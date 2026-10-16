import customtkinter as ctk
from tkinter import messagebox

import database as db
from telegram_manager import telegram_manager
from ui import estilo as e


class ContasFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, corner_radius=0, fg_color=e.FUNDO)
        acoes = e.cabecalho(self, "Contas")
        e.acao(acoes, e.botao_texto(acoes, "Remover", self._remove_conta, perigo=True))
        e.acao(acoes, e.botao(acoes, "Desconectar", self._disconnect))
        e.acao(acoes, e.botao(acoes, "Conectar", self._connect))
        e.acao(acoes, e.botao_primario(acoes, "Adicionar conta", self._add_conta))

        e.paragrafo(self, "Com o bot configurado, a conta só lê os canais onde o bot não pode entrar; quem publica "
                          "é o bot.", padx=e.MARGEM, pady=(0, e.E2))
        lista = ctk.CTkFrame(self, fg_color="transparent")
        lista.pack(fill="both", expand=True, padx=e.MARGEM, pady=(0, e.E3))
        self._tabela = e.Tabela(lista, [("telefone", "Telefone", 4), ("apelido", "Apelido", 4),
                                        ("status", "Status", 3, {"tipo": "status", "min": 128})])
        self._vazio = e.estado_vazio(lista, "Nenhuma conta ainda. Adicione uma conta do Telegram para ler canais "
                                            "onde o bot não pode entrar.", "Adicionar conta", self._add_conta)

    # ── Refresh ──────────────────────────────────────────────────────────────

    def refresh(self):
        contas = db.listar_contas()
        if not contas:
            self._tabela.pack_forget()
            self._vazio.pack(anchor="w")
            return
        self._vazio.pack_forget()
        self._tabela.pack(fill="both", expand=True)
        self._tabela.carregar([(c["telefone"], c["apelido"] or "—",
                                ("ok", "Conectada") if c["status"] == "conectada" else
                                ("inativo", (c["status"] or "desconectada").capitalize())) for c in contas],
                              ids=[c["id"] for c in contas])

    def _selecionada(self) -> dict | None:
        cid = self._tabela.selecionado()
        if not cid:
            messagebox.showinfo("Contas", "Selecione uma conta na lista.", parent=self)
            return None
        return next((c for c in db.listar_contas() if c["id"] == int(cid)), None)

    # ── Ações ────────────────────────────────────────────────────────────────

    def _add_conta(self):
        AdicionarContaDialog(self)

    def _remove_conta(self):
        conta = self._selecionada()
        if conta and messagebox.askyesno("Remover conta", f"Remover a conta {conta['telefone']}? Os repasses que "
                                                          "dependem dela param de ler as origens.", parent=self):
            telegram_manager.desconectar_conta(conta["id"])
            db.remover_conta(conta["id"])
            self.refresh()

    def _connect(self):
        conta = self._selecionada()
        if not conta:
            return
        try:
            telegram_manager.get_creds()
        except ValueError as ex:
            messagebox.showerror("Conectar conta", str(ex), parent=self)
            return

        def cb(result, error):
            if error:
                self.after(0, lambda: messagebox.showerror("Conectar conta", f"Não conectou: {error}", parent=self))
                return
            if result == "needs_code":
                self.after(0, lambda: CodigoDialog(self, conta))
            else:
                self.after(0, self.refresh)

        telegram_manager.conectar_conta(conta["id"], conta["telefone"], cb)

    def _disconnect(self):
        conta = self._selecionada()
        if conta:
            telegram_manager.desconectar_conta(conta["id"], callback=lambda _: self.after(0, self.refresh))


# ── Diálogos ──────────────────────────────────────────────────────────────────

class AdicionarContaDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self._parent = parent
        e.janela(self, "Adicionar conta", 420, 340, parent)
        self.resizable(False, False)
        e.rodape_dialogo(self, "Salvar", self._save)
        corpo = ctk.CTkFrame(self, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=e.E3, pady=(e.E3, 0))
        e.rotulo(corpo, "Adicionar conta do Telegram", e.F_SECAO).pack(anchor="w", pady=(0, e.E2))
        self._phone = e.campo(corpo, "Telefone com DDI e DDD", largura=360, dica="+5571999999999")
        self._apelido = e.campo(corpo, "Apelido", largura=360, dica="Ex.: Conta principal")

    def _save(self):
        phone = self._phone.get().strip()
        if not phone:
            messagebox.showwarning("Adicionar conta", "Informe o telefone, com DDI e DDD.", parent=self)
            return
        db.adicionar_conta(phone, self._apelido.get().strip() or phone, "telegram")
        self.destroy()
        self._parent.refresh()


class CodigoDialog(ctk.CTkToplevel):
    def __init__(self, parent, conta: dict):
        super().__init__(parent)
        self._parent = parent
        self._conta = conta
        e.janela(self, "Código de verificação", 420, 360, parent)
        self.resizable(False, False)
        e.rodape_dialogo(self, "Confirmar", self._confirm)
        corpo = ctk.CTkFrame(self, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=e.E3, pady=(e.E3, 0))
        e.rotulo(corpo, "Código de verificação", e.F_SECAO).pack(anchor="w", pady=(0, e.E1))
        e.rotulo(corpo, f"O Telegram enviou um código para {conta['telefone']}.", e.F_CORPO,
                 secundario=True).pack(anchor="w", pady=(0, e.E2))
        self._code = e.campo(corpo, "Código", largura=360, dica="12345")
        self._pw = e.campo(corpo, "Senha de duas etapas (se tiver)", largura=360, oculto=True)

    def _confirm(self):
        code = self._code.get().strip()
        pw = self._pw.get().strip() or None
        if not code:
            messagebox.showwarning("Código de verificação", "Informe o código que o Telegram enviou.", parent=self)
            return

        def cb(result, error):
            if error:
                self.after(0, lambda: messagebox.showerror("Código de verificação", f"Não conectou: {error}",
                                                           parent=self))
            else:
                self.after(0, self.destroy)
                self.after(0, self._parent.refresh)

        telegram_manager.confirmar_codigo(self._conta["id"], code, cb, pw)
