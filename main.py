import os
import signal
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("TZ", "America/Sao_Paulo")
if hasattr(time, "tzset"):
    time.tzset()

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
        db.DATA_DIR.mkdir(parents=True, exist_ok=True)
        log = open(db.DATA_DIR / "app.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log

    import inicializacao
    if not inicializacao.garantir_instancia_unica():
        print("[App] Já existe uma instância aberta; encerrando esta.")
        if "--headless" not in sys.argv:
            try:
                import tkinter as tk
                from tkinter import messagebox
                raiz = tk.Tk()
                raiz.withdraw()
                messagebox.showinfo("Repasse Telegram", "O app já está aberto (veja a barra de tarefas/bandeja).")
            except Exception:
                pass
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
    web_srv = _start_web()
    try:
        app.mainloop()
    finally:
        if web_srv is not None:
            web_srv.should_exit = True


def _start_engine():
    """Sobe o motor: bot (publicação + painel), contas (repasses + radar) e rotinas autônomas."""
    from telegram_manager import telegram_manager
    import autonomia
    if db.get_config("bot_token"):
        telegram_manager.iniciar_bot()
    _auto_reconnect()
    telegram_manager._run(autonomia.iniciar(telegram_manager))


def _run_headless(parar_evento: threading.Event | None = None):
    """Roda só o motor, sem interface (servidor/24h). Contas precisam ter sessão salva pela GUI."""
    from telegram_manager import telegram_manager

    parar = parar_evento or threading.Event()

    def _ao_sinal(signum, _frame):
        nome = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        print(f"[Headless] Sinal {nome} recebido; desconectando...")
        parar.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _ao_sinal)
        except (ValueError, OSError):
            pass

    _start_engine()
    web_srv = _start_web()
    print("[Headless] Motor ativo. Ctrl+C ou SIGTERM para encerrar.")
    try:
        while not parar.is_set():
            parar.wait(timeout=1.0)
    except KeyboardInterrupt:
        print("[Headless] Interrompido; desconectando...")
    finally:
        if web_srv is not None:
            web_srv.should_exit = True
        telegram_manager.encerrar()
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



def _start_web():
    """Sobe o servidor Web (FastAPI/Uvicorn) em thread única no mesmo processo (zero duplicação de StringSession)."""
    if "--no-web" in sys.argv or db.get_config("web_enabled", "1") != "1":
        return None
    try:
        import uvicorn
        from web.auth import obter_ip_rede_local
        host = (os.environ.get("WEB_HOST") or db.get_config("web_host", "0.0.0.0") or "0.0.0.0").strip()
        port = int(os.environ.get("WEB_PORT") or db.get_config("web_port", "8080") or 8080)
        cfg = uvicorn.Config("web.app:app", host=host, port=port, workers=1, log_level="warning", access_log=False)
        server = uvicorn.Server(cfg)
        server.install_signal_handlers = lambda: None
        t = threading.Thread(target=server.run, name="web-uvicorn", daemon=True)
        t.start()
        ip_lan = obter_ip_rede_local()
        print(f"[Web] Ativo em http://127.0.0.1:{port} · Rede local (celular): http://{ip_lan}:{port}")
        return server
    except Exception as e:
        print(f"[Web] Falha ao iniciar servidor web: {e}")
        return None

if __name__ == "__main__":
    main()
