import sys
import threading
import database as db

# Garantir codificação UTF-8 para stdout e stderr no Windows
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

def main():
    # Inicializar banco
    db.init_db()

    if "--headless" in sys.argv:
        _run_headless()
        return

    import customtkinter as ctk

    # Tema salvo
    theme = db.get_config("theme", "dark")
    ctk.set_appearance_mode(theme)
    ctk.set_default_color_theme("blue")

    # Janela principal
    from ui.main_window import MainWindow
    app = MainWindow()

    _start_engine()
    app.mainloop()


def _start_engine():
    """Sobe o motor: bot (publicação + painel) e contas (que restauram seus repasses e o radar)."""
    if db.get_config("bot_token"):
        from telegram_manager import telegram_manager
        telegram_manager.iniciar_bot()
    _auto_reconnect()


def _run_headless():
    """Roda só o motor, sem interface (servidor/24h). Contas precisam ter sessão salva pela GUI."""
    if sys.stdout is None:  # exe --windowed não tem console: loga em arquivo
        log = open("data/headless.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log

    _start_engine()
    print("[Headless] Motor ativo. Ctrl+C para encerrar.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("[Headless] Encerrado.")


def _auto_reconnect():
    """Tenta reconectar contas que possuem sessão salva."""
    from telegram_manager import telegram_manager

    for conta in db.listar_contas():
        if conta.get("session"):
            try:
                api_id, api_hash = telegram_manager.get_creds()

                async def _try_connect(c=conta, aid=api_id, ah=api_hash):
                    from telethon import TelegramClient
                    from telethon.sessions import StringSession
                    client = TelegramClient(StringSession(c["session"]), aid, ah)
                    await client.connect()
                    if await client.is_user_authorized():
                        telegram_manager.clients[c["id"]] = client
                        db.atualizar_conta(c["id"], client.session.save(), "conectada")
                        telegram_manager.restaurar_repasses_conta(c["id"])
                        print(f"[Contas] {c['telefone']} conectada.")
                    else:
                        print(f"[Contas] {c['telefone']} sem sessão válida: reconecte pela GUI.")

                fut = telegram_manager._run(_try_connect())
                fut.add_done_callback(lambda f, tel=conta["telefone"]: f.exception() and print(
                    f"[Contas] Falha ao reconectar {tel}: {f.exception()}"))
            except Exception as e:
                print(f"[Contas] Falha ao reconectar {conta['telefone']}: {e}")


if __name__ == "__main__":
    main()
