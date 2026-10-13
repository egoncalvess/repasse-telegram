import customtkinter as ctk
from tkinter import messagebox
import database as db
from telegram_manager import telegram_manager

BTN_GREEN  = ("#27ae60", "#1e8449")
BTN_RED    = ("#e74c3c", "#c0392b")
BTN_BLUE   = ("#1a6fd4", "#1558ab")
ROW_SEL    = ("#dbeafe", "#1e3a5f")
HDR_BG     = ("#e2e8f2", "#1e293b")


class ContasFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, corner_radius=0, fg_color=("#f4f6fb", "#0f1115"))
        self._selected: int | None = None
        self._rows: dict = {}
        self._build()

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=("#ffffff", "#181b22"), corner_radius=12)
        hdr.pack(fill="x", padx=16, pady=(16, 8))

        ctk.CTkLabel(hdr, text="Gerenciar Contas",
                     font=("Segoe UI", 18, "bold")).pack(side="left", padx=16, pady=14)

        btn_bar = ctk.CTkFrame(hdr, fg_color="transparent")
        btn_bar.pack(side="right", padx=12, pady=10)

        _btn(btn_bar, "+ Adicionar",  self._add_conta,    BTN_BLUE).pack(side="left", padx=4)
        _btn(btn_bar, "Remover",      self._remove_conta,  BTN_RED).pack(side="left", padx=4)
        _btn(btn_bar, "Conectar",     self._connect,       BTN_GREEN).pack(side="left", padx=4)
        _btn(btn_bar, "Desconectar",  self._disconnect,    BTN_RED).pack(side="left", padx=4)
        _btn(btn_bar, "↻ Atualizar",  self.refresh,        BTN_BLUE, width=90).pack(side="left", padx=4)

        # Table
        card = ctk.CTkFrame(self, fg_color=("#ffffff", "#181b22"), corner_radius=12)
        card.pack(fill="both", expand=True, padx=16, pady=8)

        cols = [("Cód.", 55), ("Tipo", 70), ("Telefone", 160), ("Apelido", 160), ("Status", 130)]
        hrow = ctk.CTkFrame(card, fg_color=HDR_BG, corner_radius=8)
        hrow.pack(fill="x", padx=8, pady=(8, 0))
        for col, w in cols:
            ctk.CTkLabel(hrow, text=col, font=("Segoe UI", 12, "bold"),
                         width=w, anchor="w").pack(side="left", padx=8, pady=8)

        self._list = ctk.CTkScrollableFrame(card, fg_color="transparent")
        self._list.pack(fill="both", expand=True, padx=8, pady=6)

        self.refresh()

    # ── Refresh ──────────────────────────────────────────────────────────────

    def refresh(self):
        for w in self._list.winfo_children():
            w.destroy()
        self._rows.clear()
        for conta in db.listar_contas():
            self._add_row(conta)

    def _add_row(self, conta: dict):
        row = ctk.CTkFrame(self._list, fg_color="transparent",
                           cursor="hand2", corner_radius=6)
        row.pack(fill="x", pady=1)

        connected = conta["status"] == "conectada"
        sc = ("#27ae60", "#2ecc71") if connected else ("#e74c3c", "#f87171")
        tipo_label = "✈️ TG"
        tipo_color = ("#1a6fd4", "#3b82f6")

        ctk.CTkLabel(row, text=str(conta["id"]),    width=55,  anchor="w", font=("Segoe UI", 12)).pack(side="left", padx=8, pady=8)
        ctk.CTkLabel(row, text=tipo_label,          width=70,  anchor="w", font=("Segoe UI", 12, "bold"), text_color=tipo_color).pack(side="left")
        ctk.CTkLabel(row, text=conta["telefone"],   width=160, anchor="w", font=("Segoe UI", 12)).pack(side="left")
        ctk.CTkLabel(row, text=conta["apelido"] or "-", width=160, anchor="w", font=("Segoe UI", 12)).pack(side="left")
        ctk.CTkLabel(row, text="● " + conta["status"].capitalize(),
                     width=130, anchor="w", font=("Segoe UI", 12), text_color=sc).pack(side="left")

        for w in [row] + list(row.winfo_children()):
            w.bind("<Button-1>", lambda e, cid=conta["id"]: self._select(cid))

        self._rows[conta["id"]] = row

    def _select(self, cid: int):
        self._selected = cid
        for k, r in self._rows.items():
            r.configure(fg_color=ROW_SEL if k == cid else "transparent")

    # ── Ações ────────────────────────────────────────────────────────────────

    def _add_conta(self):
        AdicionarContaDialog(self)
        self.after(200, self.refresh)

    def _remove_conta(self):
        if not self._selected:
            messagebox.showwarning("Aviso", "Selecione uma conta.")
            return
        conta = next((c for c in db.listar_contas() if c["id"] == self._selected), None)
        if not conta:
            return
        if messagebox.askyesno("Confirmar", "Remover esta conta?"):
            telegram_manager.desconectar_conta(self._selected)
            db.remover_conta(self._selected)
            self._selected = None
            self.refresh()

    def _connect(self):
        if not self._selected:
            messagebox.showwarning("Aviso", "Selecione uma conta.")
            return
        
        conta = next((c for c in db.listar_contas() if c["id"] == self._selected), None)
        if not conta:
            return

        try:
            telegram_manager.get_creds()
        except ValueError as e:
            messagebox.showerror("Configuração necessária", str(e))
            return

        def cb(result, error):
            if error:
                self.after(0, lambda: messagebox.showerror("Erro", error))
                return
            if result == "needs_code":
                self.after(0, lambda: CodigoDialog(self, conta))
            else:
                self.after(0, self.refresh)

        telegram_manager.conectar_conta(self._selected, conta["telefone"], cb)

    def _disconnect(self):
        if not self._selected:
            messagebox.showwarning("Aviso", "Selecione uma conta.")
            return
        conta = next((c for c in db.listar_contas() if c["id"] == self._selected), None)
        if not conta:
            return
        telegram_manager.desconectar_conta(self._selected,
                                           callback=lambda _: self.after(0, self.refresh))


# ── Dialogs ───────────────────────────────────────────────────────────────────

class AdicionarContaDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Adicionar Conta Telegram")
        self.geometry("380x260")
        self.grab_set()
        self.resizable(False, False)

        ctk.CTkLabel(self, text="Adicionar Conta Telegram",
                     font=("Segoe UI", 15, "bold")).pack(pady=(20, 15))

        ctk.CTkLabel(self, text="Telefone com DDD (Ex: +5511999999999)").pack()
        self._phone = ctk.CTkEntry(self, width=300, placeholder_text="+55 11 99999-9999")
        self._phone.pack(pady=(4, 12))

        ctk.CTkLabel(self, text="Apelido").pack()
        self._apelido = ctk.CTkEntry(self, width=300, placeholder_text="Ex: Conta Principal")
        self._apelido.pack(pady=(4, 18))

        ctk.CTkButton(self, text="Salvar", command=self._save, width=140, fg_color=BTN_BLUE[0], hover_color=BTN_BLUE[1]).pack()

    def _save(self):
        phone = self._phone.get().strip()
        apelido = self._apelido.get().strip()
        if not phone:
            messagebox.showwarning("Aviso", "Informe o número de telefone.", parent=self)
            return
        db.adicionar_conta(phone, apelido or phone, "telegram")
        self.destroy()


class CodigoDialog(ctk.CTkToplevel):
    def __init__(self, parent, conta: dict):
        super().__init__(parent)
        self._parent = parent
        self._conta = conta
        self.title("Verificação")
        self.geometry("380x280")
        self.grab_set()
        self.resizable(False, False)

        ctk.CTkLabel(self, text=f"Código enviado para\n{conta['telefone']}",
                     font=("Segoe UI", 13), justify="center").pack(pady=(20, 16))

        ctk.CTkLabel(self, text="Código de verificação").pack()
        self._code = ctk.CTkEntry(self, width=300, placeholder_text="12345")
        self._code.pack(pady=(4, 12))

        ctk.CTkLabel(self, text="Senha 2FA (se houver)").pack()
        self._pw = ctk.CTkEntry(self, width=300, show="*", placeholder_text="Deixe vazio se não tiver")
        self._pw.pack(pady=(4, 20))

        ctk.CTkButton(self, text="Confirmar", command=self._confirm, width=140).pack()

    def _confirm(self):
        code = self._code.get().strip()
        pw   = self._pw.get().strip() or None
        if not code:
            messagebox.showwarning("Aviso", "Informe o código.", parent=self)
            return

        def cb(result, error):
            if error:
                self.after(0, lambda: messagebox.showerror("Erro", error, parent=self))
            else:
                self.after(0, self.destroy)
                self.after(0, self._parent.refresh)

        telegram_manager.confirmar_codigo(self._conta["id"], code, cb, pw)


# ── Helper ────────────────────────────────────────────────────────────────────

def _btn(parent, text, cmd, colors, width=110):
    return ctk.CTkButton(parent, text=text, command=cmd, width=width,
                         fg_color=colors[0], hover_color=colors[1])
