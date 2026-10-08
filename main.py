import sys
import codecs
import customtkinter as ctk
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

    # Tema salvo
    theme = db.get_config("theme", "dark")
    ctk.set_appearance_mode(theme)
    ctk.set_default_color_theme("blue")

    # Janela principal
    from ui.main_window import MainWindow
    app = MainWindow()

    # Reconectar contas que tinham sessão salva
    _auto_reconnect()

    # Inicializar agendador de nichos se ativo
    from niche_scheduler import niche_scheduler
    if db.get_config("nicho_scheduler_ativo", "0") == "1":
        niche_scheduler.start()

    app.mainloop()


def _auto_reconnect():
    """Tenta reconectar contas que possuem sessão salva."""
    from telegram_manager import telegram_manager
    import database as db

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

                telegram_manager._run(_try_connect())
            except Exception:
                pass


if __name__ == "__main__":
    main()
