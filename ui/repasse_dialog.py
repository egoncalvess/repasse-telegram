"""
Diálogo de criação/edição de repasse.
Inclui: conta, origem, destinos, filtros, substituições, delay, horário.
"""
import json
import customtkinter as ctk
from tkinter import messagebox
import database as db
from telegram_manager import telegram_manager

BTN_BLUE = ("#1a6fd4", "#1558ab")
BTN_RED  = ("#e74c3c", "#c0392b")
BTN_GRAY = ("#64748b", "#4b5563")


class RepasseDialog(ctk.CTkToplevel):
    def __init__(self, parent, repasse_id: int | None):
        super().__init__(parent)
        self._rid = repasse_id
        self._destinos: list[dict] = []
        self._subs: list[dict] = []
        self._grupos_cache: list[dict] = []
        self._origem_id_cached = None
        self._origem_nome_cached = None

        r = db.get_repasse(repasse_id) if repasse_id else None
        self.title("Editar Repasse" if r else "Novo Repasse")
        self.geometry("760x640")
        self.grab_set()
        self.resizable(True, True)

        self._build(r)
        if r:
            self._populate(r)

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build(self, r):
        main = ctk.CTkScrollableFrame(self, fg_color=("#f1f5fb", "#121212"))
        main.pack(fill="both", expand=True)
        self._main = main

        # ── Nome ──────────────────────────────────────────────────────────────
        _section(main, "Identificação")
        ctk.CTkLabel(main, text="Nome da tarefa").pack(anchor="w", padx=16)
        self._nome = ctk.CTkEntry(main, width=500, placeholder_text="Ex: Amazon → Meu Grupo")
        self._nome.pack(anchor="w", padx=16, pady=(4, 12))

        # ── Conta ─────────────────────────────────────────────────────────────
        _section(main, "Conta Vinculada (Telegram)")
        contas = db.listar_contas()
        self._conta_map = {f"{c['apelido']} ({c['telefone']})": (c["id"], c.get("tipo", "telegram")) for c in contas}
        conta_opts = list(self._conta_map.keys()) or ["(nenhuma conta cadastrada)"]

        row_conta = ctk.CTkFrame(main, fg_color="transparent")
        row_conta.pack(fill="x", padx=16, pady=(4, 0))
        ctk.CTkLabel(row_conta, text="Conta:").pack(side="left")
        self._conta_var = ctk.StringVar(value=conta_opts[0])
        ctk.CTkOptionMenu(row_conta, variable=self._conta_var,
                          values=conta_opts, width=300,
                          command=self._on_conta_change).pack(side="left", padx=8)
        ctk.CTkButton(row_conta, text="Carregar Grupos", command=self._load_groups,
                      width=140, fg_color=BTN_GRAY[0], hover_color=BTN_GRAY[1]).pack(side="left", padx=4)

        # ── Origem ────────────────────────────────────────────────────────────
        _section(main, "Grupo de Origem")
        self._origem_opts = ["(carregue os grupos)"]
        self._origem_var = ctk.StringVar(value=self._origem_opts[0])
        self._origem_menu = ctk.CTkOptionMenu(main, variable=self._origem_var,
                                              values=self._origem_opts, width=400)
        self._origem_menu.pack(anchor="w", padx=16, pady=(4, 12))

        # ── Destinos ──────────────────────────────────────────────────────────
        _section(main, "Grupos de Destino")

        dest_ctrl = ctk.CTkFrame(main, fg_color="transparent")
        dest_ctrl.pack(fill="x", padx=16, pady=(4, 0))

        self._dest_var = ctk.StringVar(value="(carregue os grupos)")
        self._dest_menu = ctk.CTkOptionMenu(dest_ctrl, variable=self._dest_var,
                                            values=["(carregue os grupos)"], width=350)
        self._dest_menu.pack(side="left")
        ctk.CTkButton(dest_ctrl, text="+ Adicionar", command=self._add_dest,
                      width=100, fg_color=BTN_BLUE[0], hover_color=BTN_BLUE[1]).pack(side="left", padx=8)

        self._dest_list = ctk.CTkFrame(main, fg_color=("white", "#1e1e1e"), corner_radius=8)
        self._dest_list.pack(fill="x", padx=16, pady=(6, 12))
        self._dest_placeholder = ctk.CTkLabel(self._dest_list,
                                              text="Nenhum destino adicionado",
                                              text_color=("#94a3b8", "#64748b"))
        self._dest_placeholder.pack(pady=8)

        # ── Filtros ───────────────────────────────────────────────────────────
        _section(main, "Filtros de Mídia (bloquear se marcado)")
        frow = ctk.CTkFrame(main, fg_color="transparent")
        frow.pack(anchor="w", padx=16, pady=(4, 4))
        self._f_links  = _check(frow, "Links")
        self._f_img    = _check(frow, "Imagens")
        self._f_vid    = _check(frow, "Vídeos")
        self._f_aud    = _check(frow, "Áudios")

        # ── Configurações Avançadas ───────────────────────────────────────────
        _section(main, "Opções Especiais")
        frow_spec = ctk.CTkFrame(main, fg_color="transparent")
        frow_spec.pack(anchor="w", padx=16, pady=(4, 4))
        self._f_aff    = _check(frow_spec, "Substituição Inteligente de Links Afiliados")
        frow_of = ctk.CTkFrame(main, fg_color="transparent")
        frow_of.pack(anchor="w", padx=16, pady=(0, 4))
        self._f_ofertas = _check(frow_of, "Somente ofertas (msg com link de loja)")
        self._f_dedup   = _check(frow_of, "Não repetir o mesmo produto (24h)")


        # ── Termos ────────────────────────────────────────────────────────────
        _section(main, "Filtro por Palavras")
        ctk.CTkLabel(main, text="Bloquear se a msg contiver (separe por vírgula):").pack(anchor="w", padx=16)
        self._termos_bloquear = ctk.CTkEntry(main, width=500, placeholder_text="promoção, patrocinado")
        self._termos_bloquear.pack(anchor="w", padx=16, pady=(4, 8))

        ctk.CTkLabel(main, text="Repassar SOMENTE se contiver (separe por vírgula):").pack(anchor="w", padx=16)
        self._termos_permitir = ctk.CTkEntry(main, width=500, placeholder_text="R$, desconto, off")
        self._termos_permitir.pack(anchor="w", padx=16, pady=(4, 12))

        # ── Substituições ─────────────────────────────────────────────────────
        _section(main, "Substituições de Texto")

        sub_ctrl = ctk.CTkFrame(main, fg_color="transparent")
        sub_ctrl.pack(fill="x", padx=16, pady=(4, 0))
        self._sub_busca = ctk.CTkEntry(sub_ctrl, width=200, placeholder_text="Buscar")
        self._sub_busca.pack(side="left")
        ctk.CTkLabel(sub_ctrl, text=" → ").pack(side="left")
        self._sub_rep = ctk.CTkEntry(sub_ctrl, width=200, placeholder_text="Substituir por")
        self._sub_rep.pack(side="left")
        ctk.CTkButton(sub_ctrl, text="+ Adicionar", command=self._add_sub,
                      width=100, fg_color=BTN_BLUE[0], hover_color=BTN_BLUE[1]).pack(side="left", padx=8)

        self._sub_list = ctk.CTkFrame(main, fg_color=("white", "#1e1e1e"), corner_radius=8)
        self._sub_list.pack(fill="x", padx=16, pady=(6, 12))
        self._sub_placeholder = ctk.CTkLabel(self._sub_list,
                                             text="Nenhuma substituição cadastrada",
                                             text_color=("#94a3b8", "#64748b"))
        self._sub_placeholder.pack(pady=8)

        # ── Config ────────────────────────────────────────────────────────────
        _section(main, "Configurações de Envio")
        cfg_row = ctk.CTkFrame(main, fg_color="transparent")
        cfg_row.pack(anchor="w", padx=16, pady=(4, 4))

        ctk.CTkLabel(cfg_row, text="Delay (seg):").pack(side="left")
        self._delay = ctk.CTkEntry(cfg_row, width=70)
        self._delay.insert(0, "1")
        self._delay.pack(side="left", padx=(4, 20))

        ctk.CTkLabel(cfg_row, text="Limite diário (0=ilimitado):").pack(side="left")
        self._limite = ctk.CTkEntry(cfg_row, width=70)
        self._limite.insert(0, "0")
        self._limite.pack(side="left", padx=4)

        hor_row = ctk.CTkFrame(main, fg_color="transparent")
        hor_row.pack(anchor="w", padx=16, pady=(4, 20))
        ctk.CTkLabel(hor_row, text="Funcionar entre:").pack(side="left")
        self._h_ini = ctk.CTkEntry(hor_row, width=70, placeholder_text="00:00")
        self._h_ini.pack(side="left", padx=(4, 4))
        ctk.CTkLabel(hor_row, text="até").pack(side="left")
        self._h_fim = ctk.CTkEntry(hor_row, width=70, placeholder_text="00:00")
        self._h_fim.pack(side="left", padx=4)
        ctk.CTkLabel(hor_row, text="(00:00 em ambos = sem restrição)",
                     font=("Arial", 10), text_color=("#94a3b8", "#64748b")).pack(side="left", padx=8)

        # ── Salvar ────────────────────────────────────────────────────────────
        foot = ctk.CTkFrame(self, fg_color=("white", "#1c1c1c"), corner_radius=0)
        foot.pack(fill="x", side="bottom")
        ctk.CTkButton(foot, text="💾 Salvar", command=self._save,
                      width=140, height=38).pack(side="right", padx=16, pady=10)
        ctk.CTkButton(foot, text="Cancelar", command=self.destroy,
                      width=100, height=38, fg_color=BTN_GRAY[0],
                      hover_color=BTN_GRAY[1]).pack(side="right", padx=4, pady=10)

    # ── Populate (edit mode) ──────────────────────────────────────────────────

    def _populate(self, r: dict):
        self._nome.insert(0, r["descricao"])
        self._origem_id_cached = r["origem_id"]
        self._origem_nome_cached = r["origem_nome"]

        # Selecionar conta
        for label, entry in self._conta_map.items():
            if entry[0] == r["conta_id"]:
                self._conta_var.set(label)
                break

        # Origem (load groups then select)
        if r["origem_nome"]:
            self._origem_opts = [r["origem_nome"]]
            self._origem_var.set(r["origem_nome"])
            self._origem_menu.configure(values=self._origem_opts)

        # Destinos
        for d in db.listar_destinos(r["id"]):
            self._destinos.append(d)
        self._render_destinos()

        # Filtros
        filtros = json.loads(r["filtros"] or "{}")
        if filtros.get("links"):  self._f_links.select()
        if filtros.get("imagens"): self._f_img.select()
        if filtros.get("videos"): self._f_vid.select()
        if filtros.get("audios"): self._f_aud.select()
        if filtros.get("substituir_afiliados"): self._f_aff.select()
        if filtros.get("somente_ofertas"): self._f_ofertas.select()
        if filtros.get("sem_repetidas"): self._f_dedup.select()


        # Termos
        self._termos_bloquear.insert(0, r["termos_bloquear"] or "")
        self._termos_permitir.insert(0, r["termos_permitir"] or "")

        # Substituições
        self._subs = json.loads(r["substituicoes"] or "[]")
        self._render_subs()

        # Config
        self._delay.delete(0, "end")
        self._delay.insert(0, str(r["delay"] or 1))
        self._limite.delete(0, "end")
        self._limite.insert(0, str(r["limite_diario"] or 0))
        self._h_ini.insert(0, r["horario_inicio"] or "00:00")
        self._h_fim.insert(0, r["horario_fim"] or "00:00")

    # ── Grupos ───────────────────────────────────────────────────────────────

    def _on_conta_change(self, _):
        self._grupos_cache = []

    def _load_groups(self):
        conta_label = self._conta_var.get()
        entry = self._conta_map.get(conta_label)
        if not entry:
            messagebox.showwarning("Aviso", "Selecione uma conta.", parent=self)
            return
        conta_id, tipo = entry

        if conta_id not in telegram_manager.clients:
            messagebox.showwarning("Aviso",
                "Conta não conectada. Conecte a conta em 'Contas' primeiro.", parent=self)
            return

        def cb(groups, error):
            if error:
                self.after(0, lambda: messagebox.showerror("Erro", error, parent=self))
                return
            self._grupos_cache = groups
            nomes = [g["nome"] for g in groups]
            if not nomes:
                nomes = ["(nenhum grupo encontrado)"]
            self.after(0, lambda: self._origem_menu.configure(values=nomes))
            self.after(0, lambda: self._dest_menu.configure(values=nomes))
            # Preservar seleção existente (modo edição) em vez de sobrescrever
            def _preserve_selections():
                if self._origem_var.get() not in nomes:
                    self._origem_var.set(nomes[0])
                if self._dest_var.get() not in nomes:
                    self._dest_var.set(nomes[0])
                # Re-renderizar destinos para garantir que permaneçam visíveis
                self._render_destinos()
            self.after(50, _preserve_selections)

        telegram_manager.get_groups(conta_id, cb)

    # ── Destinos ─────────────────────────────────────────────────────────────

    def _add_dest(self):
        nome = self._dest_var.get()
        if not nome or nome.startswith("("):
            messagebox.showwarning("Aviso", "Carregue os grupos primeiro.", parent=self)
            return
        gid = next((g["id"] for g in self._grupos_cache if g["nome"] == nome), None)
        if not gid:
            # Permite adicionar por nome sem id (se grupos não carregados)
            gid = nome
        if any(d["grupo_nome"] == nome for d in self._destinos):
            return  # Já existe
        self._destinos.append({"grupo_id": gid, "grupo_nome": nome})
        self._render_destinos()

    def _remove_dest(self, nome: str):
        self._destinos = [d for d in self._destinos if d["grupo_nome"] != nome]
        self._render_destinos()

    def _render_destinos(self):
        for w in self._dest_list.winfo_children():
            w.destroy()
        if not self._destinos:
            ctk.CTkLabel(self._dest_list, text="Nenhum destino adicionado",
                         text_color=("#94a3b8", "#64748b")).pack(pady=8)
            return
        for d in self._destinos:
            row = ctk.CTkFrame(self._dest_list, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=2)
            ctk.CTkLabel(row, text=d["grupo_nome"], anchor="w").pack(side="left", padx=4)
            ctk.CTkButton(row, text="✕", width=28, height=24,
                          fg_color=BTN_RED[0], hover_color=BTN_RED[1],
                          command=lambda n=d["grupo_nome"]: self._remove_dest(n)).pack(side="right")

    # ── Substituições ─────────────────────────────────────────────────────────

    def _add_sub(self):
        busca = self._sub_busca.get().strip()
        rep   = self._sub_rep.get().strip()
        if not busca:
            messagebox.showwarning("Aviso", "Informe o texto a buscar.", parent=self)
            return
        self._subs.append({"busca": busca, "substituir": rep})
        self._sub_busca.delete(0, "end")
        self._sub_rep.delete(0, "end")
        self._render_subs()

    def _remove_sub(self, idx: int):
        self._subs.pop(idx)
        self._render_subs()

    def _render_subs(self):
        for w in self._sub_list.winfo_children():
            w.destroy()
        if not self._subs:
            ctk.CTkLabel(self._sub_list, text="Nenhuma substituição cadastrada",
                         text_color=("#94a3b8", "#64748b")).pack(pady=8)
            return
        for i, s in enumerate(self._subs):
            row = ctk.CTkFrame(self._sub_list, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=2)
            ctk.CTkLabel(row,
                         text=f'"{s["busca"]}" → "{s["substituir"]}"',
                         anchor="w", font=("Arial", 11)).pack(side="left", padx=4)
            ctk.CTkButton(row, text="✕", width=28, height=24,
                          fg_color=BTN_RED[0], hover_color=BTN_RED[1],
                          command=lambda idx=i: self._remove_sub(idx)).pack(side="right")

    # ── Salvar ────────────────────────────────────────────────────────────────

    def _save(self):
        nome = self._nome.get().strip()
        if not nome:
            messagebox.showwarning("Aviso", "Informe o nome da tarefa.", parent=self)
            return

        conta_label = self._conta_var.get()
        entry = self._conta_map.get(conta_label)
        if not entry:
            messagebox.showwarning("Aviso", "Selecione uma conta válida.", parent=self)
            return
        conta_id, tipo = entry

        origem_nome = self._origem_var.get()
        origem_id = next((g["id"] for g in self._grupos_cache if g["nome"] == origem_nome), None)
        if not origem_id:
            if self._origem_id_cached and origem_nome == self._origem_nome_cached:
                origem_id = self._origem_id_cached
            else:
                origem_id = origem_nome

        try:
            delay  = int(self._delay.get() or 1)
            limite = int(self._limite.get() or 0)
        except ValueError:
            messagebox.showwarning("Aviso", "Delay e limite devem ser números.", parent=self)
            return

        filtros = {
            "links":   bool(self._f_links.get()),
            "imagens": bool(self._f_img.get()),
            "videos":  bool(self._f_vid.get()),
            "audios":  bool(self._f_aud.get()),
            "substituir_afiliados": bool(self._f_aff.get()),
            "somente_ofertas": bool(self._f_ofertas.get()),
            "sem_repetidas": bool(self._f_dedup.get()),
        }

        dados = {
            "descricao":       nome,
            "conta_id":        conta_id,
            "origem_id":       str(origem_id),
            "origem_nome":     origem_nome,
            "filtros":         json.dumps(filtros),
            "substituicoes":   json.dumps(self._subs),
            "delay":           delay,
            "limite_diario":   limite,
            "horario_inicio":  self._h_ini.get().strip() or "00:00",
            "horario_fim":     self._h_fim.get().strip() or "00:00",
            "termos_bloquear": self._termos_bloquear.get().strip(),
            "termos_permitir": self._termos_permitir.get().strip(),
        }

        if self._rid:
            db.atualizar_repasse(self._rid, dados)
            db.set_destinos(self._rid, self._destinos)
        else:
            rid = db.adicionar_repasse(dados)
            db.set_destinos(rid, self._destinos)

        self.destroy()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _section(parent, title: str):
    f = ctk.CTkFrame(parent, fg_color="transparent")
    f.pack(fill="x", padx=16, pady=(14, 2))
    ctk.CTkLabel(f, text=title, font=("Arial", 13, "bold")).pack(side="left")
    sep = ctk.CTkFrame(f, height=1, fg_color=("#cbd5e1", "#334155"))
    sep.pack(side="left", fill="x", expand=True, padx=(8, 0), pady=6)


def _check(parent, text: str) -> ctk.CTkCheckBox:
    cb = ctk.CTkCheckBox(parent, text=text)
    cb.pack(side="left", padx=12)
    return cb
