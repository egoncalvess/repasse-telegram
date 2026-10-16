import os
import sys
import threading
from pathlib import Path

import database as db

# Garantir codificação UTF-8 para stdout e stderr no Windows
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

def _pasta_do_app() -> Path:
    """Pasta do .exe (ou do main.py): data/ fica sempre ao lado do app, qualquer que seja a pasta de início do atalho."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def main():
    os.chdir(_pasta_do_app())  # caminhos relativos (data/repasse.db, data/imagens, backups, log) partem daqui

    # Inicializar banco
    db.init_db()

    if sys.stdout is None:  # pythonw / exe sem console: log em arquivo
        log = open("data/app.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log

    import inicializacao
    if not inicializacao.garantir_instancia_unica():
        print("[App] Já existe uma instância aberta; encerrando esta.")
        if "--headless" not in sys.argv:
            import tkinter as tk
            from tkinter import messagebox
            raiz = tk.Tk()
            raiz.withdraw()
            messagebox.showinfo("Repasse Telegram", "O app já está aberto (veja a barra de tarefas/bandeja).")
        return

    if "--headless" in sys.argv:
        _run_headless()
        return

    import customtkinter as ctk

    # IBM Plex Sans registrada antes de criar a janela (cai para Segoe UI se faltar)
    from ui import fontes
    fontes.registrar()

    # Tema salvo
    theme = db.get_config("theme", "dark")
    ctk.set_appearance_mode(theme)
    ctk.set_default_color_theme("blue")

    # Janela principal
    from ui.main_window import MainWindow
    app = MainWindow()

    if "--minimizado" in sys.argv or db.get_config("start_minimized", "0") == "1":
        app.iconify()

    _start_engine()
    app.mainloop()


def _start_engine():
    """Sobe o motor: bot (publicação + painel), contas (repasses + radar) e rotinas autônomas."""
    from telegram_manager import telegram_manager
    import autonomia
    if db.get_config("bot_token"):
        telegram_manager.iniciar_bot()
    _auto_reconnect()
    telegram_manager._run(autonomia.iniciar(telegram_manager))


def _run_headless():
    """Roda só o motor, sem interface (servidor/24h). Contas precisam ter sessão salva pela GUI."""
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
