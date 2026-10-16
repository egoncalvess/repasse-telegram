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
from ui import estilo as e
from ui.fundo import em_segundo_plano
from ui.seletor_chats import SeletorChats


class RepasseDialog(ctk.CTkToplevel):
    def __init__(self, parent, repasse_id: int | None, ao_salvar=None):
        super().__init__(parent)
        self._rid = repasse_id
        self._ao_salvar = ao_salvar
        self._origens: list[dict] = []   # {'origem_id', 'origem_nome'}
        self._destinos: list[dict] = []  # {'grupo_id', 'grupo_nome'}
        self._subs: list[dict] = []
        self._leitura: dict[str, str] = {}  # origem_id -> "bot" | "conta" | "sem acesso"

        r = db.get_repasse(repasse_id) if repasse_id else None
        e.janela(self, "Editar repasse" if r else "Novo repasse", 760, 720, parent)
        self.minsize(640, 520)

        self._build(r)
        if r:
            self._populate(r)
        self._render_listas()

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build(self, r):
        e.rodape_dialogo(self, "Salvar", self._save)
        main = e.area_rolavel(self, fundo=e.SUPERFICIE)
        main.pack(fill="both", expand=True, padx=(e.E3, e.E1), pady=(e.E3, 0))
        e.rotulo(main, "Editar repasse" if r else "Novo repasse", e.F_SECAO).pack(anchor="w", pady=(0, e.E2))

        self._nome = e.campo(main, "Nome", largura=480, dica="Ex.: Canais de promoção para o meu canal")
        contas = db.listar_contas()
        self._conta_map = {f"{c['apelido']} ({c['telefone']})": c["id"] for c in contas}
        opts = list(self._conta_map) or ["Nenhuma conta cadastrada"]
        e.rotulo(main, "Conta que lê as origens onde o bot não está", e.F_LEGENDA, secundario=True).pack(
            anchor="w", pady=(0, 4))
        self._conta_var = ctk.StringVar(value=opts[0])
        e.menu(main, self._conta_var, opts, largura=320).pack(anchor="w", pady=(0, e.E3))

        sec = e.secao(main, "Origens e destinos", padx=0)
        self._lbl_origens = self._bloco_lista(sec, "Origens", "Escolher origens", self._escolher_origens)
        e.paragrafo(sec, "O bot só lê grupos e canais onde foi adicionado (em canal, como administrador). As demais "
                      "origens são lidas pela conta, que nunca envia nada quando há bot.", pady=(0, e.E2))
        self._lbl_destinos = self._bloco_lista(sec, "Destinos", "Escolher destinos", self._escolher_destinos)

        sec = e.secao(main, "Ofertas e afiliação", padx=0)
        for attr, txt in [("_f_aff", "Trocar links pelos meus links de afiliado"),
                          ("_f_exigir", "Só repassar se todos os links virarem meus"),
                          ("_f_ofertas", "Somente ofertas (mensagem com link de loja)"),
                          ("_f_dedup", "Não repetir o mesmo produto em 24 horas")]:
            cb = e.caixa_marcar(sec, txt)
            cb.pack(anchor="w", pady=(0, e.E1))
            setattr(self, attr, cb)

        sec = e.secao(main, "Bloquear mensagens com", padx=0)
        fr = ctk.CTkFrame(sec, fg_color="transparent")
        fr.pack(anchor="w")
        for attr, txt in [("_f_links", "Links"), ("_f_img", "Imagens"), ("_f_vid", "Vídeos"), ("_f_aud", "Áudios")]:
            cb = e.caixa_marcar(fr, txt)
            cb.pack(side="left", padx=(0, e.E3))
            setattr(self, attr, cb)

        sec = e.secao(main, "Filtro por palavras", padx=0)
        self._termos_bloquear = e.campo(sec, "Bloquear se contiver (separe por vírgula)", largura=480,
                                        dica="patrocinado, sorteio")
        self._termos_permitir = e.campo(sec, "Repassar somente se contiver (separe por vírgula)", largura=480,
                                        dica="R$, desconto, cupom")

        sec = e.secao(main, "Substituições de texto", padx=0)
        fr = ctk.CTkFrame(sec, fg_color="transparent")
        fr.pack(anchor="w", pady=(0, e.E1))
        self._sub_busca = e.entrada(fr, 200, placeholder_text="Buscar")
        self._sub_busca.pack(side="left")
        e.rotulo(fr, "por", e.F_LEGENDA, secundario=True).pack(side="left", padx=e.E1)
        self._sub_rep = e.entrada(fr, 200, placeholder_text="Substituir por")
        self._sub_rep.pack(side="left")
        e.botao(fr, "Adicionar", self._add_sub).pack(side="left", padx=(e.E1, 0))
        self._sub_list = ctk.CTkFrame(sec, fg_color="transparent")
        self._sub_list.pack(fill="x")

        sec = e.secao(main, "Ritmo de envio", padx=0)
        fr = ctk.CTkFrame(sec, fg_color="transparent")
        fr.pack(anchor="w")
        campos = []
        for titulo, padrao in [("Intervalo entre envios (seg)", "1"), ("Limite por dia (0 = sem)", "0"),
                               ("Das", "00:00"), ("Até", "00:00")]:
            caixa = ctk.CTkFrame(fr, fg_color="transparent")
            caixa.pack(side="left", padx=(0, e.E2))
            campos.append(e.campo(caixa, titulo, padrao, largura=120 if len(campos) < 2 else 80, pady=(0, 0)))
        self._delay, self._limite, self._h_ini, self._h_fim = campos
        e.rotulo(sec, "00:00 até 00:00 = o dia todo", e.F_LEGENDA, secundario=True).pack(anchor="w", pady=(e.E1, 0))

    def _bloco_lista(self, parent, titulo, txt_botao, comando):
        caixa = ctk.CTkFrame(parent, fg_color="transparent")
        caixa.pack(fill="x", pady=(0, e.E2))
        topo = ctk.CTkFrame(caixa, fg_color="transparent")
        topo.pack(fill="x")
        e.rotulo(topo, titulo, e.F_CORPO_FORTE).pack(side="left")
        e.botao_texto(topo, txt_botao, comando).pack(side="right")
        lbl = e.rotulo(caixa, "", e.F_CORPO, secundario=True)
        lbl.pack(fill="x", pady=(4, 0))
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
        for campo, valor in [(self._delay, 1 if r["delay"] is None else r["delay"]), (self._limite, r["limite_diario"] or 0),
                             (self._h_ini, r["horario_inicio"] or "00:00"), (self._h_fim, r["horario_fim"] or "00:00")]:
            campo.delete(0, "end")
            campo.insert(0, str(valor))

    # ── Origens / destinos ────────────────────────────────────────────────────

    def _conta_id(self):
        cid = self._conta_map.get(self._conta_var.get())
        if not cid:
            messagebox.showwarning("Repasse", "Cadastre uma conta em Contas e selecione-a aqui.", parent=self)
        elif cid not in telegram_manager.clients:
            messagebox.showwarning("Repasse", "A conta está desconectada. Conecte-a em Contas para escolher os chats.", parent=self)
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
        self._render_origens()
        self._lbl_destinos.configure(text=_resumo([d["grupo_nome"] for d in self._destinos]))
        self._render_subs()
        self._verificar_leitura()

    def _render_origens(self):
        rotulos = {"bot": "Lida pelo bot", "conta": "Lida pela conta", "sem acesso": "Sem acesso"}
        self._lbl_origens.configure(text=_resumo([
            f"{o['origem_nome'][:32]} · {rotulos.get(self._leitura.get(str(o['origem_id'])), 'verificando…')}"
            for o in self._origens]))

    def _verificar_leitura(self):
        """Quem lê cada origem (bot ou conta): consulta no loop do Telegram, resposta via after()."""
        ids = [o["origem_id"] for o in self._origens if str(o["origem_id"]) not in self._leitura]
        if not ids:
            return

        def _volta(res, err):
            self._leitura.update(res if not err else {str(i): "sem acesso" for i in ids})
            self._render_origens()
        fut = telegram_manager._run(telegram_manager._leitura_origens(self._conta_map.get(self._conta_var.get()), ids))
        em_segundo_plano(self, lambda: fut.result(timeout=60), _volta)

    # ── Substituições ─────────────────────────────────────────────────────────

    def _add_sub(self):
        busca = self._sub_busca.get().strip()
        if not busca:
            messagebox.showwarning("Repasse", "Informe o texto a buscar.", parent=self)
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
            e.rotulo(self._sub_list, "Nenhuma substituição", e.F_LEGENDA, secundario=True).pack(anchor="w")
        for i, s in enumerate(self._subs):
            row = ctk.CTkFrame(self._sub_list, fg_color="transparent")
            row.pack(fill="x")
            e.rotulo(row, f'"{s["busca"]}" vira "{s["substituir"]}"', e.F_CORPO).pack(side="left")
            e.botao_texto(row, "Remover", lambda idx=i: self._remove_sub(idx), perigo=True).pack(side="left",
                                                                                                padx=(e.E1, 0))

    # ── Salvar ────────────────────────────────────────────────────────────────

    def _save(self):
        nome = self._nome.get().strip()
        conta_id = self._conta_map.get(self._conta_var.get())
        if not nome or not conta_id:
            messagebox.showwarning("Repasse", "Informe o nome e escolha a conta.", parent=self)
            return
        if not self._origens:
            messagebox.showwarning("Repasse", "Escolha pelo menos uma origem.", parent=self)
            return
        try:
            delay, limite = int(self._delay.get() or 1), int(self._limite.get() or 0)
            if delay < 0 or limite < 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Repasse", "Intervalo e limite precisam ser números inteiros, 0 ou mais.", parent=self)
            return
        h_ini, h_fim = self._h_ini.get().strip() or "00:00", self._h_fim.get().strip() or "00:00"
        if not all(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", h) for h in (h_ini, h_fim)):
            messagebox.showwarning("Repasse", "Use horários no formato HH:MM, como 08:00.", parent=self)
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

def _resumo(nomes: list[str]) -> str:
    if not nomes:
        return "Nenhum selecionado"
    return "\n".join(f"• {n[:60]}" for n in nomes[:6]) + (f"\n… e mais {len(nomes) - 6}" if len(nomes) > 6 else "")
