import sys
from pathlib import Path

import customtkinter as ctk
from PIL import Image

from ui.estilo import AZUL, FUNDO, FONTE, TEXTO_SEC

SB_BG    = ("#0b1d4a", "#0a1430")   # barra lateral (azul Bahia escuro)
SB_HOVER = ("#163172", "#14224d")
SB_TEXT  = "#e8eef8"


def recurso(rel: str) -> Path:
    """Caminho de arquivo empacotado (funciona no .exe do PyInstaller e no código-fonte)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / rel


class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("PROMO DO BAIANO — Repasse & Radar")
        self.geometry("1240x760")
        self.minsize(980, 620)
        self.configure(fg_color=FUNDO)
        try:
            self.iconbitmap(str(recurso("assets/logo.ico")))
        except Exception:
            pass

        self._build_sidebar()
        self._content = ctk.CTkFrame(self, corner_radius=0, fg_color=FUNDO)
        self._content.pack(side="left", fill="both", expand=True)
        self._load_frames()
        self.show_frame("repasses")
        self.after(2000, self._atualizar_status)

    # ── Sidebar ──────────────────────────────────────────────────────────────

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=230, corner_radius=0, fg_color=SB_BG)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        marca = ctk.CTkFrame(sb, fg_color="transparent")
        marca.pack(fill="x", padx=16, pady=(22, 18))
        try:
            img = ctk.CTkImage(Image.open(recurso("assets/logo.png")), size=(46, 46))
            ctk.CTkLabel(marca, image=img, text="").pack(side="left")
        except Exception:
            ctk.CTkLabel(marca, text="🏷️", font=(FONTE, 32)).pack(side="left")
        txt = ctk.CTkFrame(marca, fg_color="transparent")
        txt.pack(side="left", padx=10)
        ctk.CTkLabel(txt, text="PROMO DO", font=(FONTE, 13, "bold"), text_color=SB_TEXT).pack(anchor="w")
        ctk.CTkLabel(txt, text="BAIANO", font=(FONTE, 17, "bold"), text_color="#fb923c").pack(anchor="w")

        self._nav_btns: dict[str, ctk.CTkButton] = {}
        nav = [
            ("repasses",      "📨   Repasses"),
            ("radar",         "📉   Radar de Preços"),
            ("contas",        "👤   Contas"),
            ("integracoes",   "🔗   Afiliados"),
            ("banco",         "🗄️   Banco de Dados"),
            ("configuracoes", "⚙️   Configurações"),
        ]
        for key, label in nav:
            btn = ctk.CTkButton(sb, text=label, anchor="w", fg_color="transparent", hover_color=SB_HOVER,
                                text_color=SB_TEXT, font=(FONTE, 13), height=42, corner_radius=8,
                                command=lambda k=key: self.show_frame(k))
            btn.pack(fill="x", padx=12, pady=2)
            self._nav_btns[key] = btn

        self._status = ctk.CTkLabel(sb, text="", font=(FONTE, 11), text_color=SB_TEXT, justify="left", anchor="w")
        self._status.pack(side="bottom", fill="x", padx=18, pady=16)

    def _atualizar_status(self):
        """Rodapé da barra lateral: conta, bot e piloto (atualiza a cada 5 s)."""
        try:
            import database as db
            from telegram_manager import telegram_manager as tm
            linhas = [f"{'🟢' if tm.clients else '🔴'} Conta {'conectada' if tm.clients else 'desconectada'}",
                      f"{'🟢' if tm.bot else '⚪'} Bot {'online' if tm.bot else 'offline'}",
                      f"{'🤖' if db.get_config('piloto_ativo', '0') == '1' else '⏸'} Piloto "
                      f"{'ligado' if db.get_config('piloto_ativo', '0') == '1' else 'desligado'}"]
            if db.get_config("pausado", "0") == "1":
                linhas.append("⏸ PAUSA GERAL")
            self._status.configure(text="\n".join(linhas))
        finally:
            self.after(5000, self._atualizar_status)

    # ── Content ──────────────────────────────────────────────────────────────

    def _load_frames(self):
        from ui.contas_frame import ContasFrame
        from ui.repasses_frame import RepassesFrame
        from ui.integracoes_frame import IntegracoesFrame
        from ui.configuracoes_frame import ConfiguracoesFrame
        from ui.radar_frame import RadarFrame
        from ui.banco_frame import BancoFrame

        self._frames = {
            "contas":        ContasFrame(self._content),
            "repasses":      RepassesFrame(self._content),
            "radar":         RadarFrame(self._content),
            "integracoes":   IntegracoesFrame(self._content),
            "banco":         BancoFrame(self._content),
            "configuracoes": ConfiguracoesFrame(self._content),
        }

    def show_frame(self, name: str):
        for f in self._frames.values():
            f.pack_forget()
        for k, btn in self._nav_btns.items():
            btn.configure(fg_color=AZUL if k == name else "transparent")
        self._frames[name].pack(fill="both", expand=True)
        if hasattr(self._frames[name], "refresh"):
            self._frames[name].refresh()
