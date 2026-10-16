"""
Buscas: o que o app procura sozinho nas fontes (Mercado Livre e futuras), a cada quanto e com quais regras.
"""
import customtkinter as ctk
from tkinter import messagebox

import database as db
import fontes
from ui import estilo as e
from ui.fundo import em_segundo_plano

TIPOS = {"Termo": "termo", "Categoria": "categoria", "Produto": "produto"}
DICA_VALOR = {"termo": ("O que buscar", "air fryer 4 litros"),
              "categoria": ("Código da categoria", "MLB1648"),
              "produto": ("Link ou código do produto", "https://www.mercadolivre.com.br/…/p/MLB…")}


def _status(b: dict) -> tuple[str, str]:
    st = b.get("ultimo_status") or ""
    if not b["ativo"]:
        return "inativo", "Pausada"
    if not st:
        return "inativo", "Nunca executada"
    if st.startswith("ok"):
        return "ok", "Ok" + (f" · {st.split(':', 1)[1].strip()}" if ":" in st else "")
    return "falha", st.split(":", 1)[0].capitalize() if ":" in st else "Falha"


def _quando(texto: str | None) -> str:
    return f"{texto[8:10]}/{texto[5:7]} {texto[11:16]}" if texto else "—"


class BuscasFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, corner_radius=0, fg_color=e.FUNDO)
        acoes = e.cabecalho(self, "Buscas")
        e.acao(acoes, e.botao_texto(acoes, "Remover", self._remover, perigo=True))
        e.acao(acoes, e.botao(acoes, "Executar agora", self._executar))
        e.acao(acoes, e.botao(acoes, "Editar", self._editar))
        self._btn_pausar = e.acao(acoes, e.botao(acoes, "Pausar", self._pausar, largura=96))
        e.acao(acoes, e.botao_primario(acoes, "Nova busca", self.nova))

        self._aviso = e.rotulo(self, "", e.F_LEGENDA, secundario=True)
        e.ajustar_quebra(self._aviso)

        lista = ctk.CTkFrame(self, fg_color="transparent")
        lista.pack(fill="both", expand=True, padx=e.MARGEM, pady=(0, e.E3))
        self._tabela = e.Tabela(lista, [("nome", "Nome", 4), ("fonte", "Fonte", 3, {"min": 120, "opcional": True}), ("valor", "O que busca", 5),
                                        ("intervalo", "A cada", 2, {"alinhar": "e", "min": 72}),
                                        ("ultima", "Última execução", 3, {"min": 120, "opcional": True}), ("status", "Status", 4, {"tipo": "status", "min": 176})])
        self._tabela.ao_selecionar(lambda _: self._atualizar_botoes())
        self._tabela.ao_duplo_clique(lambda _: self._editar())
        self._vazio = e.estado_vazio(lista, "Nenhuma busca ainda. Crie uma para o app procurar ofertas sozinho.",
                                     "Nova busca", self.nova)
        self._lista = lista
        self._buscas: dict[str, dict] = {}

    def _mostrar_aviso(self, texto: str):
        """Linha de aviso acima da lista: só ocupa espaço quando tem o que dizer."""
        self._aviso.configure(text=texto)
        if texto:
            self._aviso.pack(fill="x", anchor="w", padx=e.MARGEM, pady=(0, e.E2), before=self._lista)
        else:
            self._aviso.pack_forget()

    def refresh(self):
        buscas = db.listar_buscas()
        self._buscas = {str(b["id"]): b for b in buscas}
        inativas = [f.nome for f in fontes.registro().values() if not fontes.ativa(f.id)]
        self._mostrar_aviso(f"{', '.join(inativas)} desligado nas buscas automáticas: ligue em "
                            "Configurações → Fontes." if inativas and buscas else "")
        if not buscas:
            self._tabela.pack_forget()
            self._vazio.pack(anchor="w")
            return
        self._vazio.pack_forget()
        self._tabela.pack(fill="both", expand=True)
        linhas = []
        for b in buscas:
            f = fontes.get(b["fonte_id"])
            tipo = next((k for k, v in TIPOS.items() if v == b["tipo"]), b["tipo"])
            linhas.append((b["nome"], f.nome if f else b["fonte_id"], f"{tipo}: {b['valor']}",
                           f"{b['intervalo_min']} min", _quando(b["ultima_execucao"]), _status(b)))
        self._tabela.carregar(linhas, ids=list(self._buscas))
        self._atualizar_botoes()

    def _selecionada(self, avisar=True) -> dict | None:
        b = self._buscas.get(self._tabela.selecionado() or "")
        if not b and avisar:
            messagebox.showinfo("Buscas", "Selecione uma busca na lista.", parent=self)
        return b

    def _atualizar_botoes(self):
        b = self._selecionada(avisar=False)
        self._btn_pausar.configure(text="Retomar" if b and not b["ativo"] else "Pausar")

    # ── Ações ────────────────────────────────────────────────────────────────

    def nova(self):
        BuscaDialog(self, None, self.refresh)

    def _editar(self):
        b = self._selecionada()
        if b:
            BuscaDialog(self, b, self.refresh)

    def _pausar(self):
        b = self._selecionada()
        if b:
            db.atualizar_busca(b["id"], {"ativo": 0 if b["ativo"] else 1})
            self.refresh()

    def _remover(self):
        b = self._selecionada()
        if b and messagebox.askyesno("Remover busca", f"Remover a busca \"{b['nome']}\"? O histórico de preços "
                                                      "dos produtos continua no app.", parent=self):
            db.remover_busca(b["id"])
            self.refresh()

    def _executar(self):
        b = self._selecionada()
        if not b:
            return
        self._mostrar_aviso(f"Executando \"{b['nome']}\"…")

        def _fim(res, err):
            self.refresh()
            self._mostrar_aviso(f"\"{b['nome']}\": {f'erro: {err}' if err else res}")
        import buscador
        em_segundo_plano(self, lambda: buscador.executar(b), _fim)


class BuscaDialog(ctk.CTkToplevel):
    def __init__(self, parent, busca: dict | None, ao_salvar):
        super().__init__(parent)
        e.janela(self, "Editar busca" if busca else "Nova busca", 460, 680, parent)
        self._busca, self._ao_salvar = busca, ao_salvar
        b = busca or {}
        e.rodape_dialogo(self, "Salvar", self._salvar)

        corpo = e.area_rolavel(self, fundo=e.SUPERFICIE)
        corpo.pack(fill="both", expand=True, padx=e.E3, pady=(e.E3, 0))
        e.rotulo(corpo, "Editar busca" if busca else "Nova busca", e.F_SECAO).pack(anchor="w", pady=(0, e.E2))

        self._nome = e.campo(corpo, "Nome", b.get("nome", ""), dica="Ex.: Air fryers")
        self._fontes = {f.nome: f for f in fontes.registro().values()}
        atual = fontes.get(b.get("fonte_id", "")) or next(iter(self._fontes.values()))
        self._fonte = ctk.StringVar(value=atual.nome)
        self._menu(corpo, "Fonte", e.menu(corpo, self._fonte, list(self._fontes), largura=320))

        self._tipo = ctk.StringVar(value=next((k for k, v in TIPOS.items() if v == b.get("tipo")), "Termo"))
        self._menu(corpo, "Tipo", e.segmentado(corpo, list(TIPOS), self._tipo, lambda _: self._dica()))
        self._rot_valor = e.rotulo(corpo, "", e.F_LEGENDA, secundario=True)
        self._rot_valor.pack(anchor="w", pady=(0, 4))
        self._valor = e.entrada(corpo, 380)
        self._valor.pack(anchor="w", pady=(0, e.E2))
        if b.get("valor"):
            self._valor.insert(0, b["valor"])

        self._intervalo = e.campo(corpo, "A cada (minutos)", b.get("intervalo_min") or atual.intervalo_min_padrao,
                                  largura=120)
        self._desconto = e.campo(corpo, "Desconto mínimo para publicar (%)", _num(b.get("desconto_min_pct")),
                                 largura=120, dica="0 = qualquer")
        self._preco_max = e.campo(corpo, "Preço máximo para publicar (R$)", _num(b.get("preco_max")),
                                  largura=120, dica="0 = sem teto")
        self._frete = e.caixa_marcar(corpo, "Só produtos com frete grátis")
        self._frete.pack(anchor="w", pady=(0, e.E2))
        if b.get("so_frete_gratis"):
            self._frete.select()
        self._ativa = e.caixa_marcar(corpo, "Ativa")
        self._ativa.pack(anchor="w", pady=(0, e.E2))
        if b.get("ativo", 1):
            self._ativa.select()
        self._dica()

    @staticmethod
    def _menu(parent, titulo, widget):
        e.rotulo(parent, titulo, e.F_LEGENDA, secundario=True).pack(anchor="w", pady=(0, 4))
        widget.pack(anchor="w", pady=(0, e.E2))

    def _dica(self):
        titulo, exemplo = DICA_VALOR[TIPOS[self._tipo.get()]]
        self._rot_valor.configure(text=titulo)
        self._valor.configure(placeholder_text=exemplo)

    def _salvar(self):
        nome, valor = self._nome.get().strip(), self._valor.get().strip()
        if not nome or not valor:
            messagebox.showwarning("Busca", "Preencha o nome e o que buscar.", parent=self)
            return
        try:
            intervalo = int(self._intervalo.get().strip() or 0)
            desconto = float((self._desconto.get().strip() or "0").replace(",", "."))
            preco_max = float((self._preco_max.get().strip() or "0").replace(",", "."))
        except ValueError:
            messagebox.showwarning("Busca", "Intervalo, desconto e preço máximo precisam ser números.", parent=self)
            return
        fonte = self._fontes[self._fonte.get()]
        if intervalo < 5:
            messagebox.showwarning("Busca", "O intervalo mínimo é de 5 minutos.", parent=self)
            return
        dados = {"fonte_id": fonte.id, "nome": nome, "tipo": TIPOS[self._tipo.get()], "valor": valor,
                 "intervalo_min": intervalo, "desconto_min_pct": max(0.0, desconto), "preco_max": max(0.0, preco_max),
                 "so_frete_gratis": int(self._frete.get()), "ativo": int(self._ativa.get())}
        if self._busca:
            db.atualizar_busca(self._busca["id"], dados)
        else:
            db.adicionar_busca(dados)
        self.destroy()
        self._ao_salvar()


def _num(v) -> str:
    if not v:
        return ""
    return str(int(v)) if float(v).is_integer() else str(v)
