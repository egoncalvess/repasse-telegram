"""
IBM Plex Sans (licença OFL, assets/fonts/) registrada só para este processo, sem instalar no Windows.
Se o arquivo faltar ou o registro falhar, o app usa Segoe UI sem erro.
"""
import sys
from pathlib import Path

ARQUIVOS = ("IBMPlexSans-Regular.ttf", "IBMPlexSans-SemiBold.ttf", "IBMPlexSans-Bold.ttf")
FR_PRIVATE = 0x10

# Nomes de família como o Windows (GDI) registra: SemiBold vira uma família à parte
PLEX, PLEX_SEMI = "IBM Plex Sans", "IBM Plex Sans SmBld"
RESERVA, RESERVA_SEMI = "Segoe UI", "Segoe UI Semibold"

_registradas: bool | None = None


def recurso(rel: str) -> Path:
    """Caminho de arquivo empacotado (funciona no .exe do PyInstaller e no código-fonte)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / rel


def registrar() -> bool:
    """Registra as fontes (uma vez por processo). True se a IBM Plex Sans ficou disponível."""
    global _registradas
    if _registradas is not None:
        return _registradas
    _registradas = False
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ok = [ctypes.windll.gdi32.AddFontResourceExW(str(recurso(f"assets/fonts/{a}")), FR_PRIVATE, 0)
                  for a in ARQUIVOS if recurso(f"assets/fonts/{a}").exists()]
            _registradas = len(ok) == len(ARQUIVOS) and all(ok)
        except Exception as e:
            print(f"[Fontes] IBM Plex Sans indisponível ({e}); usando Segoe UI.")
    return _registradas


def familias() -> tuple[str, str]:
    """(família regular/negrito, família semibold)."""
    return (PLEX, PLEX_SEMI) if registrar() else (RESERVA, RESERVA_SEMI)
