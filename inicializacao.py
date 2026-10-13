"""
Abrir junto com o Windows sem privilégio de admin: um .vbs na pasta "Inicializar" do próprio usuário.
Também garante instância única (autostart + abrir manualmente não duplicam sessões/repasses).
"""
import os
import socket
import sys
from pathlib import Path

PASTA_INICIAR = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
ARQUIVO = PASTA_INICIAR / "RepasseTelegram.vbs"
PORTA_TRAVA = 47817
_trava = None


def _comando() -> tuple[str, str, str]:
    """(executável, argumentos, pasta de trabalho) do app atual."""
    if getattr(sys, "frozen", False):  # .exe do PyInstaller
        return sys.executable, "--minimizado", str(Path(sys.executable).parent)
    raiz = Path(__file__).resolve().parent
    pyw = Path(sys.executable).with_name("pythonw.exe")  # sem janela de console
    return str(pyw if pyw.exists() else Path(sys.executable)), f'"{raiz / "main.py"}" --minimizado', str(raiz)


def ativo() -> bool:
    return ARQUIVO.exists()


def ativar():
    exe, args, pasta = _comando()
    PASTA_INICIAR.mkdir(parents=True, exist_ok=True)
    ARQUIVO.write_text(
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f'sh.CurrentDirectory = "{pasta}"\r\n'
        f'sh.Run """{exe}"" {args.replace(chr(34), chr(34) * 2)}", 1, False\r\n',
        encoding="utf-8")


def desativar():
    if ARQUIVO.exists():
        ARQUIVO.unlink()


def garantir_instancia_unica() -> bool:
    """True se esta é a única instância aberta (mantém uma porta local reservada enquanto roda)."""
    global _trava
    _trava = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _trava.bind(("127.0.0.1", PORTA_TRAVA))
        _trava.listen(1)
        return True
    except OSError:
        return False
