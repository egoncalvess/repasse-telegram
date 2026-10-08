import customtkinter as ctk
from tkinter import messagebox
import database as db
from telegram_manager import telegram_manager

BTN_BLUE  = ("#1a6fd4", "#1558ab")
BTN_RED   = ("#e74c3c", "#c0392b")
BTN_GRAY  = ("#64748b", "#4b5563")
ROW_SEL   = ("#dbeafe", "#1e3a5f")
HDR_BG    = ("#e2e8f2", "#1e293b")


class RepassesFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, corner_radius=0, fg_color=("#f1f5fb", "#121212"))
        self._selected: int | None = None
        self._rows: dict = {}
        self._switches: dict = {}
        self._build()

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=("white", "#1e1e1e"), corner_radius=12)
        hdr.pack(fill="x", padx=16, pady=(16, 8))

        ctk.CTkLabel(hdr, text="Repasses",
                     font=("Arial", 18, "bold")).pack(side="left", padx=16, pady=14)

        bar = ctk.CTkFrame(hdr, fg_color="transparent")
        bar.pack(side="right", padx=12, pady=10)

        _btn(bar, "+ Adicionar", self._add,     BTN_BLUE).pack(side="left", padx=4)
        _btn(bar, "Editar",      self._edit,    BTN_GRAY).pack(side="left", padx=4)
        _btn(bar, "Remover",     self._remove,  BTN_RED).pack(side="left",  padx=4)
        _btn(bar, "Relatório",   self._report,  BTN_GRAY, width=90).pack(side="left", padx=4)

        # Table
        card = ctk.CTkFrame(self, fg_color=("white", "#1e1e1e"), corner_radius=12)
        card.pack(fill="both", expand=True, padx=16, pady=8)

        cols = [("Status", 70), ("Cód.", 55), ("Descrição", 220), ("Total", 80)]
        hrow = ctk.CTkFrame(card, fg_color=HDR_BG, corner_radius=8)
        hrow.pack(fill="x", padx=8, pady=(8, 0))
        for col, w in cols:
            ctk.CTkLabel(hrow, text=col, font=("Arial", 12, "bold"),
                         width=w, anchor="w").pack(side="left", padx=8, pady=8)
        ctk.CTkLabel(hrow, text="Mapeamento de Canais (Origem ➔ Destinos)", font=("Arial", 12, "bold"),
                     anchor="w").pack(side="left", padx=8, pady=8)

        self._list = ctk.CTkScrollableFrame(card, fg_color="transparent")
        self._list.pack(fill="both", expand=True, padx=8, pady=6)

        self.refresh()

    # ── Refresh ──────────────────────────────────────────────────────────────

    def refresh(self):
        for w in self._list.winfo_children():
            w.destroy()
        self._rows.clear()
        self._switches.clear()
        repasses = db.listar_repasses()
        if not repasses:
            empty_lbl = ctk.CTkLabel(self._list, text="Nenhum repasse cadastrado. Clique em '+ Adicionar' para criar um novo repasse.", text_color=("#64748b", "#94a3b8"))
            empty_lbl.pack(pady=40)
            return

        for r in repasses:
            self._add_row(r)

    def _add_row(self, r: dict):
        row = ctk.CTkFrame(self._list, fg_color="transparent",
                           cursor="hand2", corner_radius=8)
        row.pack(fill="x", pady=3)

        # Container do Switch com Toggle Responsivo
        sw_wrap = ctk.CTkFrame(row, fg_color="transparent", width=70)
        sw_wrap.pack(side="left", padx=4)
        
        is_ativo = bool(r["ativo"])
        sw_var = ctk.BooleanVar(value=is_ativo)
        sw = ctk.CTkSwitch(
            sw_wrap, 
            text="", 
            variable=sw_var, 
            width=46,
            progress_color="#2ecc71",
            button_color="#1a6fd4" if is_ativo else "#64748b",
            button_hover_color="#1558ab",
            command=lambda rid=r["id"], v=sw_var, sw_widget=None: self._toggle(rid, v)
        )
        sw.pack(side="left", padx=4, pady=4)
        self._switches[r["id"]] = sw_var

        # Código, Descrição e Total
        ctk.CTkLabel(row, text=str(r["id"]),     width=55,  anchor="w", font=("Arial", 12, "bold")).pack(side="left", padx=4)
        ctk.CTkLabel(row, text=r["descricao"],   width=220, anchor="w", font=("Arial", 12, "bold")).pack(side="left", padx=4)
        
        # Badge de Total de Repasses
        total_badge = ctk.CTkFrame(row, fg_color=("#eff6ff", "#1e293b"), corner_radius=6, width=65, height=26)
        total_badge.pack(side="left", padx=4)
        total_badge.pack_propagate(False)
        ctk.CTkLabel(total_badge, text=f"📦 {r['total']}", font=("Arial", 11, "bold"), text_color=BTN_BLUE[0]).pack(expand=True)

        # Mapeamento de Canais com Badges Visuais Limpas
        badges_container = ctk.CTkFrame(row, fg_color="transparent")
        badges_container.pack(side="left", fill="x", expand=True, padx=8)

        # Badge de Origem
        orig_txt = r["origem_nome"] or "Não configurado"
        if len(orig_txt) > 22:
            orig_txt = orig_txt[:20] + "..."
            
        orig_badge = ctk.CTkFrame(badges_container, fg_color=("#dbeafe", "#1e3a5f"), corner_radius=6, height=24)
        orig_badge.pack(side="left", padx=(0, 4))
        ctk.CTkLabel(orig_badge, text=f"📡 {orig_txt}", font=("Arial", 10, "bold"), text_color=("#1e40af", "#93c5fd")).pack(padx=8, pady=2)

        # Seta de fluxo
        ctk.CTkLabel(badges_container, text="➔", font=("Arial", 12, "bold"), text_color=("#64748b", "#94a3b8")).pack(side="left", padx=2)

        # Badges dos Destinos Mapeados
        destinos = db.listar_destinos(r["id"])
        if not destinos:
            none_badge = ctk.CTkFrame(badges_container, fg_color=("#f1f5f9", "#334155"), corner_radius=6, height=24)
            none_badge.pack(side="left", padx=4)
            ctk.CTkLabel(none_badge, text="Nenhum destino", font=("Arial", 10), text_color=("#64748b", "#94a3b8")).pack(padx=8, pady=2)
        else:
            for idx, d in enumerate(destinos[:3]):
                dname = d["grupo_nome"] or "Destino"
                if len(dname) > 18:
                    dname = dname[:16] + "..."
                dest_badge = ctk.CTkFrame(badges_container, fg_color=("#dcfce7", "#14532d"), corner_radius=6, height=24)
                dest_badge.pack(side="left", padx=3)
                ctk.CTkLabel(dest_badge, text=f"🎯 {dname}", font=("Arial", 10, "bold"), text_color=("#15803d", "#86efac")).pack(padx=8, pady=2)
            
            if len(destinos) > 3:
                more_badge = ctk.CTkFrame(badges_container, fg_color=("#f1f5f9", "#334155"), corner_radius=6, height=24)
                more_badge.pack(side="left", padx=3)
                ctk.CTkLabel(more_badge, text=f"+{len(destinos)-3}", font=("Arial", 10, "bold")).pack(padx=6, pady=2)

        # Linha separadora suave
        sep = ctk.CTkFrame(self._list, fg_color=("#e2e8f2", "#2e2e2e"), height=1)
        sep.pack(fill="x", padx=4, pady=2)

        # Bind de seleção em todos os elementos não-interativos
        def _bind_all(widget):
            if not isinstance(widget, ctk.CTkSwitch):
                widget.bind("<Button-1>", lambda e, rid=r["id"]: self._select(rid))
                for child in widget.winfo_children():
                    _bind_all(child)

        _bind_all(row)

        self._rows[r["id"]] = row

    def _select(self, rid: int):
        self._selected = rid
        for k, r in self._rows.items():
            r.configure(fg_color=ROW_SEL if k == rid else "transparent")

    def _toggle(self, rid: int, var: ctk.BooleanVar):
        ativo = int(var.get())
        db.toggle_repasse(rid, ativo)
        if ativo:
            telegram_manager.iniciar_repasse(rid)
        else:
            r = db.get_repasse(rid)
            if r:
                telegram_manager.parar_repasse(rid, r["conta_id"])

    # ── Ações ────────────────────────────────────────────────────────────────

    def _add(self):
        from ui.repasse_dialog import RepasseDialog
        dlg = RepasseDialog(self, repasse_id=None)
        self.wait_window(dlg)
        self.refresh()

    def _edit(self):
        if not self._selected:
            messagebox.showwarning("Aviso", "Selecione um repasse.")
            return
        from ui.repasse_dialog import RepasseDialog
        dlg = RepasseDialog(self, repasse_id=self._selected)
        self.wait_window(dlg)
        self.refresh()

    def _remove(self):
        if not self._selected:
            messagebox.showwarning("Aviso", "Selecione um repasse.")
            return
        if messagebox.askyesno("Confirmar", "Remover este repasse?"):
            r = db.get_repasse(self._selected)
            if r:
                telegram_manager.parar_repasse(self._selected, r["conta_id"])
            db.remover_repasse(self._selected)
            self._selected = None
            self.refresh()

    def _report(self):
        if not self._selected:
            messagebox.showwarning("Aviso", "Selecione um repasse.")
            return
        ReportDialog(self, self._selected)


# ── Relatório ─────────────────────────────────────────────────────────────────

class ReportDialog(ctk.CTkToplevel):
    def __init__(self, parent, repasse_id: int):
        super().__init__(parent)
        self._rid = repasse_id
        r = db.get_repasse(repasse_id)
        self.title(f"Relatório — {r['descricao'] if r else repasse_id}")
        self.geometry("820x480")
        self.grab_set()

        # Header
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=12)
        ctk.CTkLabel(hdr, text="Relatório de Repasse",
                     font=("Arial", 16, "bold")).pack(side="left")
        ctk.CTkButton(hdr, text="↻ Atualizar", width=110,
                      command=self._load).pack(side="right")

        # Cols header
        cols = [("Data", 150), ("Destino", 180), ("Status", 90), ("Detalhes", 360)]
        hrow = ctk.CTkFrame(self, fg_color=HDR_BG, corner_radius=8)
        hrow.pack(fill="x", padx=16)
        for col, w in cols:
            ctk.CTkLabel(hrow, text=col, font=("Arial", 12, "bold"),
                         width=w, anchor="w").pack(side="left", padx=8, pady=8)

        self._list = ctk.CTkScrollableFrame(self, fg_color=("white", "#1e1e1e"), corner_radius=8)
        self._list.pack(fill="both", expand=True, padx=16, pady=8)

        self._load()

    def _load(self):
        for w in self._list.winfo_children():
            w.destroy()

        for h in db.listar_historico(self._rid):
            row = ctk.CTkFrame(self._list, fg_color="transparent")
            row.pack(fill="x", pady=1)

            sc = ("#27ae60", "#2ecc71") if h["status"] == "Sucesso" else ("#e74c3c", "#f87171")
            ctk.CTkLabel(row, text=h["data"] or "-",    width=150, anchor="w", font=("Arial", 11)).pack(side="left", padx=6, pady=6)
            ctk.CTkLabel(row, text=h["destino"] or "-", width=180, anchor="w", font=("Arial", 11)).pack(side="left")
            ctk.CTkLabel(row, text=h["status"],         width=90,  anchor="w", font=("Arial", 11), text_color=sc).pack(side="left")
            ctk.CTkLabel(row, text=(h["detalhes"] or "")[:80], anchor="w",
                         font=("Arial", 11), text_color=("#64748b", "#94a3b8")).pack(side="left", padx=4)


# ── Helper ────────────────────────────────────────────────────────────────────

def _btn(parent, text, cmd, colors, width=100):
    return ctk.CTkButton(parent, text=text, command=cmd, width=width,
                         fg_color=colors[0], hover_color=colors[1])
