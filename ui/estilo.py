"""
Identidade visual do app (PROMO DO BAIANO) e componentes reutilizáveis.
Tabelas usam ttk.Treeview: desenha milhares de linhas sem travar (CTk cria 1 widget por célula).
"""
import customtkinter as ctk
from tkinter import ttk

# Paleta: azul Bahia + laranja "promoção"
AZUL      = ("#1747a6", "#2f6fe4")
AZUL_HOV  = ("#123a88", "#2559c0")
LARANJA   = ("#f97316", "#fb923c")
VERMELHO  = ("#dc2626", "#ef4444")
VERM_HOV  = ("#b91c1c", "#dc2626")
CINZA     = ("#64748b", "#475569")
CINZA_HOV = ("#475569", "#334155")
FUNDO     = ("#f4f6fb", "#0f1115")
CARD      = ("#ffffff", "#181b22")
BORDA     = ("#e2e8f0", "#262b36")
TEXTO_SEC = ("#64748b", "#94a3b8")

FONTE        = "Segoe UI"
F_TITULO     = (FONTE, 20, "bold")
F_SUBTITULO  = (FONTE, 14, "bold")
F_NORMAL     = (FONTE, 13)
F_PEQUENA    = (FONTE, 11)


def botao(parent, texto, comando, cor="azul", largura=110, **kw):
    cores = {"azul": (AZUL, AZUL_HOV), "cinza": (CINZA, CINZA_HOV), "vermelho": (VERMELHO, VERM_HOV)}[cor]
    return ctk.CTkButton(parent, text=texto, command=comando, width=largura, height=34, corner_radius=8,
                         fg_color=cores[0], hover_color=cores[1], font=(FONTE, 12, "bold"), **kw)


def card(parent, **pack):
    c = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDA)
    c.pack(**({"fill": "x", "padx": 20, "pady": (0, 12)} | pack))
    return c


def cabecalho(parent, titulo: str, subtitulo: str = ""):
    """Título da tela + área à direita para botões (retornada)."""
    hdr = ctk.CTkFrame(parent, fg_color="transparent")
    hdr.pack(fill="x", padx=20, pady=(18, 10))
    txt = ctk.CTkFrame(hdr, fg_color="transparent")
    txt.pack(side="left")
    ctk.CTkLabel(txt, text=titulo, font=F_TITULO).pack(anchor="w")
    if subtitulo:
        ctk.CTkLabel(txt, text=subtitulo, font=F_PEQUENA, text_color=TEXTO_SEC).pack(anchor="w")
    acoes = ctk.CTkFrame(hdr, fg_color="transparent")
    acoes.pack(side="right")
    return acoes


def _cor(par):
    return par[1] if ctk.get_appearance_mode() == "Dark" else par[0]


def aplicar_estilo_tabela():
    st = ttk.Style()
    st.theme_use("clam")
    fundo, texto = _cor(CARD), _cor(("#0f172a", "#e5e7eb"))
    st.configure("App.Treeview", background=fundo, fieldbackground=fundo, foreground=texto,
                 rowheight=30, font=(FONTE, 10), borderwidth=0, relief="flat")
    st.configure("App.Treeview.Heading", background=_cor(("#eef2f8", "#1f2430")), foreground=texto,
                 font=(FONTE, 10, "bold"), relief="flat", padding=(8, 6))
    st.map("App.Treeview", background=[("selected", _cor(AZUL))], foreground=[("selected", "white")])
    st.map("App.Treeview.Heading", background=[("active", _cor(("#e2e8f0", "#262b36")))])


class Tabela(ctk.CTkFrame):
    """Treeview com rolagem, colunas proporcionais à largura e linhas zebradas."""

    def __init__(self, parent, colunas: list[tuple[str, str, int]], altura: int = 12, multipla=False):
        # colunas: (id, título, peso relativo da largura)
        super().__init__(parent, fg_color="transparent")
        aplicar_estilo_tabela()
        self._pesos = {c: p for c, _, p in colunas}
        self.tree = ttk.Treeview(self, columns=[c for c, _, _ in colunas], show="headings", height=altura,
                                 style="App.Treeview", selectmode="extended" if multipla else "browse")
        for c, titulo, _ in colunas:
            self.tree.heading(c, text=titulo, anchor="w")
            self.tree.column(c, anchor="w", stretch=True, minwidth=40)
        ys = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("par", background=_cor(("#f8fafc", "#1c2029")))
        self.tree.bind("<Configure>", self._redimensionar)

    def _redimensionar(self, event):
        total = sum(self._pesos.values())
        for c, p in self._pesos.items():
            self.tree.column(c, width=int(event.width * p / total))

    def carregar(self, linhas: list[tuple], ids: list[str] = None):
        self.tree.delete(*self.tree.get_children())
        for i, linha in enumerate(linhas):
            self.tree.insert("", "end", iid=ids[i] if ids else None, values=linha,
                             tags=("par",) if i % 2 else ())

    def selecionado(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel else None
