"""
Painel de detalhe da oferta (direita, 360 px): o preço atual é o único destaque grande do app.
Gráfico de 90 dias em tk.Canvas: linha TINTA, menor preço anterior tracejado, ponto final em QUEDA se caiu.
"""
import tkinter as tk
import webbrowser
from datetime import date, datetime, timedelta

import customtkinter as ctk

import database as db
from oferta import brl, queda
from ui import estilo as e
from ui.fundo import em_segundo_plano


def _origem(texto: str | None) -> str:
    if not texto:
        return "—"
    if texto.startswith("fonte:"):
        import fontes
        f = fontes.get(texto[6:])
        return f"Busca no {f.nome}" if f else "Busca automática"
    return texto


def _quando(texto: str | None) -> str:
    if not texto:
        return "—"
    try:
        dt = datetime.strptime(texto[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return texto
    dia = "hoje" if dt.date() == date.today() else ("ontem" if dt.date() == date.today() - timedelta(days=1)
                                                    else dt.strftime("%d/%m"))
    return f"{dia}, {dt:%H:%M}"


class GraficoPreco(tk.Canvas):
    LARGURA, ALTURA = 296, 96

    def __init__(self, parent):
        s = ctk.ScalingTracker.get_widget_scaling(parent)
        self._s = s
        super().__init__(parent, width=round(self.LARGURA * s), height=round(self.ALTURA * s),
                         highlightthickness=0, bd=0)
        self._dados: list[tuple[str, float]] = []
        self._caiu = False
        ctk.AppearanceModeTracker.add(lambda _m: self.after(0, self.desenhar), self)

    def carregar(self, dados, caiu: bool):
        self._dados, self._caiu = dados, caiu
        self.desenhar()

    def desenhar(self):
        if not self.winfo_exists():
            return
        s = self._s
        w, h = round(self.LARGURA * s), round(self.ALTURA * s)
        self.configure(bg=e.cor(e.SUPERFICIE))
        self.delete("all")
        fonte = e.fonte_tk(e.F_LEGENDA, s)
        if len(self._dados) < 2:
            self.create_text(0, h / 2, anchor="w", text="O histórico começa a partir de hoje.",
                             fill=e.cor(e.TINTA_2), font=fonte)
            return
        hoje = date.today()
        inicio = hoje - timedelta(days=90)
        precos = [p for _, p in self._dados]
        anteriores = precos[:-1]
        lo, hi = min(precos), max(precos)
        if hi == lo:
            lo, hi = lo * 0.95, hi * 1.05
        topo, base = 8 * s, h - 8 * s

        def xy(dia, preco):
            d = (date.fromisoformat(dia) - inicio).days
            return w * d / 90, base - (preco - lo) / (hi - lo) * (base - topo)

        pontos = [xy(d, p) for d, p in self._dados]
        if anteriores:
            _, y_min = xy(self._dados[0][0], min(anteriores))
            self.create_line(0, y_min, w, y_min, fill=e.cor(e.TINTA_2), dash=(4, 3))
        self.create_line(*[c for pt in pontos for c in pt], fill=e.cor(e.TINTA), width=1.5 * s)
        x, y = pontos[-1]
        r = 3 * s
        self.create_oval(x - r, y - r, x + r, y + r, outline="", fill=e.cor(e.QUEDA if self._caiu else e.TINTA))


class PainelDetalhe(ctk.CTkFrame):
    def __init__(self, parent, ao_fechar, ao_mudar):
        super().__init__(parent, width=e.LARGURA_DETALHE, fg_color=e.SUPERFICIE, corner_radius=0)
        self.pack_propagate(False)
        self._ao_fechar, self._ao_mudar = ao_fechar, ao_mudar
        self._p: dict | None = None
        self._chave: str | None = None

        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.pack(fill="x", padx=e.E3, pady=(e.E1, 0))
        e.botao_texto(topo, "Fechar", ao_fechar).pack(side="right")

        corpo = e.area_rolavel(self, fundo=e.SUPERFICIE)
        corpo.pack(fill="both", expand=True, padx=(e.E3, e.E1))
        self._nome = e.rotulo(corpo, "", e.F_SECAO, wraplength=290)
        self._nome.pack(anchor="w", pady=(0, e.E2))
        self._preco = e.rotulo(corpo, "", e.F_PRECO)
        self._preco.pack(anchor="w")
        linha = ctk.CTkFrame(corpo, fg_color="transparent")
        linha.pack(anchor="w", pady=(0, e.E3))
        self._antes = e.rotulo(linha, "", e.F_CORPO, secundario=True)
        self._antes.pack(side="left")
        self._pct = e.rotulo(linha, "", e.F_CORPO_FORTE)
        self._pct.configure(text_color=e.QUEDA)
        self._pct.pack(side="left", padx=(e.E1, 0))

        e.rotulo(corpo, "Últimos 90 dias", e.F_LEGENDA, secundario=True).pack(anchor="w", pady=(0, e.E1))
        self._grafico = GraficoPreco(corpo)
        self._grafico.pack(anchor="w")
        self._legenda = e.rotulo(corpo, "", e.F_LEGENDA, secundario=True)
        self._legenda.pack(anchor="w", pady=(e.E1, e.E2))

        self._info = {}
        grade = ctk.CTkFrame(corpo, fg_color="transparent")
        grade.pack(anchor="w", fill="x")
        for i, (chave, titulo) in enumerate((("loja", "Loja"), ("origem", "Origem"), ("visto", "Visto por último"))):
            e.rotulo(grade, titulo, e.F_LEGENDA, secundario=True).grid(row=i, column=0, sticky="nw", pady=(0, e.E1))
            self._info[chave] = e.rotulo(grade, "", e.F_CORPO, wraplength=180)
            self._info[chave].grid(row=i, column=1, sticky="nw", padx=(e.E2, 0), pady=(0, e.E1))

        acoes = ctk.CTkFrame(corpo, fg_color="transparent")
        acoes.pack(anchor="w", fill="x", pady=(e.E1, 0))
        self._publicar = e.botao_primario(acoes, "Publicar", self._publicar_oferta, largura=112)
        self._publicar.pack(side="left")
        e.botao(acoes, "Descartar", self._descartar, largura=104).pack(side="left", padx=(e.E1, 0))
        e.botao_texto(corpo, "Abrir na loja", self._abrir).pack(anchor="w", pady=(e.E1, 0))
        self._erro = e.rotulo(corpo, "", e.F_LEGENDA, wraplength=290)
        self._erro.configure(text_color=e.ERRO)
        self._erro.pack(anchor="w", pady=(e.E1, e.E3))

    # ── Dados ────────────────────────────────────────────────────────────────

    def mostrar(self, chave: str):
        self._chave = chave
        self._erro.configure(text="")
        self._publicar.configure(text="Publicar", state="normal")

        def _ler():
            itens = db.menores_precos_do_dia(chave=chave, limit=1)
            return (itens[0] if itens else None), db.historico_precos(chave, 90)
        em_segundo_plano(self, _ler, lambda res, err: self._render(chave, err or res))

    def _render(self, chave, res):
        if chave != self._chave or not self.winfo_exists():
            return
        if isinstance(res, Exception) or res[0] is None:
            self._p = None
            self._nome.configure(text="Produto sem preço registrado hoje.")
            self._preco.configure(text="")
            return
        p, hist = res
        self._p = p
        antes, pct = queda(p)
        self._nome.configure(text=p["nome"])
        self._preco.configure(text=brl(p["preco_hoje"]))
        self._antes.configure(text=f"Antes {brl(antes)}" if antes else "Sem queda comprovada")
        self._pct.configure(text=f"-{pct}%" if pct else "")
        self._grafico.carregar(hist, caiu=bool(pct))
        anteriores = [v for d, v in hist if d < date.today().isoformat()]
        self._legenda.configure(text=f"Tracejado: menor preço anterior, {brl(min(anteriores))}" if anteriores else "")
        self._info["loja"].configure(text=p["loja"])
        self._info["origem"].configure(text=_origem(p.get("origem")))
        self._info["visto"].configure(text=_quando(p.get("visto_por_ultimo")))

    # ── Ações ────────────────────────────────────────────────────────────────

    def _publicar_oferta(self):
        if not self._p:
            return
        destino = (db.get_config("radar_destino") or "").strip()
        if not destino:
            self._erro.configure(text="Defina onde publicar em Ofertas → Publicação automática → Publicar em.")
            return
        chave = self._p["chave"]
        self._publicar.configure(text="Publicando", state="disabled")
        self._erro.configure(text="")

        def _trabalho():
            from oferta import publicar_oferta
            from telegram_manager import telegram_manager
            publicar_oferta(chave, next(iter(telegram_manager.clients), None), destino)

        def _fim(_, err):
            if chave != self._chave:
                return
            if err:
                self._publicar.configure(text="Publicar", state="normal")
                self._erro.configure(text=f"Não publicado: {err}")
            else:
                self._publicar.configure(text="Publicado", state="disabled")
                self._ao_mudar()
        em_segundo_plano(self, _trabalho, _fim)

    def _descartar(self):
        if not self._p:
            return
        db.descartar(self._p["chave"])
        self._ao_fechar()
        self._ao_mudar()

    def _abrir(self):
        if self._p and self._p.get("url"):
            webbrowser.open(self._p["url"])
