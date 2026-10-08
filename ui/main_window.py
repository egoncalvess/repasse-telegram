import customtkinter as ctk

# Paleta
SB_BG     = "#0f1923"   # sidebar fundo
SB_HOVER  = "#1a2840"   # sidebar hover
ACCENT    = "#1a6fd4"   # azul selecionado
ACCENT_H  = "#1558ab"   # azul hover
CONTENT   = ("#f1f5fb", "#121212")   # fundo do conteúdo (light, dark)
TEXT_LT   = "#e8eef6"   # texto claro
TEXT_DIM  = "#6b8099"   # texto apagado
SUCCESS   = "#27ae60"
DANGER    = "#e74c3c"


class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Repasse Automático — Telegram")
        self.geometry("1150x700")
        self.minsize(900, 580)
        self.configure(fg_color=CONTENT)

        self._build_sidebar()
        self._build_content()
        self._load_frames()
        self.show_frame("repasses")

    # ── Sidebar ──────────────────────────────────────────────────────────────

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=210, corner_radius=0, fg_color=SB_BG)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)
        self._sb = sb

        # Logo
        logo = ctk.CTkFrame(sb, fg_color="#0a1320", corner_radius=0)
        logo.pack(fill="x")
        ctk.CTkLabel(logo, text="🤖", font=("Segoe UI Emoji", 40)).pack(pady=(22, 4))
        ctk.CTkLabel(logo, text="Repasse Auto", font=("Arial", 15, "bold"),
                     text_color=TEXT_LT).pack()
        ctk.CTkLabel(logo, text="Telegram Manager", font=("Arial", 10),
                     text_color=TEXT_DIM).pack(pady=(2, 18))

        # Nav
        self._nav_btns: dict[str, ctk.CTkButton] = {}
        nav = [
            ("contas",        "👤   Contas"),
            ("repasses",      "📨   Repasses"),
            ("disparador",    "🚀   Disparador"),
            ("radar",         "📉   Radar de Preços"),
            ("integracoes",   "🔗   Integrações"),
            ("configuracoes", "⚙️   Configurações"),
        ]
        nav_wrap = ctk.CTkFrame(sb, fg_color="transparent")
        nav_wrap.pack(fill="both", expand=True, pady=12)

        for key, label in nav:
            btn = ctk.CTkButton(
                nav_wrap, text=label, anchor="w",
                fg_color="transparent", hover_color=SB_HOVER,
                text_color=TEXT_LT, font=("Arial", 13),
                height=46, corner_radius=6,
                command=lambda k=key: self.show_frame(k)
            )
            btn.pack(fill="x", padx=10, pady=2)
            self._nav_btns[key] = btn

        ctk.CTkLabel(sb, text="v1.0.0", font=("Arial", 10),
                     text_color=TEXT_DIM).pack(side="bottom", pady=10)

    # ── Content ──────────────────────────────────────────────────────────────

    def _build_content(self):
        self._content = ctk.CTkFrame(self, corner_radius=0, fg_color=CONTENT)
        self._content.pack(side="left", fill="both", expand=True)

    def _load_frames(self):
        from ui.contas_frame import ContasFrame
        from ui.repasses_frame import RepassesFrame
        from ui.disparador_frame import DisparadorFrame
        from ui.integracoes_frame import IntegracoesFrame
        from ui.configuracoes_frame import ConfiguracoesFrame
        from ui.radar_frame import RadarFrame

        self._frames = {
            "contas":        ContasFrame(self._content),
            "repasses":      RepassesFrame(self._content),
            "disparador":    DisparadorFrame(self._content),
            "radar":         RadarFrame(self._content),
            "integracoes":   IntegracoesFrame(self._content),
            "configuracoes": ConfiguracoesFrame(self._content),
        }

    def show_frame(self, name: str):
        for f in self._frames.values():
            f.pack_forget()
        for k, btn in self._nav_btns.items():
            btn.configure(fg_color=ACCENT if k == name else "transparent")
        self._frames[name].pack(fill="both", expand=True)
        if hasattr(self._frames[name], "refresh"):
            self._frames[name].refresh()
