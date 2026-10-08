"""
Diálogo de criação/edição de repasse.
Várias origens -> vários destinos, escolhidos de uma vez no seletor (busca + marcação múltipla).
"""
import json
import re
import customtkinter as ctk
from tkinter import messagebox
import database as db
from telegram_manager import telegram_manager
from ui.estilo import botao, FUNDO, CARD, BORDA, TEXTO_SEC, F_SUBTITULO, F_PEQUENA, F_NORMAL
from ui.seletor_chats import SeletorChats


class RepasseDialog(ctk.CTkToplevel):
    def __init__(self, parent, repasse_id: int | None, ao_salvar=None):
        super().__init__(parent)
        self._rid = repasse_id
        self._ao_salvar = ao_salvar
        self._origens: list[dict] = []   # {'origem_id', 'origem_nome'}
        self._destinos: list[dict] = []  # {'grupo_id', 'grupo_nome'}
        self._subs: list[dict] = []

        r = db.get_repasse(repasse_id) if repasse_id else None
        self.title("Editar Repasse" if r else "Novo Repasse")
        self.geometry("780x700")
        self.minsize(640, 520)
        self.configure(fg_color=FUNDO)
        self.transient(parent)
        self.grab_set()

        self._build()
        if r:
            self._populate(r)
        self._render_listas()

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build(self):
        foot = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0)
        foot.pack(fill="x", side="bottom")
        botao(foot, "💾 Salvar", self._save, "azul", 140).pack(side="right", padx=16, pady=10)
        botao(foot, "Cancelar", self.destroy, "cinza", 100).pack(side="right", pady=10)

        main = ctk.CTkScrollableFrame(self, fg_color=FUNDO)
        main.pack(fill="both", expand=True)

        sec = _secao(main, "Identificação")
        self._nome = ctk.CTkEntry(sec, placeholder_text="Ex: Canais de promoção → PROMO DO BAIANO", height=34)
        self._nome.pack(fill="x", padx=14, pady=(0, 10))
        contas = db.listar_contas()
        self._conta_map = {f"{c['apelido']} ({c['telefone']})": c["id"] for c in contas}
        opts = list(self._conta_map) or ["(nenhuma conta cadastrada)"]
        linha = ctk.CTkFrame(sec, fg_color="transparent")
        linha.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkLabel(linha, text="Conta que lê as origens:", font=F_NORMAL).pack(side="left")
        self._conta_var = ctk.StringVar(value=opts[0])
        ctk.CTkOptionMenu(linha, variable=self._conta_var, values=opts, width=280).pack(side="left", padx=8)

        sec = _secao(main, "De onde → para onde")
        grade = ctk.CTkFrame(sec, fg_color="transparent")
        grade.pack(fill="x", padx=14, pady=(0, 12))
        grade.grid_columnconfigure((0, 1), weight=1, uniform="col")
        self._lbl_origens = self._bloco_lista(grade, 0, "📥 Origens", "Escolher origens...", self._escolher_origens)
        self._lbl_destinos = self._bloco_lista(grade, 1, "📤 Destinos", "Escolher destinos...", self._escolher_destinos)

        sec = _secao(main, "Ofertas e afiliação")
        for linha_opts in [[("_f_aff", "Trocar links pelos meus links de afiliado"),
                            ("_f_exigir", "Só repassar se todos os links virarem meus")],
                           [("_f_ofertas", "Somente ofertas (msg com link de loja)"),
                            ("_f_dedup", "Não repetir o mesmo produto (24h)")]]:
            fr = ctk.CTkFrame(sec, fg_color="transparent")
            fr.pack(fill="x", padx=14, pady=(0, 8))
            for attr, txt in linha_opts:
                cb = ctk.CTkCheckBox(fr, text=txt, font=F_NORMAL)
                cb.pack(side="left", padx=(0, 18))
                setattr(self, attr, cb)

        sec = _secao(main, "Bloquear mensagens com mídia")
        fr = ctk.CTkFrame(sec, fg_color="transparent")
        fr.pack(fill="x", padx=14, pady=(0, 12))
        for attr, txt in [("_f_links", "Links"), ("_f_img", "Imagens"), ("_f_vid", "Vídeos"), ("_f_aud", "Áudios")]:
            cb = ctk.CTkCheckBox(fr, text=txt, font=F_NORMAL)
            cb.pack(side="left", padx=(0, 18))
            setattr(self, attr, cb)

        sec = _secao(main, "Filtro por palavras (separe por vírgula)")
        self._termos_bloquear = ctk.CTkEntry(sec, placeholder_text="Bloquear se contiver: patrocinado, sorteio", height=34)
        self._termos_bloquear.pack(fill="x", padx=14, pady=(0, 8))
        self._termos_permitir = ctk.CTkEntry(sec, placeholder_text="Repassar SOMENTE se contiver: R$, desconto, cupom", height=34)
        self._termos_permitir.pack(fill="x", padx=14, pady=(0, 12))

        sec = _secao(main, "Substituições de texto")
        fr = ctk.CTkFrame(sec, fg_color="transparent")
        fr.pack(fill="x", padx=14, pady=(0, 6))
        fr.grid_columnconfigure((0, 2), weight=1)
        self._sub_busca = ctk.CTkEntry(fr, placeholder_text="Buscar", height=32)
        self._sub_busca.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(fr, text=" → ").grid(row=0, column=1)
        self._sub_rep = ctk.CTkEntry(fr, placeholder_text="Substituir por", height=32)
        self._sub_rep.grid(row=0, column=2, sticky="ew")
        botao(fr, "+ Adicionar", self._add_sub, "azul", 100).grid(row=0, column=3, padx=(8, 0))
        self._sub_list = ctk.CTkFrame(sec, fg_color="transparent")
        self._sub_list.pack(fill="x", padx=14, pady=(0, 12))

        sec = _secao(main, "Ritmo de envio")
        fr = ctk.CTkFrame(sec, fg_color="transparent")
        fr.pack(fill="x", padx=14, pady=(0, 12))
        self._delay = _campo(fr, "Espera (seg)", "1")
        self._limite = _campo(fr, "Limite/dia (0 = sem)", "0")
        self._h_ini = _campo(fr, "Das", "00:00")
        self._h_fim = _campo(fr, "Até", "00:00")
        ctk.CTkLabel(fr, text="00:00–00:00 = o dia todo", font=F_PEQUENA, text_color=TEXTO_SEC).pack(side="left", padx=6)

    def _bloco_lista(self, grade, col, titulo, txt_botao, comando):
        caixa = ctk.CTkFrame(grade, fg_color=FUNDO, corner_radius=10)
        caixa.grid(row=0, column=col, sticky="nsew", padx=(0, 8) if col == 0 else (8, 0))
        ctk.CTkLabel(caixa, text=titulo, font=F_SUBTITULO).pack(anchor="w", padx=12, pady=(10, 4))
        lbl = ctk.CTkLabel(caixa, text="", font=F_PEQUENA, text_color=TEXTO_SEC, justify="left", anchor="w")
        lbl.pack(fill="x", padx=12)
        botao(caixa, txt_botao, comando, "cinza", 170).pack(anchor="w", padx=12, pady=10)
        return lbl

    # ── Populate (edição) ─────────────────────────────────────────────────────

    def _populate(self, r: dict):
        self._nome.insert(0, r["descricao"])
        for label, cid in self._conta_map.items():
            if cid == r["conta_id"]:
                self._conta_var.set(label)
        self._origens = db.listar_origens(r["id"])
        self._destinos = db.listar_destinos(r["id"])
        filtros = json.loads(r["filtros"] or "{}")
        for chave, cb in [("links", self._f_links), ("imagens", self._f_img), ("videos", self._f_vid),
                          ("audios", self._f_aud), ("substituir_afiliados", self._f_aff),
                          ("exigir_afiliado", self._f_exigir), ("somente_ofertas", self._f_ofertas),
                          ("sem_repetidas", self._f_dedup)]:
            if filtros.get(chave):
                cb.select()
        self._termos_bloquear.insert(0, r["termos_bloquear"] or "")
        self._termos_permitir.insert(0, r["termos_permitir"] or "")
        self._subs = json.loads(r["substituicoes"] or "[]")
        for campo, valor in [(self._delay, r["delay"] or 1), (self._limite, r["limite_diario"] or 0),
                             (self._h_ini, r["horario_inicio"] or "00:00"), (self._h_fim, r["horario_fim"] or "00:00")]:
            campo.delete(0, "end")
            campo.insert(0, str(valor))

    # ── Origens / destinos ────────────────────────────────────────────────────

    def _conta_id(self):
        cid = self._conta_map.get(self._conta_var.get())
        if not cid:
            messagebox.showwarning("Aviso", "Cadastre e selecione uma conta.", parent=self)
        elif cid not in telegram_manager.clients:
            messagebox.showwarning("Aviso", "Conta não conectada. Conecte em 'Contas' primeiro.", parent=self)
            cid = None
        return cid

    def _escolher_origens(self):
        cid = self._conta_id()
        if cid:
            SeletorChats(self, cid, "Origens do repasse", self._set_origens,
                         selecionados=[o["origem_id"] for o in self._origens])

    def _escolher_destinos(self):
        cid = self._conta_id()
        if cid:
            SeletorChats(self, cid, "Destinos do repasse", self._set_destinos,
                         selecionados=[d["grupo_id"] for d in self._destinos], atalho_promo=False)

    def _set_origens(self, chats):
        self._origens = [{"origem_id": c["id"], "origem_nome": c["nome"]} for c in chats]
        self._render_listas()

    def _set_destinos(self, chats):
        self._destinos = [{"grupo_id": c["id"], "grupo_nome": c["nome"]} for c in chats]
        self._render_listas()

    def _render_listas(self):
        def resumo(nomes):
            if not nomes:
                return "Nenhum selecionado"
            return "\n".join(f"• {n[:40]}" for n in nomes[:6]) + (f"\n… e mais {len(nomes) - 6}" if len(nomes) > 6 else "")
        self._lbl_origens.configure(text=resumo([o["origem_nome"] for o in self._origens]))
        self._lbl_destinos.configure(text=resumo([d["grupo_nome"] for d in self._destinos]))
        self._render_subs()

    # ── Substituições ─────────────────────────────────────────────────────────

    def _add_sub(self):
        busca = self._sub_busca.get().strip()
        if not busca:
            messagebox.showwarning("Aviso", "Informe o texto a buscar.", parent=self)
            return
        self._subs.append({"busca": busca, "substituir": self._sub_rep.get().strip()})
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
            ctk.CTkLabel(self._sub_list, text="Nenhuma substituição", font=F_PEQUENA,
                         text_color=TEXTO_SEC).pack(anchor="w")
        for i, s in enumerate(self._subs):
            row = ctk.CTkFrame(self._sub_list, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=f'"{s["busca"]}" → "{s["substituir"]}"', font=F_PEQUENA).pack(side="left")
            botao(row, "✕", lambda idx=i: self._remove_sub(idx), "vermelho", 30).pack(side="right")

    # ── Salvar ────────────────────────────────────────────────────────────────

    def _save(self):
        nome = self._nome.get().strip()
        conta_id = self._conta_map.get(self._conta_var.get())
        if not nome or not conta_id:
            messagebox.showwarning("Aviso", "Informe o nome e a conta.", parent=self)
            return
        if not self._origens:
            messagebox.showwarning("Aviso", "Escolha pelo menos uma origem.", parent=self)
            return
        try:
            delay, limite = int(self._delay.get() or 1), int(self._limite.get() or 0)
        except ValueError:
            messagebox.showwarning("Aviso", "Espera e limite devem ser números.", parent=self)
            return
        h_ini, h_fim = self._h_ini.get().strip() or "00:00", self._h_fim.get().strip() or "00:00"
        if not all(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", h) for h in (h_ini, h_fim)):
            messagebox.showwarning("Aviso", "Horários no formato HH:MM.", parent=self)
            return

        filtros = {"links": bool(self._f_links.get()), "imagens": bool(self._f_img.get()),
                   "videos": bool(self._f_vid.get()), "audios": bool(self._f_aud.get()),
                   "substituir_afiliados": bool(self._f_aff.get()), "exigir_afiliado": bool(self._f_exigir.get()),
                   "somente_ofertas": bool(self._f_ofertas.get()), "sem_repetidas": bool(self._f_dedup.get())}
        dados = {"descricao": nome, "conta_id": conta_id,
                 "origem_id": self._origens[0]["origem_id"], "origem_nome": self._origens[0]["origem_nome"],
                 "filtros": json.dumps(filtros), "substituicoes": json.dumps(self._subs),
                 "delay": delay, "limite_diario": limite, "horario_inicio": h_ini, "horario_fim": h_fim,
                 "termos_bloquear": self._termos_bloquear.get().strip(),
                 "termos_permitir": self._termos_permitir.get().strip()}

        rid = self._rid
        if rid:
            db.atualizar_repasse(rid, dados)
        else:
            rid = db.adicionar_repasse(dados)
        db.set_origens(rid, self._origens)
        db.set_destinos(rid, self._destinos)

        # Aplica na hora: reinicia o repasse (novas origens) e o ouvinte do radar
        r = db.get_repasse(rid)
        if r and r["ativo"]:
            telegram_manager.iniciar_repasse(rid)
        telegram_manager.atualizar_radar(conta_id)
        self.destroy()
        if self._ao_salvar:
            self._ao_salvar()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _secao(parent, titulo: str):
    c = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDA)
    c.pack(fill="x", padx=16, pady=(12, 0))
    ctk.CTkLabel(c, text=titulo, font=F_SUBTITULO).pack(anchor="w", padx=14, pady=(10, 8))
    return c


def _campo(parent, rotulo: str, padrao: str):
    ctk.CTkLabel(parent, text=rotulo, font=F_PEQUENA).pack(side="left", padx=(0, 4))
    e = ctk.CTkEntry(parent, width=64, height=30)
    e.insert(0, padrao)
    e.pack(side="left", padx=(0, 14))
    return e
