import customtkinter as ctk
from tkinter import messagebox
import database as db

BTN_BLUE = ("#1747a6", "#123a88")
BTN_RED  = ("#e74c3c", "#c0392b")
HDR_BG   = ("#e2e8f2", "#1e293b")
ROW_SEL  = ("#dbeafe", "#1e3a5f")

TIPOS = {
    "Amazon":      "amazon",
    "Mercado Livre": "mercadolivre",
    "Shopee":      "shopee",
    "AliExpress":  "aliexpress",
    "Magalu":      "magalu",
    "Outro":       "outro",
}

EMOJI = {
    "amazon":       "🟠",
    "mercadolivre": "🟡",
    "shopee":       "🟠",
    "aliexpress":   "🔴",
    "magalu":       "🔵",
    "outro":        "⚪",
}


AJUDA_TAG = ("Mercado Livre: no Portal do Afiliado, gere um link de qualquer produto em 'Gerador de link', "
             "escolha LINK COMPLETO e cole aqui (o app extrai matt_word e matt_tool).\n"
             "Amazon: sua tag (ex.: seunome-20). Magalu: nome da sua loja Magazine Você.")


def _validar_tag(tipo: str, tag: str, parent) -> str:
    """Normaliza a tag e avisa se ela não permite converter links."""
    from affiliate_helper import normalizar_tag
    tag, aviso = normalizar_tag(tipo, tag)
    if aviso:
        messagebox.showwarning("Atenção", aviso, parent=parent)
    return tag


class IntegracoesFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, corner_radius=0, fg_color=("#f4f6fb", "#0f1115"))
        self._selected: int | None = None
        self._rows: dict = {}
        self._build()

    def _build(self):
        hdr = ctk.CTkFrame(self, fg_color=("#ffffff", "#181b22"), corner_radius=12)
        hdr.pack(fill="x", padx=16, pady=(16, 8))
        ctk.CTkLabel(hdr, text="Integrações de Afiliados",
                     font=("Segoe UI", 18, "bold")).pack(side="left", padx=16, pady=14)

        bar = ctk.CTkFrame(hdr, fg_color="transparent")
        bar.pack(side="right", padx=12, pady=10)
        ctk.CTkButton(bar, text="+ Adicionar", command=self._add,
                      fg_color=BTN_BLUE[0], hover_color=BTN_BLUE[1], width=110).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="✏️ Editar", command=self._edit,
                      fg_color=("#64748b", "#4b5563"), hover_color=("#475569", "#374151"), width=90).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Remover", command=self._remove,
                      fg_color=BTN_RED[0], hover_color=BTN_RED[1], width=90).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="🧪 Testar link", command=self._testar,
                      fg_color=("#64748b", "#4b5563"), hover_color=("#475569", "#374151"), width=110).pack(side="left", padx=4)

        card = ctk.CTkFrame(self, fg_color=("#ffffff", "#181b22"), corner_radius=12)
        card.pack(fill="both", expand=True, padx=16, pady=8)

        cols = [("", 40), ("Cód.", 50), ("Nome", 160), ("Tipo", 160), ("Tag/ID Afiliado", 240)]
        hrow = ctk.CTkFrame(card, fg_color=HDR_BG, corner_radius=8)
        hrow.pack(fill="x", padx=8, pady=(8, 0))
        for col, w in cols:
            ctk.CTkLabel(hrow, text=col, font=("Segoe UI", 12, "bold"),
                         width=w, anchor="w").pack(side="left", padx=8, pady=8)

        self._list = ctk.CTkScrollableFrame(card, fg_color="transparent")
        self._list.pack(fill="both", expand=True, padx=8, pady=6)

        # Aviso
        info = ctk.CTkFrame(self, fg_color=("#eff6ff", "#1e293b"), corner_radius=8)
        info.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(info,
                     text="ℹ️  Links de loja nos repasses (com 'Substituição Inteligente') e no Radar são reconstruídos com a SUA afiliação; "
                          "tags de outros afiliados são descartadas. Use '🧪 Testar link' para conferir antes de publicar.",
                     font=("Segoe UI", 11), text_color=("#1e40af", "#93c5fd"),
                     wraplength=700, justify="left").pack(padx=16, pady=10, anchor="w")

        self.refresh()

    def refresh(self):
        for w in self._list.winfo_children():
            w.destroy()
        self._rows.clear()
        for intg in db.listar_integracoes():
            self._add_row(intg)

    def _add_row(self, intg: dict):
        row = ctk.CTkFrame(self._list, fg_color="transparent", cursor="hand2", corner_radius=6)
        row.pack(fill="x", pady=1)

        emoji = EMOJI.get(intg["tipo"], "⚪")
        ctk.CTkLabel(row, text=emoji, width=40, font=("Segoe UI", 16)).pack(side="left", padx=6, pady=8)
        ctk.CTkLabel(row, text=str(intg["id"]),  width=50,  anchor="w", font=("Segoe UI", 12)).pack(side="left")
        ctk.CTkLabel(row, text=intg["nome"],      width=160, anchor="w", font=("Segoe UI", 12)).pack(side="left")
        ctk.CTkLabel(row, text=intg["tipo"],      width=160, anchor="w", font=("Segoe UI", 12)).pack(side="left")
        
        tag_text = intg["tag"] or "-"
        if intg["tipo"] == "mercadolivre":
            from affiliate_helper import parametros_ml
            tag_text = ("✅ " + tag_text) if len(parametros_ml(tag_text)) == 2 else "⚠️ falta link completo do portal"
            
        ctk.CTkLabel(row, text=tag_text, width=240, anchor="w", font=("Segoe UI", 12),
                     text_color=("#64748b", "#94a3b8")).pack(side="left")

        for w in [row] + list(row.winfo_children()):
            w.bind("<Button-1>", lambda e, iid=intg["id"]: self._select(iid))

        self._rows[intg["id"]] = row

    def _select(self, iid: int):
        self._selected = iid
        for k, r in self._rows.items():
            r.configure(fg_color=ROW_SEL if k == iid else "transparent")

    def _add(self):
        AdicionarIntegracaoDialog(self)
        self.after(100, self.refresh)

    def _remove(self):
        if not self._selected:
            messagebox.showwarning("Aviso", "Selecione uma integração.")
            return
        if messagebox.askyesno("Confirmar", "Remover esta integração?"):
            db.remover_integracao(self._selected)
            self._selected = None
            self.refresh()

    def _testar(self):
        url = ctk.CTkInputDialog(text="Cole um link de oferta (qualquer loja, pode ser encurtado):",
                                 title="Testar conversão").get_input()
        if not url:
            return
        from telegram_manager import telegram_manager
        from affiliate_helper import converter_links

        def _done(fut):  # roda no loop do Telegram: a tela não trava enquanto resolve o link
            try:
                texto, nao = fut.result()
            except Exception as e:
                texto, nao = "", [f"erro: {e}"]

            def _ui():
                if nao:
                    messagebox.showwarning("Não convertido",
                                           f"Este link NÃO vira afiliado seu:\n{nao[0]}\n\n"
                                           "Confira se a loja tem integração ativa (ML: link completo do portal).")
                else:
                    messagebox.showinfo("Convertido", f"Original:\n{url.strip()}\n\nSeu link:\n{texto}")
            self.after(0, _ui)

        telegram_manager._run(converter_links(url.strip())).add_done_callback(_done)

    def _edit(self):
        if not self._selected:
            messagebox.showwarning("Aviso", "Selecione uma integração para editar.")
            return
        intg = db.get_integracao(self._selected)
        if not intg:
            messagebox.showerror("Erro", "Integração não encontrada.")
            return
        EditarIntegracaoDialog(self, intg)
        self.after(100, self.refresh)


class AdicionarIntegracaoDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self._parent = parent
        self.title("Adicionar Integração")
        self.geometry("420x540")
        self.grab_set()
        self.resizable(False, False)

        # Make sure the top window stays on top on Windows
        self.attributes("-topmost", True)

        ctk.CTkLabel(self, text="Nova Integração de Afiliado",
                     font=("Segoe UI", 16, "bold")).pack(pady=(16, 12))

        ctk.CTkLabel(self, text="Nome (apelido interno)", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=40)
        self._nome = ctk.CTkEntry(self, width=340, placeholder_text="Ex: Minha Conta Mercado Livre")
        self._nome.pack(pady=(2, 10))

        ctk.CTkLabel(self, text="Plataforma", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=40)
        self._tipo_var = ctk.StringVar(value=list(TIPOS.keys())[0])
        self._tipo_menu = ctk.CTkOptionMenu(self, variable=self._tipo_var,
                          values=list(TIPOS.keys()), width=340)
        self._tipo_menu.pack(pady=(2, 10))

        ctk.CTkLabel(self, text="Tag de afiliado (ML: link completo do portal)", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=40)
        self._tag = ctk.CTkEntry(self, width=340, placeholder_text="Sua tag de afiliado")
        self._tag.pack(pady=(2, 10))

        ctk.CTkLabel(self, text=AJUDA_TAG, font=("Segoe UI", 11), wraplength=340, justify="left",
                     text_color=("#64748b", "#94a3b8")).pack(padx=40, pady=(0, 16), anchor="w")

        ctk.CTkButton(self, text="Salvar", command=self._save, width=140, fg_color=BTN_BLUE[0], hover_color=BTN_BLUE[1]).pack(pady=(0, 16))

    def _save(self):
        nome = self._nome.get().strip()
        tag  = self._tag.get().strip()
        tipo = TIPOS.get(self._tipo_var.get(), "outro")
            
        if not nome:
            messagebox.showwarning("Aviso", "Informe o nome.", parent=self)
            return
        tag = _validar_tag(tipo, tag, self)
        db.adicionar_integracao(nome, tipo, tag, "")
        self.destroy()
        self._parent.refresh()


class EditarIntegracaoDialog(ctk.CTkToplevel):
    """Diálogo para editar uma integração existente."""
    def __init__(self, parent, intg: dict):
        super().__init__(parent)
        self._parent = parent
        self._intg_id = intg["id"]
        self.title("Editar Integração")
        self.geometry("420x540")
        self.grab_set()
        self.resizable(False, False)
        self.attributes("-topmost", True)

        ctk.CTkLabel(self, text="Editar Integração de Afiliado",
                     font=("Segoe UI", 16, "bold")).pack(pady=(16, 12))

        ctk.CTkLabel(self, text="Nome (apelido interno)", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=40)
        self._nome = ctk.CTkEntry(self, width=340)
        self._nome.insert(0, intg["nome"])
        self._nome.pack(pady=(2, 10))

        # Descobrir label da plataforma
        tipo_label = next((k for k, v in TIPOS.items() if v == intg["tipo"]), list(TIPOS.keys())[0])
        ctk.CTkLabel(self, text="Plataforma", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=40)
        self._tipo_var = ctk.StringVar(value=tipo_label)
        self._tipo_menu = ctk.CTkOptionMenu(self, variable=self._tipo_var,
                          values=list(TIPOS.keys()), width=340)
        self._tipo_menu.pack(pady=(2, 10))

        ctk.CTkLabel(self, text="Tag de afiliado (ML: link completo do portal)", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=40)
        self._tag = ctk.CTkEntry(self, width=340)
        self._tag.insert(0, intg.get("tag", ""))
        self._tag.pack(pady=(2, 10))

        ctk.CTkLabel(self, text=AJUDA_TAG, font=("Segoe UI", 11), wraplength=340, justify="left",
                     text_color=("#64748b", "#94a3b8")).pack(padx=40, pady=(0, 16), anchor="w")

        ctk.CTkButton(self, text="💾 Salvar Alterações", command=self._save, width=160,
                      fg_color=BTN_BLUE[0], hover_color=BTN_BLUE[1]).pack(pady=(0, 16))

    def _save(self):
        nome = self._nome.get().strip()
        tag  = self._tag.get().strip()
        tipo = TIPOS.get(self._tipo_var.get(), "outro")

        if not nome:
            messagebox.showwarning("Aviso", "Informe o nome.", parent=self)
            return
        tag = _validar_tag(tipo, tag, self)
        db.atualizar_integracao(self._intg_id, nome, tipo, tag, "")
        self.destroy()
        self._parent.refresh()
