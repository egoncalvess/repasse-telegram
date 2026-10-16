import customtkinter as ctk
from tkinter import messagebox

import database as db
from ui import estilo as e

TIPOS = {
    "Amazon":        "amazon",
    "Mercado Livre": "mercadolivre",
    "Shopee":        "shopee",
    "AliExpress":    "aliexpress",
    "Magalu":        "magalu",
    "Outro":         "outro",
}

AJUDA_TAG = ("Mercado Livre: no Portal do Afiliado, gere um link de qualquer produto em Gerador de link, escolha "
             "Link completo e cole aqui (o app extrai matt_word e matt_tool).\n"
             "Amazon: sua tag (ex.: seunome-20). Magalu: nome da sua loja Magazine Você.")


def _validar_tag(tipo: str, tag: str, parent) -> str:
    """Normaliza a tag e avisa se ela não permite converter links."""
    from affiliate_helper import normalizar_tag
    tag, aviso = normalizar_tag(tipo, tag)
    if aviso:
        messagebox.showwarning("Afiliado", aviso, parent=parent)
    return tag


def _situacao(intg: dict) -> tuple[str, str]:
    if intg["tipo"] == "mercadolivre":
        from affiliate_helper import parametros_ml
        return ("ok", "Link completo ok") if len(parametros_ml(intg["tag"] or "")) == 2 else \
            ("falha", "Falta o link completo do portal")
    return ("ok", intg["tag"]) if intg["tag"] else ("falha", "Sem tag")


class IntegracoesFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, corner_radius=0, fg_color=e.FUNDO)
        acoes = e.cabecalho(self, "Afiliados")
        e.acao(acoes, e.botao_texto(acoes, "Remover", self._remove, perigo=True))
        e.acao(acoes, e.botao(acoes, "Testar link", self._testar))
        e.acao(acoes, e.botao(acoes, "Editar", self._edit))
        e.acao(acoes, e.botao_primario(acoes, "Adicionar", self._add))

        e.paragrafo(self, "Links de loja nos repasses e nas ofertas são reconstruídos com a sua afiliação; tags de "
                          "outros afiliados são descartadas. Use Testar link para conferir antes de publicar.",
                    padx=e.MARGEM, pady=(0, e.E2))
        lista = ctk.CTkFrame(self, fg_color="transparent")
        lista.pack(fill="both", expand=True, padx=e.MARGEM, pady=(0, e.E3))
        self._tabela = e.Tabela(lista, [("nome", "Nome", 4), ("loja", "Loja", 3),
                                        ("tag", "Afiliação", 6, {"tipo": "status"})])
        self._tabela.ao_duplo_clique(lambda _: self._edit())
        self._vazio = e.estado_vazio(lista, "Nenhuma afiliação ainda. Sem ela, os links não viram seus e o app não "
                                            "publica ofertas.", "Adicionar afiliação", self._add)

    def refresh(self):
        itens = db.listar_integracoes()
        if not itens:
            self._tabela.pack_forget()
            self._vazio.pack(anchor="w")
            return
        self._vazio.pack_forget()
        self._tabela.pack(fill="both", expand=True)
        nomes = {v: k for k, v in TIPOS.items()}
        self._tabela.carregar([(i["nome"], nomes.get(i["tipo"], i["tipo"]), _situacao(i)) for i in itens],
                              ids=[i["id"] for i in itens])

    def _selecionada(self) -> int | None:
        iid = self._tabela.selecionado()
        if not iid:
            messagebox.showinfo("Afiliados", "Selecione uma afiliação na lista.", parent=self)
        return int(iid) if iid else None

    def _add(self):
        IntegracaoDialog(self, None)

    def _edit(self):
        iid = self._selecionada()
        if not iid:
            return
        intg = db.get_integracao(iid)
        if not intg:
            messagebox.showerror("Afiliados", "Essa afiliação não existe mais. A lista foi atualizada.", parent=self)
            self.refresh()
            return
        IntegracaoDialog(self, intg)

    def _remove(self):
        iid = self._selecionada()
        if iid and messagebox.askyesno("Remover afiliação", "Remover esta afiliação? Links dessa loja deixam de "
                                                            "virar seus.", parent=self):
            db.remover_integracao(iid)
            self.refresh()

    def _testar(self):
        url = ctk.CTkInputDialog(text="Cole um link de oferta (qualquer loja, pode ser encurtado):",
                                 title="Testar link", font=e.F_CORPO, fg_color=e.SUPERFICIE,
                                 button_fg_color=e.AZUL, button_hover_color=e.AZUL_HOVER, button_text_color=e.BRANCO,
                                 entry_fg_color=e.SUPERFICIE, entry_border_color=e.LINHA, entry_text_color=e.TINTA,
                                 text_color=e.TINTA).get_input()
        if not url:
            return
        from telegram_manager import telegram_manager
        from affiliate_helper import converter_links

        def _done(fut):  # roda no loop do Telegram: a tela não trava enquanto resolve o link
            try:
                texto, nao = fut.result()
            except Exception as ex:
                texto, nao = "", [f"erro: {ex}"]

            def _ui():
                if nao:
                    messagebox.showwarning("Testar link", f"Este link não vira afiliado seu:\n{nao[0]}\n\n"
                                           "Confira se a loja tem afiliação cadastrada (Mercado Livre: link completo "
                                           "do portal).", parent=self)
                else:
                    messagebox.showinfo("Testar link", f"Original:\n{url.strip()}\n\nSeu link:\n{texto}", parent=self)
            self.after(0, _ui)

        telegram_manager._run(converter_links(url.strip())).add_done_callback(_done)


class IntegracaoDialog(ctk.CTkToplevel):
    """Adicionar (intg=None) ou editar uma afiliação."""

    def __init__(self, parent, intg: dict | None):
        super().__init__(parent)
        self._parent, self._intg = parent, intg
        titulo = "Editar afiliação" if intg else "Nova afiliação"
        e.janela(self, titulo, 460, 520, parent)
        self.resizable(False, False)
        e.rodape_dialogo(self, "Salvar", self._save)
        corpo = ctk.CTkFrame(self, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=e.E3, pady=(e.E3, 0))
        e.rotulo(corpo, titulo, e.F_SECAO).pack(anchor="w", pady=(0, e.E2))
        self._nome = e.campo(corpo, "Nome (apelido interno)", intg["nome"] if intg else "", largura=400,
                             dica="Ex.: Minha conta Mercado Livre")
        e.rotulo(corpo, "Loja", e.F_LEGENDA, secundario=True).pack(anchor="w", pady=(0, 4))
        atual = next((k for k, v in TIPOS.items() if intg and v == intg["tipo"]), list(TIPOS)[0])
        self._tipo_var = ctk.StringVar(value=atual)
        e.menu(corpo, self._tipo_var, list(TIPOS), largura=400).pack(anchor="w", pady=(0, e.E2))
        self._tag = e.campo(corpo, "Tag de afiliado (Mercado Livre: link completo do portal)",
                            intg.get("tag", "") if intg else "", largura=400)
        e.rotulo(corpo, AJUDA_TAG, e.F_LEGENDA, secundario=True, wraplength=400).pack(anchor="w")

    def _save(self):
        nome, tag = self._nome.get().strip(), self._tag.get().strip()
        tipo = TIPOS.get(self._tipo_var.get(), "outro")
        if not nome:
            messagebox.showwarning("Afiliado", "Informe um nome para a afiliação.", parent=self)
            return
        tag = _validar_tag(tipo, tag, self)
        if self._intg:
            db.atualizar_integracao(self._intg["id"], nome, tipo, tag, "")
        else:
            db.adicionar_integracao(nome, tipo, tag, "")
        self.destroy()
        self._parent.refresh()
