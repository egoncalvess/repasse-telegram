"""
Ofertas (antigo Radar de Preços): tudo o que teve preço hoje, de canais e de buscas, com filtros por loja e
origem; canais monitorados, importação de histórico e o bloco de publicação automática (piloto).
"""
import re

import customtkinter as ctk
from tkinter import messagebox

import database as db
from ui import estilo as e
from ui.fundo import em_segundo_plano
from ui.painel_frame import COLUNAS_OFERTAS, linha_oferta

TODAS = "Todas"
ORIGENS = {TODAS: None, "Canais": "canal", "Buscas": "fonte"}
MODOS = {"Automático": "automatico", "Com aprovação": "aprovacao"}


class OfertasFrame(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, corner_radius=0, fg_color=e.FUNDO)
        self._app = app
        self._itens: list[dict] = []

        acoes = e.cabecalho(self, "Ofertas")
        e.acao(acoes, e.botao(acoes, "Canais do radar", self._fontes))
        self._dias = ctk.StringVar(value="30 dias")
        e.acao(acoes, e.menu(acoes, self._dias, ["7 dias", "30 dias", "90 dias"], largura=96))
        self._btn_importar = e.acao(acoes, e.botao(acoes, "Importar histórico", self._importar))

        # Publicação automática (fica embaixo; a lista ocupa o resto)
        self._build_piloto()

        filtros = ctk.CTkFrame(self, fg_color="transparent")
        filtros.pack(fill="x", padx=e.MARGEM, pady=(0, e.E2))
        e.rotulo(filtros, "Loja", e.F_LEGENDA, secundario=True).pack(side="left", padx=(0, e.E1))
        self._loja = ctk.StringVar(value=TODAS)
        self._menu_loja = e.menu(filtros, self._loja, [TODAS], lambda _: self._render(), largura=160)
        self._menu_loja.pack(side="left", padx=(0, e.E2))
        e.rotulo(filtros, "Origem", e.F_LEGENDA, secundario=True).pack(side="left", padx=(0, e.E1))
        self._origem = ctk.StringVar(value=TODAS)
        e.menu(filtros, self._origem, list(ORIGENS), lambda _: self._render(), largura=120).pack(side="left")
        self._contagem = e.rotulo(filtros, "", e.F_LEGENDA, secundario=True)
        self._contagem.pack(side="right")

        lista = ctk.CTkFrame(self, fg_color="transparent")
        lista.pack(fill="both", expand=True, padx=e.MARGEM, pady=(0, e.E3))
        self._tabela = e.Tabela(lista, COLUNAS_OFERTAS)
        self._tabela.ao_selecionar(self._app.abrir_detalhe)
        self._tabela.pack(fill="both", expand=True)
        self._vazio = e.estado_vazio(lista, "Nenhuma oferta com preço hoje. Escolha canais do radar ou crie uma "
                                            "busca.", "Canais do radar", self._fontes)

    def _build_piloto(self):
        bloco = e.secao(self, "Publicação automática", side="bottom")
        topo = ctk.CTkFrame(bloco, fg_color="transparent")
        topo.pack(fill="x", pady=(0, e.E2))
        self._piloto = ctk.BooleanVar(value=db.get_config("piloto_ativo", "0") == "1")
        e.interruptor(topo, "Ligada", self._piloto).pack(side="left", padx=(0, e.E3))
        self._modo = ctk.StringVar(value=self._nome_modo())
        e.segmentado(topo, list(MODOS), self._modo).pack(side="left")

        grade = ctk.CTkFrame(bloco, fg_color="transparent")
        grade.pack(fill="x")
        self._campos = {}
        for i, (chave, titulo, padrao, largura) in enumerate([
                ("radar_destino", "Publicar em (ID)", "", 160), ("piloto_intervalo_min", "A cada (min)", "30", 96),
                ("piloto_max_dia", "Máximo por dia", "10", 96), ("piloto_inicio", "Das", "08:00", 80),
                ("piloto_fim", "Às", "22:00", 80)]):
            caixa = ctk.CTkFrame(grade, fg_color="transparent")
            caixa.grid(row=0, column=i, sticky="w", padx=(0, e.E2))
            self._campos[chave] = e.campo(caixa, titulo, db.get_config(chave) or padrao, largura=largura,
                                          pady=(0, 0))
        e.botao(grade, "Salvar", self._salvar).grid(row=0, column=5, sticky="sw")
        self._status = e.rotulo(bloco, "", e.F_LEGENDA, secundario=True)
        self._status.pack(anchor="w", pady=(e.E1, 0))

    @staticmethod
    def _nome_modo():
        modo = db.get_config("piloto_modo", "automatico")
        return next((k for k, v in MODOS.items() if v == modo), "Automático")

    # ── Dados ────────────────────────────────────────────────────────────────

    def refresh(self):
        self._piloto.set(db.get_config("piloto_ativo", "0") == "1")  # pode mudar pelo painel do bot
        self._modo.set(self._nome_modo())
        self._status.configure(text="Última rodada: " + (db.get_config("piloto_status") or "nenhuma ainda"))

        def _ler():
            fora = db.descartados()
            return [p for p in db.menores_precos_do_dia(limit=5000) if p["chave"] not in fora]
        em_segundo_plano(self, _ler, lambda itens, err: self._carregado(err or itens))

    def _carregado(self, itens):
        if not self.winfo_exists():
            return
        if isinstance(itens, Exception):
            self._contagem.configure(text=f"Não foi possível ler o banco: {itens}")
            return
        self._itens = itens
        self._menu_loja.configure(values=[TODAS] + sorted({p["loja"] for p in itens}))
        self._render()

    def _render(self):
        loja, origem = self._loja.get(), ORIGENS.get(self._origem.get())
        vis = [p for p in self._itens if (loja == TODAS or p["loja"] == loja) and
               (origem is None or ((p.get("origem") or "").startswith("fonte:")) == (origem == "fonte"))]
        self._contagem.configure(text=f"{len(vis)} de {len(self._itens)}")
        if vis:
            self._vazio.pack_forget()
            self._tabela.pack(fill="both", expand=True)
            self._tabela.carregar([linha_oferta(p) for p in vis], ids=[p["chave"] for p in vis])
        else:
            self._tabela.pack_forget()
            self._vazio.pack(anchor="w", pady=(e.E1, 0))

    def limpar_selecao(self):
        self._tabela.selecionar(None)

    # ── Publicação automática ────────────────────────────────────────────────

    def _salvar(self):
        v = {k: ent.get().strip() for k, ent in self._campos.items()}
        if not (v["piloto_intervalo_min"].isdigit() and int(v["piloto_intervalo_min"]) >= 5):
            messagebox.showwarning("Publicação automática", "O intervalo precisa ser de 5 minutos ou mais.", parent=self)
            return
        if not v["piloto_max_dia"].isdigit():
            messagebox.showwarning("Publicação automática", "Informe o máximo por dia como número inteiro.",
                                   parent=self)
            return
        if not all(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v[k]) for k in ("piloto_inicio", "piloto_fim")):
            messagebox.showwarning("Publicação automática", "Use horários no formato HH:MM, como 08:00.", parent=self)
            return
        if self._piloto.get() and not v["radar_destino"]:
            messagebox.showwarning("Publicação automática", "Informe o ID do canal ou grupo em Publicar em.",
                                   parent=self)
            return
        for k, val in v.items():
            db.set_config(k, val)
        db.set_config("piloto_ativo", "1" if self._piloto.get() else "0")
        db.set_config("piloto_modo", MODOS[self._modo.get()])
        self._status.configure(text="Salvo.")

    # ── Canais do radar ──────────────────────────────────────────────────────

    def _fontes(self):
        from telegram_manager import telegram_manager
        conta_id = next(iter(telegram_manager.clients), None)
        if not conta_id:
            messagebox.showwarning("Canais do radar", "Conecte uma conta em Contas para escolher os canais.",
                                   parent=self)
            return
        from ui.seletor_chats import SeletorChats

        def salvar(chats):
            db.set_fontes(conta_id, [{"chat_id": c["id"], "nome": c["nome"]} for c in chats])
            telegram_manager.atualizar_radar(conta_id)
            self.refresh()
            if chats and messagebox.askyesno("Canais do radar", f"{len(chats)} canais no radar.\n\n"
                                             "Importar o histórico deles agora?", parent=self):
                self._importar()

        atuais = [f["chat_id"] for f in db.listar_fontes() if f["conta_id"] == conta_id]
        SeletorChats(self, conta_id, "Canais do radar (só monitorar preços)", salvar, selecionados=atuais)

    def _importar(self):
        from telegram_manager import telegram_manager
        dias = int(self._dias.get().split()[0])
        self._btn_importar.configure(state="disabled", text="Importando")
        self._contagem.configure(text="Lendo o histórico dos canais. Pode levar alguns minutos; mantenha o app aberto.")

        def progresso(txt):
            self.after(0, lambda: self._contagem.configure(text=txt))

        def concluido(res, err):
            def _ui():
                self._btn_importar.configure(state="normal", text="Importar histórico")
                self.refresh()
                if err:
                    messagebox.showerror("Importar histórico", f"A importação parou: {err}", parent=self)
                else:
                    messagebox.showinfo("Importar histórico", res, parent=self)
            self.after(0, _ui)

        telegram_manager.importar_historico(dias, concluido, progresso)
