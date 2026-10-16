"""
Sistema de design do app: única fonte de cor, tipografia, espaçamento e componentes da interface.
Ferramenta de operação, não vitrine: o preço é o único destaque forte; o resto é quieto.

Cores são tuplas (claro, escuro). AZUL só para ação principal, item ativo e foco; QUEDA só para queda de
preço e status ok; ERRO só para erro, falha e ação destrutiva. O laranja da marca existe apenas no logo.
"""
import tkinter as tk
from tkinter import font as tkfont

import customtkinter as ctk

from ui import fontes

# ── Cores ─────────────────────────────────────────────────────────────────────

FUNDO      = ("#F7F8FA", "#14161A")   # janela e barra lateral
SUPERFICIE = ("#FFFFFF", "#1B1E24")   # painel de detalhe, diálogos, campos
LINHA      = ("#E4E7EC", "#2A2E36")   # divisórias de 1 px e bordas de campo
TINTA      = ("#1A1D23", "#E8EAEE")   # texto principal
TINTA_2    = ("#6B7280", "#9AA1AC")   # texto secundário, cabeçalhos de tabela
AZUL       = ("#1F4FD1", "#5B8CFF")
QUEDA      = ("#0E8A5F", "#3CCB8F")
ERRO       = ("#C62828", "#F2645A")
BRANCO     = ("#FFFFFF", "#FFFFFF")   # só o texto do botão primário


def _mistura(a: str, b: str, t: float) -> str:
    ra, ga, ba = (int(a[i:i + 2], 16) for i in (1, 3, 5))
    rb, gb, bb = (int(b[i:i + 2], 16) for i in (1, 3, 5))
    return "#{:02X}{:02X}{:02X}".format(*(round(x + (y - x) * t) for x, y in ((ra, rb), (ga, gb), (ba, bb))))


def mistura(par_a: tuple, par_b: tuple, t: float) -> tuple:
    """Tons derivados da paleta (nenhuma cor nova): par_a com t de par_b, em cada tema."""
    return _mistura(par_a[0], par_b[0], t), _mistura(par_a[1], par_b[1], t)


AZUL_HOVER = mistura(AZUL, TINTA, 0.18)
SELECAO    = mistura(SUPERFICIE, AZUL, 0.12)   # linha selecionada: AZUL a 12% sobre SUPERFICIE
REALCE     = mistura(FUNDO, TINTA, 0.05)       # hover de botão secundário e de item da navegação

ESTADOS = {"ok": QUEDA, "inativo": TINTA_2, "falha": ERRO}


def cor(par) -> str:
    """Cor do tema atual (para tk.Canvas, que não entende tuplas)."""
    if isinstance(par, str):
        return par
    return par[1] if ctk.get_appearance_mode() == "Dark" else par[0]


def aplicar_tema(modo: str):
    """'light' | 'dark' | 'system'. CTk se redesenha; Tabela, gráficos e pontos acompanham pelo tracker."""
    ctk.set_appearance_mode(modo)


# ── Tipografia (só estes tamanhos) ────────────────────────────────────────────

FAMILIA, FAMILIA_SEMI = fontes.familias()
F_LEGENDA     = (FAMILIA, 12)
F_CORPO       = (FAMILIA, 13)
F_CORPO_FORTE = (FAMILIA_SEMI, 13)   # item ativo da navegação, texto do botão primário
F_SECAO       = (FAMILIA_SEMI, 15)
F_TITULO      = (FAMILIA_SEMI, 20)
F_PRECO       = (FAMILIA, 32, "bold")

def fonte_tk(fonte: tuple, escala: float = 1.0) -> tuple:
    """Fonte da escala para tk.Canvas (em pixels, como o CTk): fonte_tk(F_LEGENDA, escala do widget)."""
    familia, tamanho, *resto = fonte
    return (familia, -round(tamanho * escala), *resto)


# ── Espaço ────────────────────────────────────────────────────────────────────

E1, E2, E3, E4 = 8, 16, 24, 32
MARGEM = E4
RAIO = 6
ALTURA_BOTAO = 34
LARGURA_LATERAL = 208
LARGURA_DETALHE = 360
MIN_FLEXIVEL = 160   # largura mínima que a Tabela reserva para as colunas sem mínimo


def _largura(texto: str) -> int:
    return max(72, len(texto) * 8 + E3)


# ── Botões ────────────────────────────────────────────────────────────────────

def botao_primario(parent, texto, comando, largura=None, **kw):
    """Ação principal. No máximo um por tela."""
    return ctk.CTkButton(parent, text=texto, command=comando, width=largura or _largura(texto),
                         height=ALTURA_BOTAO, corner_radius=RAIO, fg_color=AZUL, hover_color=AZUL_HOVER,
                         text_color=BRANCO, text_color_disabled=mistura(BRANCO, AZUL, 0.35),
                         font=F_CORPO_FORTE, **kw)


def botao(parent, texto, comando, largura=None, **kw):
    """Secundário: transparente, borda de 1 px."""
    return ctk.CTkButton(parent, text=texto, command=comando, width=largura or _largura(texto),
                         height=ALTURA_BOTAO, corner_radius=RAIO, fg_color="transparent", hover_color=REALCE,
                         border_width=1, border_color=LINHA, text_color=TINTA, text_color_disabled=TINTA_2,
                         font=F_CORPO, **kw)


def botao_texto(parent, texto, comando, perigo=False, **kw):
    """Ação leve, sem borda. perigo=True para remover/descartar."""
    return ctk.CTkButton(parent, text=texto, command=comando, width=_largura(texto) - E2, height=28,
                         corner_radius=RAIO, fg_color="transparent", hover_color=REALCE, border_width=0,
                         text_color=ERRO if perigo else AZUL, text_color_disabled=TINTA_2, font=F_CORPO, **kw)


# ── Texto e campos ────────────────────────────────────────────────────────────

def rotulo(parent, texto="", fonte=F_CORPO, secundario=False, **kw):
    return ctk.CTkLabel(parent, text=texto, font=fonte, text_color=TINTA_2 if secundario else TINTA,
                        justify="left", anchor="w", **kw)


def ajustar_quebra(lbl, folga=4):
    """Faz o rótulo quebrar linha na largura que ele ocupa. Usa a largura real do widget (não a do evento, que
    também vem do rótulo interno) e aplica depois, em idle, só quando muda de verdade: sem laço de redesenho."""
    estado = {"largura": 0, "pendente": False}

    def _aplicar():
        estado["pendente"] = False
        if not lbl.winfo_exists():
            return
        largura = lbl.winfo_width()
        if largura > 1 and abs(largura - estado["largura"]) >= E1:
            estado["largura"] = largura
            lbl.configure(wraplength=max(120, largura - folga))

    def _mudou(_ev):
        if not estado["pendente"]:
            estado["pendente"] = True
            lbl.after_idle(_aplicar)

    lbl.bind("<Configure>", _mudou, add="+")
    return lbl


def paragrafo(parent, texto="", fonte=F_LEGENDA, secundario=True, **pack):
    """Texto explicativo que quebra linha na largura disponível (empacotado com fill="x")."""
    lbl = rotulo(parent, texto, fonte, secundario=secundario)
    lbl.pack(**({"fill": "x", "anchor": "w"} | pack))
    return ajustar_quebra(lbl)


def entrada(parent, largura=320, oculto=False, **kw):
    return ctk.CTkEntry(parent, width=largura, height=ALTURA_BOTAO, corner_radius=RAIO, border_width=1,
                        border_color=LINHA, fg_color=SUPERFICIE, text_color=TINTA, placeholder_text_color=TINTA_2,
                        font=F_CORPO, show="*" if oculto else "", **kw)


def campo(parent, titulo, valor="", largura=320, oculto=False, dica="", **pack):
    """Rótulo acima do campo (formulários em uma coluna). Devolve o CTkEntry."""
    caixa = ctk.CTkFrame(parent, fg_color="transparent")
    caixa.pack(**({"anchor": "w", "fill": "x", "pady": (0, E2)} | pack))
    rotulo(caixa, titulo, F_LEGENDA, secundario=True).pack(anchor="w", pady=(0, 4))
    ent = entrada(caixa, largura, oculto, placeholder_text=dica)
    if valor not in (None, ""):
        ent.insert(0, str(valor))
    ent.pack(anchor="w")
    return ent


def menu(parent, variavel, valores, comando=None, largura=200):
    """Lista de escolha com cara de campo (borda LINHA); só escolhe, não aceita digitação."""
    caixa = ctk.CTkComboBox(parent, variable=variavel, values=valores, command=comando, width=largura,
                            height=ALTURA_BOTAO, corner_radius=RAIO, border_width=1, border_color=LINHA,
                            fg_color=SUPERFICIE, button_color=LINHA, button_hover_color=mistura(LINHA, TINTA, 0.12),
                            text_color=TINTA, font=F_CORPO, dropdown_font=F_CORPO, dropdown_fg_color=SUPERFICIE,
                            dropdown_text_color=TINTA, dropdown_hover_color=SELECAO, state="readonly")
    try:  # clicar no texto também abre a lista, não só a seta
        caixa._entry.bind("<Button-1>", lambda _: caixa._open_dropdown_menu())
    except AttributeError:
        pass
    return caixa


class Segmentado(ctk.CTkFrame):
    """Escolha entre poucas opções: a escolhida tem fundo AZUL a 12% e borda AZUL; as outras, borda LINHA."""

    def __init__(self, parent, valores, variavel, comando=None):
        super().__init__(parent, fg_color="transparent")
        self._var, self._cmd = variavel, comando
        self._botoes = {}
        for i, v in enumerate(valores):
            b = ctk.CTkButton(self, text=v, command=lambda v=v: self._escolher(v), width=_largura(v),
                              height=ALTURA_BOTAO, corner_radius=RAIO, border_width=1, font=F_CORPO, text_color=TINTA)
            b.pack(side="left", padx=(0 if i == 0 else E1, 0))
            self._botoes[v] = b
        variavel.trace_add("write", lambda *_: self._pintar())
        self._pintar()

    def _escolher(self, valor):
        self._var.set(valor)
        if self._cmd:
            self._cmd(valor)

    def _pintar(self):
        for v, b in self._botoes.items():
            ativo = v == self._var.get()
            b.configure(fg_color=SELECAO if ativo else "transparent", hover_color=SELECAO if ativo else REALCE,
                        border_color=AZUL if ativo else LINHA)


def segmentado(parent, valores, variavel, comando=None) -> Segmentado:
    return Segmentado(parent, valores, variavel, comando)


def interruptor(parent, texto, variavel, comando=None):
    return ctk.CTkSwitch(parent, text=texto, variable=variavel, command=comando, font=F_CORPO, text_color=TINTA,
                         progress_color=AZUL, fg_color=LINHA, button_color=BRANCO, button_hover_color=SUPERFICIE)


def caixa_marcar(parent, texto, **kw):
    return ctk.CTkCheckBox(parent, text=texto, font=F_CORPO, text_color=TINTA, fg_color=AZUL, hover_color=AZUL_HOVER,
                           border_color=TINTA_2, border_width=1, corner_radius=4, checkbox_width=18,
                           checkbox_height=18, **kw)


def area_rolavel(parent, fundo=FUNDO):
    return ctk.CTkScrollableFrame(parent, fg_color=fundo, corner_radius=0, scrollbar_button_color=LINHA,
                                  scrollbar_button_hover_color=TINTA_2)


# ── Estrutura ─────────────────────────────────────────────────────────────────

def divisoria(parent, vertical=False):
    """Linha LINHA de 1 px (o chamador faz o pack/grid)."""
    return ctk.CTkFrame(parent, width=1 if vertical else 0, height=0 if vertical else 1, corner_radius=0,
                        fg_color=LINHA)


def cabecalho(parent, titulo: str, subtitulo: str = ""):
    """Título da tela à esquerda; devolve a área de ações (à direita)."""
    hdr = ctk.CTkFrame(parent, fg_color="transparent")
    hdr.pack(fill="x", padx=MARGEM, pady=(E3, E2))
    txt = ctk.CTkFrame(hdr, fg_color="transparent")
    txt.pack(side="left")
    rotulo(txt, titulo, F_TITULO).pack(anchor="w")
    if subtitulo:
        rotulo(txt, subtitulo, F_LEGENDA, secundario=True).pack(anchor="w")
    acoes = ctk.CTkFrame(hdr, fg_color="transparent", width=1, height=1)  # vazio não ocupa 200 px (padrão do CTk)
    acoes.pack(side="right")
    return acoes


def acao(acoes, widget):
    """Empilha um botão na área de ações do cabeçalho (da esquerda para a direita)."""
    widget.pack(side="left", padx=(E1, 0))
    return widget


def secao(parent, titulo: str = "", linha=True, padx=MARGEM, **pack):
    """Bloco de conteúdo: linha de 1 px no topo, título F_SECAO e espaço. Devolve o frame do bloco."""
    bloco = ctk.CTkFrame(parent, fg_color="transparent")
    bloco.pack(**({"fill": "x", "padx": padx, "pady": (0, E3)} | pack))
    if linha:
        divisoria(bloco).pack(fill="x", pady=(0, E2))
    if titulo:
        rotulo(bloco, titulo, F_SECAO).pack(anchor="w", pady=(0, E1))
    return bloco


class PontoStatus(ctk.CTkFrame):
    """Círculo de 8 px (QUEDA ok, TINTA_2 inativo, ERRO falha) + texto."""

    def __init__(self, parent, estado="inativo", texto="", fundo=FUNDO, fonte=F_LEGENDA):
        super().__init__(parent, fg_color="transparent")
        self._fundo, self._estado = fundo, estado
        s = self._get_widget_scaling()
        self._d = round(8 * s)
        # não usar self._canvas: o CTkFrame já usa esse nome para o próprio desenho
        self._ponto = tk.Canvas(self, width=self._d, height=self._d, highlightthickness=0, bd=0)
        self._ponto.pack(side="left", padx=(0, E1))
        self._rotulo = rotulo(self, texto, fonte)
        self._rotulo.pack(side="left")
        self._desenhar()
        ctk.AppearanceModeTracker.add(lambda _m: self.after(0, self._desenhar), self)

    def atualizar(self, estado: str, texto: str = None, cor_texto=None):
        self._estado = estado
        if texto is not None:
            self._rotulo.configure(text=texto)
        self._rotulo.configure(text_color=cor_texto or TINTA)
        self._desenhar()

    def _desenhar(self):
        if not self.winfo_exists():
            return
        self._ponto.configure(bg=cor(self._fundo))
        self._ponto.delete("all")
        self._ponto.create_oval(0, 0, self._d - 1, self._d - 1, outline="",
                                 fill=cor(ESTADOS.get(self._estado, TINTA_2)))


def ponto_status(parent, estado="inativo", texto="", fundo=FUNDO, fonte=F_LEGENDA) -> PontoStatus:
    return PontoStatus(parent, estado, texto, fundo, fonte)


def estado_vazio(parent, texto, acao_texto=None, comando=None, primario=False):
    """Tela sem dados: uma frase direta e um botão que resolve."""
    caixa = ctk.CTkFrame(parent, fg_color="transparent")
    rotulo(caixa, texto, F_CORPO, secundario=True, wraplength=520).pack(anchor="w", pady=(0, E2))
    if acao_texto:
        (botao_primario if primario else botao)(caixa, acao_texto, comando).pack(anchor="w")
    return caixa


def janela(top, titulo: str, largura: int, altura: int, parent=None):
    """Prepara um diálogo (CTkToplevel) em SUPERFICIE, modal sobre a janela de origem."""
    top.title(titulo)
    top.geometry(f"{largura}x{altura}")
    top.configure(fg_color=SUPERFICIE)
    if parent is not None:
        top.transient(parent.winfo_toplevel())
    top.after(50, lambda: top.winfo_exists() and top.grab_set())
    top.bind("<Escape>", lambda _: top.destroy())


def rodape_dialogo(top, texto_primario, comando, cancelar="Cancelar"):
    """Linha de botões do diálogo: primária à direita, Cancelar ao lado."""
    rod = ctk.CTkFrame(top, fg_color="transparent")
    rod.pack(side="bottom", fill="x", padx=E3, pady=E3)
    principal = botao_primario(rod, texto_primario, comando)
    principal.pack(side="right")
    botao(rod, cancelar, top.destroy).pack(side="right", padx=(0, E1))
    return principal


# ── Tabela ────────────────────────────────────────────────────────────────────

class Tabela(ctk.CTkFrame):
    """
    Lista em tk.Canvas: sem zebra, linha de 36 px, cabeçalho em TINTA_2 regular, seleção AZUL a 12%.
    colunas: (id, título, peso[, opções]) — opções: alinhar="e" (preço), tipo="queda" | "status" | "secundario",
    min=largura mínima em px (o preço nunca é cortado), opcional=True (some quando falta espaço).
    Células de tipo "status" recebem (estado, texto). Uma célula pode trazer (texto, "queda"/"erro"/"secundario")
    para sobrepor a cor. fixa=True: peso vira largura em px e aparece rolagem horizontal.
    """

    ALTURA_LINHA, ALTURA_CAB, PAD = 36, 32, 8

    def __init__(self, parent, colunas, fundo=FUNDO, fixa=False):
        super().__init__(parent, fg_color="transparent")
        self._cols = [{"id": c[0], "titulo": c[1], "peso": c[2], **(c[3] if len(c) > 3 else {})} for c in colunas]
        self._fundo, self._fixa = fundo, fixa
        self._linhas: list[tuple] = []
        self._ids: list[str] = []
        self._sel: str | None = None
        self._ao_selecionar = self._ao_duplo = self._ao_clicar = None
        self._corte: dict = {}

        s = self._get_widget_scaling()
        self._h, self._hc, self._pad = round(self.ALTURA_LINHA * s), round(self.ALTURA_CAB * s), round(self.PAD * s)
        self._f_corpo = tkfont.Font(font=fonte_tk(F_CORPO, s))
        self._f_cab = tkfont.Font(font=fonte_tk(F_LEGENDA, s))
        self._raio = round(4 * s)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.cab = tk.Canvas(self, height=self._hc, highlightthickness=0, bd=0)
        self.cab.grid(row=0, column=0, sticky="ew")
        self.corpo = tk.Canvas(self, highlightthickness=0, bd=0, takefocus=1, yscrollincrement=self._h)
        self.corpo.grid(row=1, column=0, sticky="nsew")
        ys = ctk.CTkScrollbar(self, orientation="vertical", command=self.corpo.yview, fg_color="transparent",
                              button_color=LINHA, button_hover_color=TINTA_2, width=12)
        ys.grid(row=1, column=1, sticky="ns")
        self.corpo.configure(yscrollcommand=ys.set)
        if fixa:
            xs = ctk.CTkScrollbar(self, orientation="horizontal", command=self._xview, fg_color="transparent",
                                  button_color=LINHA, button_hover_color=TINTA_2, height=12)
            xs.grid(row=2, column=0, sticky="ew")
            self.corpo.configure(xscrollcommand=xs.set)

        self.corpo.bind("<Configure>", lambda _: self._desenhar())
        self.corpo.bind("<Button-1>", self._clique)
        self.corpo.bind("<Double-1>", self._duplo)
        self.corpo.bind("<Up>", lambda _: self._mover(-1))
        self.corpo.bind("<Down>", lambda _: self._mover(1))
        for w in (self.corpo, self.cab):
            w.bind("<MouseWheel>", lambda e: self.corpo.yview_scroll(int(-e.delta / 120), "units"))
            w.bind("<Shift-MouseWheel>", lambda e: self._xview("scroll", int(-e.delta / 120), "units"))
        ctk.AppearanceModeTracker.add(lambda _m: self.after(0, self._desenhar), self)

    # ── API ──────────────────────────────────────────────────────────────────

    def carregar(self, linhas: list[tuple], ids: list = None):
        self._linhas = list(linhas)
        self._ids = [str(i) for i in ids] if ids is not None else [str(i) for i in range(len(linhas))]
        if self._sel not in self._ids:
            self._sel = None
        self._desenhar()

    def selecionado(self) -> str | None:
        return self._sel

    def selecionar(self, iid):
        iid = None if iid is None else str(iid)
        self._sel = iid if iid in self._ids else None
        self._desenhar()
        if self._sel is not None:
            self._mostrar(self._ids.index(self._sel))

    def ao_selecionar(self, fn):
        self._ao_selecionar = fn

    def ao_duplo_clique(self, fn):
        self._ao_duplo = fn

    def ao_clicar(self, fn):
        """Chamado a cada clique numa linha, mesmo já selecionada (ex.: marcar/desmarcar)."""
        self._ao_clicar = fn

    # ── Eventos ──────────────────────────────────────────────────────────────

    def _indice(self, event) -> int | None:
        i = int(self.corpo.canvasy(event.y) // self._h)
        return i if 0 <= i < len(self._ids) else None

    def _clique(self, event):
        self.corpo.focus_set()
        i = self._indice(event)
        if i is None:
            return
        mudou = self._ids[i] != self._sel
        self._sel = self._ids[i]
        self._desenhar()
        if mudou and self._ao_selecionar:
            self._ao_selecionar(self._sel)
        if self._ao_clicar:
            self._ao_clicar(self._sel)

    def _duplo(self, event):
        i = self._indice(event)
        if i is not None and self._ao_duplo:
            self._ao_duplo(self._ids[i])

    def _mover(self, passo):
        if not self._ids:
            return
        i = self._ids.index(self._sel) + passo if self._sel in self._ids else 0
        i = max(0, min(len(self._ids) - 1, i))
        self.selecionar(self._ids[i])
        if self._ao_selecionar:
            self._ao_selecionar(self._sel)

    def _mostrar(self, i):
        topo, base = self.corpo.canvasy(0), self.corpo.canvasy(self.corpo.winfo_height())
        y = i * self._h
        total = max(1, len(self._ids) * self._h)
        if y < topo:
            self.corpo.yview_moveto(y / total)
        elif y + self._h > base:
            self.corpo.yview_moveto((y + self._h - (base - topo)) / total)

    def _xview(self, *args):
        self.corpo.xview(*args)
        self.cab.xview(*args)

    # ── Desenho ──────────────────────────────────────────────────────────────

    def _larguras(self, total: int) -> list[int]:
        s = self._get_widget_scaling()
        if self._fixa:
            return [round(c["peso"] * s) for c in self._cols]
        mins = [round(c.get("min", 0) * s) for c in self._cols]
        visiveis = list(range(len(self._cols)))
        flexivel = round(MIN_FLEXIVEL * s)  # espaço mínimo para as colunas sem "min" (ex.: nome do produto)
        # sem espaço: as colunas opcionais saem, da última para a primeira
        for i in reversed(range(len(self._cols))):
            if sum(mins[j] for j in visiveis) + flexivel <= total:
                break
            if self._cols[i].get("opcional"):
                visiveis.remove(i)
        larg = [0] * len(self._cols)
        fixos: set[int] = set()
        while True:  # proporcional ao peso, respeitando os mínimos
            resto = total - sum(mins[i] for i in fixos)
            soma = sum(self._cols[i]["peso"] for i in visiveis if i not in fixos) or 1
            for i in visiveis:
                larg[i] = mins[i] if i in fixos else int(resto * self._cols[i]["peso"] / soma)
            novos = {i for i in visiveis if i not in fixos and larg[i] < mins[i]}
            if not novos:
                return larg
            fixos |= novos

    def _cortar(self, texto: str, largura: int, fonte) -> str:
        chave = (texto, largura, str(fonte))
        if chave in self._corte:
            return self._corte[chave]
        if fonte.measure(texto) <= largura:
            res = texto
        else:
            lo, hi = 0, len(texto)
            while lo < hi:
                meio = (lo + hi + 1) // 2
                if fonte.measure(texto[:meio] + "…") <= largura:
                    lo = meio
                else:
                    hi = meio - 1
            res = texto[:lo].rstrip() + "…" if lo else ""
        if len(self._corte) > 20000:
            self._corte.clear()
        self._corte[chave] = res
        return res

    def _desenhar(self):
        if not self.winfo_exists():
            return
        fundo, linha, tinta, tinta2 = cor(self._fundo), cor(LINHA), cor(TINTA), cor(TINTA_2)
        cores = {"queda": cor(QUEDA), "erro": cor(ERRO), "secundario": tinta2}
        c, cab = self.corpo, self.cab
        c.configure(bg=fundo)
        cab.configure(bg=fundo)
        c.delete("all")
        cab.delete("all")
        larguras = self._larguras(max(c.winfo_width(), 1))
        total_w = sum(larguras)
        xs, x = [], 0
        for w in larguras:
            xs.append(x)
            x += w

        for col, x0, w in zip(self._cols, xs, larguras):
            if not w:
                continue
            direita = col.get("alinhar") == "e"
            cab.create_text(x0 + w - self._pad if direita else x0 + self._pad, self._hc / 2,
                            text=self._cortar(col["titulo"], w - 2 * self._pad, self._f_cab),
                            anchor="e" if direita else "w", fill=tinta2, font=self._f_cab)
        cab.create_line(0, self._hc - 1, max(total_w, cab.winfo_width()), self._hc - 1, fill=linha)

        sel_bg = cor(SELECAO)
        for i, (iid, valores) in enumerate(zip(self._ids, self._linhas)):
            y0 = i * self._h
            if iid == self._sel:
                c.create_rectangle(0, y0, max(total_w, c.winfo_width()), y0 + self._h, fill=sel_bg, outline="")
            for col, x0, w, valor in zip(self._cols, xs, larguras, valores):
                if w:
                    self._celula(c, col, x0, w, y0, valor, tinta, cores)
            c.create_line(0, y0 + self._h - 1, max(total_w, c.winfo_width()), y0 + self._h - 1, fill=linha)
        c.configure(scrollregion=(0, 0, total_w if self._fixa else c.winfo_width(), len(self._ids) * self._h))
        if self._fixa:
            cab.configure(scrollregion=(0, 0, total_w, self._hc))

    def _celula(self, c, col, x0, w, y0, valor, tinta, cores):
        meio = y0 + self._h / 2
        util = w - 2 * self._pad
        if col.get("tipo") == "status" and isinstance(valor, tuple):
            estado, texto = valor
            r = self._raio
            cx = x0 + self._pad + r
            c.create_oval(cx - r, meio - r, cx + r, meio + r, outline="", fill=cor(ESTADOS.get(estado, TINTA_2)))
            c.create_text(cx + r + self._pad, meio, text=self._cortar(str(texto), util - 2 * r - self._pad, self._f_corpo),
                          anchor="w", fill=tinta, font=self._f_corpo)
            return
        preenchimento = cores.get(col.get("tipo"), tinta)
        if isinstance(valor, tuple):
            valor, sobrepor = valor
            preenchimento = cores.get(sobrepor, preenchimento)
        texto = self._cortar("" if valor is None else str(valor), util, self._f_corpo)
        direita = col.get("alinhar") == "e"
        c.create_text(x0 + w - self._pad if direita else x0 + self._pad, meio, text=texto,
                      anchor="e" if direita else "w", fill=preenchimento, font=self._f_corpo)
