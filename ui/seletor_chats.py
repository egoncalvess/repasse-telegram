"""
Seletor de canais/grupos da conta: busca, marcação múltipla e atalho para marcar canais de promoção.
Substitui o "Carregar grupos" + escolher um por um.
"""
import re
import customtkinter as ctk
from tkinter import messagebox

from ui.estilo import Tabela, botao, F_SUBTITULO, F_PEQUENA, TEXTO_SEC, FUNDO

PROMO_RE = re.compile(r"promo|oferta|desconto|achad|cupom|black|pechincha|barato|liquida|bug|precinho|off\b", re.I)


class SeletorChats(ctk.CTkToplevel):
    """
    Abre a lista de canais/grupos da conta. ao_confirmar recebe [{'id', 'nome'}].
    selecionados: ids já marcados (modo edição).
    """

    def __init__(self, parent, conta_id: int, titulo: str, ao_confirmar, selecionados=(), atalho_promo=True):
        super().__init__(parent)
        self.title(titulo)
        self.geometry("720x560")
        self.minsize(560, 420)
        self.configure(fg_color=FUNDO)
        self.transient(parent)
        self.grab_set()
        self._ao_confirmar = ao_confirmar
        # IDs antigos foram salvos sem prefixo: aceita as formas marcadas também (-100… canal, -… grupo)
        self._marcados = set()
        for s in map(str, selecionados):
            self._marcados |= {s, f"-100{s}", f"-{s}"} if s.isdigit() else {s}
        self._chats: list[dict] = []

        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(topo, text=titulo, font=F_SUBTITULO).pack(side="left")
        self._contador = ctk.CTkLabel(topo, text="", font=F_PEQUENA, text_color=TEXTO_SEC)
        self._contador.pack(side="right")

        barra = ctk.CTkFrame(self, fg_color="transparent")
        barra.pack(fill="x", padx=16, pady=(0, 8))
        self._busca = ctk.CTkEntry(barra, placeholder_text="🔎 Buscar por nome...", height=34)
        self._busca.pack(side="left", fill="x", expand=True)
        self._busca.bind("<KeyRelease>", lambda _: self._render())
        if atalho_promo:
            botao(barra, "Marcar canais de promoção", self._marcar_promo, "cinza", 200).pack(side="left", padx=(8, 0))
        botao(barra, "Limpar", self._limpar, "cinza", 80).pack(side="left", padx=(8, 0))

        self._tabela = Tabela(self, [("marca", "✓", 1), ("nome", "Nome", 10), ("tipo", "Tipo", 2)], altura=14)
        self._tabela.pack(fill="both", expand=True, padx=16)
        self._tabela.tree.bind("<ButtonRelease-1>", self._alternar)
        self._tabela.tree.bind("<space>", self._alternar)

        ctk.CTkLabel(self, text="Clique na linha para marcar/desmarcar.", font=F_PEQUENA,
                     text_color=TEXTO_SEC).pack(anchor="w", padx=16, pady=(4, 0))
        rodape = ctk.CTkFrame(self, fg_color="transparent")
        rodape.pack(fill="x", padx=16, pady=12)
        botao(rodape, "Confirmar", self._confirmar, "azul", 130).pack(side="right")
        botao(rodape, "Cancelar", self.destroy, "cinza", 100).pack(side="right", padx=8)

        self._contador.configure(text="Carregando canais e grupos...")
        from telegram_manager import telegram_manager
        telegram_manager.listar_chats(conta_id, lambda chats, err: self.after(0, self._carregado, chats, err))

    def _carregado(self, chats, err):
        if err:
            messagebox.showerror("Erro", err, parent=self)
            self.destroy()
            return
        self._chats = sorted(chats, key=lambda c: (c["id"] not in self._marcados, c["nome"].lower()))
        self._render()

    def _visiveis(self):
        termo = self._busca.get().strip().lower()
        return [c for c in self._chats if termo in c["nome"].lower()]

    def _render(self):
        vis = self._visiveis()
        self._tabela.carregar([("✓" if c["id"] in self._marcados else "", c["nome"], c["tipo"]) for c in vis],
                              ids=[c["id"] for c in vis])
        self._contador.configure(text=f"{len(self._marcados)} marcados · {len(self._chats)} disponíveis")

    def _alternar(self, _=None):
        cid = self._tabela.selecionado()
        if not cid:
            return
        self._marcados.symmetric_difference_update({cid})
        self._render()
        if self._tabela.tree.exists(cid):
            self._tabela.tree.selection_set(cid)
            self._tabela.tree.see(cid)

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
