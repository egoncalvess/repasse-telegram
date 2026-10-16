"""
Seletor de canais/grupos da conta: busca, marcação múltipla e atalho para marcar canais de promoção.
Substitui o "Carregar grupos" + escolher um por um.
"""
import re
import customtkinter as ctk
from tkinter import messagebox

from ui import estilo as e

PROMO_RE = re.compile(r"promo|oferta|desconto|achad|cupom|black|pechincha|barato|liquida|bug|precinho|off\b", re.I)


class SeletorChats(ctk.CTkToplevel):
    """
    Abre a lista de canais/grupos da conta. ao_confirmar recebe [{'id', 'nome'}].
    selecionados: ids já marcados (modo edição).
    """

    def __init__(self, parent, conta_id: int, titulo: str, ao_confirmar, selecionados=(), atalho_promo=True):
        super().__init__(parent)
        e.janela(self, titulo, 720, 580, parent)
        self.minsize(560, 420)
        self._ao_confirmar = ao_confirmar
        # IDs antigos foram salvos sem prefixo: aceita as formas marcadas também (-100… canal, -… grupo)
        self._marcados = set()
        for s in map(str, selecionados):
            self._marcados |= {s, f"-100{s}", f"-{s}"} if s.isdigit() else {s}
        self._chats: list[dict] = []

        e.rodape_dialogo(self, "Confirmar", self._confirmar)

        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.pack(fill="x", padx=e.E3, pady=(e.E3, e.E2))
        e.rotulo(topo, titulo, e.F_SECAO).pack(side="left")
        self._contador = e.rotulo(topo, "", e.F_LEGENDA, secundario=True)
        self._contador.pack(side="right")

        barra = ctk.CTkFrame(self, fg_color="transparent")
        barra.pack(fill="x", padx=e.E3, pady=(0, e.E2))
        self._busca = e.entrada(barra, 300, placeholder_text="Buscar por nome")
        self._busca.pack(side="left", fill="x", expand=True)
        self._busca.bind("<KeyRelease>", lambda _: self._render())
        if atalho_promo:
            e.botao(barra, "Marcar canais de promoção", self._marcar_promo).pack(side="left", padx=(e.E1, 0))
        e.botao_texto(barra, "Limpar", self._limpar).pack(side="left", padx=(e.E1, 0))

        e.rotulo(self, "Clique na linha para marcar ou desmarcar.", e.F_LEGENDA, secundario=True).pack(
            side="bottom", anchor="w", padx=e.E3)
        self._tabela = e.Tabela(self, [("marca", "Marcado", 2), ("nome", "Nome", 10), ("tipo", "Tipo", 2)],
                                fundo=e.SUPERFICIE)
        self._tabela.pack(fill="both", expand=True, padx=e.E3)
        self._tabela.ao_clicar(self._alternar)
        self._tabela.corpo.bind("<space>", lambda _: self._alternar(self._tabela.selecionado()))

        self._contador.configure(text="Carregando canais e grupos…")
        from telegram_manager import telegram_manager
        telegram_manager.listar_chats(conta_id, lambda chats, err: self.after(0, self._carregado, chats, err))

    def _carregado(self, chats, err):
        if err:
            messagebox.showerror(self.title(), f"Não foi possível listar os chats da conta: {err}", parent=self)
            self.destroy()
            return
        self._chats = sorted(chats, key=lambda c: (c["id"] not in self._marcados, c["nome"].lower()))
        self._render()

    def _visiveis(self):
        termo = self._busca.get().strip().lower()
        return [c for c in self._chats if termo in c["nome"].lower()]

    def _render(self):
        vis = self._visiveis()
        self._tabela.carregar([("Sim" if c["id"] in self._marcados else ("—", "secundario"), c["nome"],
                                c["tipo"]) for c in vis], ids=[c["id"] for c in vis])
        self._contador.configure(text=f"{len(self._marcados)} marcados · {len(self._chats)} disponíveis")

    def _alternar(self, cid):
        if not cid:
            return
        self._marcados.symmetric_difference_update({cid})
        self._render()
        self._tabela.selecionar(cid)

    def _marcar_promo(self):
        self._marcados |= {c["id"] for c in self._visiveis() if PROMO_RE.search(c["nome"])}
        self._render()

    def _limpar(self):
        self._marcados.clear()
        self._render()

    def _confirmar(self):
        escolhidos = [{"id": c["id"], "nome": c["nome"]} for c in self._chats if c["id"] in self._marcados]
        self.destroy()
        self._ao_confirmar(escolhidos)
