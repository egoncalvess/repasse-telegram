"""
Radar de Preços: produtos vistos nos canais monitorados, comparados ao próprio histórico.
Fontes (canais só monitorados), importação de histórico, piloto automático e publicação.
"""
import re
import threading
import customtkinter as ctk
from tkinter import messagebox

import database as db
from oferta import brl, selo, publicar_oferta
from ui.estilo import Tabela, botao, cabecalho, card, FUNDO, F_NORMAL, F_PEQUENA, F_SUBTITULO, TEXTO_SEC


class RadarFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, corner_radius=0, fg_color=FUNDO)
        acoes = cabecalho(self, "Radar de Preços", "Preços reais lidos das ofertas dos canais monitorados")
        botao(acoes, "📡 Fontes do radar", self._fontes, "cinza", 150).pack(side="left", padx=4)
        self._dias = ctk.StringVar(value="30 dias")
        ctk.CTkOptionMenu(acoes, variable=self._dias, values=["7 dias", "30 dias", "90 dias"],
                          width=95, height=34).pack(side="left", padx=4)
        self._btn_importar = botao(acoes, "📥 Importar histórico", self._importar, "azul", 165)
        self._btn_importar.pack(side="left", padx=4)
        botao(acoes, "↻", self.refresh, "cinza", 40).pack(side="left", padx=4)

        self._resumo = ctk.CTkLabel(self, text="", font=F_PEQUENA, text_color=TEXTO_SEC)
        self._resumo.pack(anchor="w", padx=24, pady=(0, 6))

        # Destino + piloto automático
        cfg = card(self)
        cfg.grid_columnconfigure(9, weight=1)
        ctk.CTkLabel(cfg, text="Publicar em", font=F_NORMAL).grid(row=0, column=0, padx=(14, 6), pady=10, sticky="w")
        self._destino = ctk.CTkEntry(cfg, width=170, placeholder_text="ID -100...", height=32)
        self._destino.insert(0, db.get_config("radar_destino") or "")
        self._destino.grid(row=0, column=1, sticky="w")
        self._piloto = ctk.BooleanVar(value=db.get_config("piloto_ativo", "0") == "1")
        ctk.CTkSwitch(cfg, text="🤖 Piloto automático", variable=self._piloto,
                      font=(F_NORMAL[0], 12, "bold")).grid(row=0, column=2, padx=(20, 8))
        self._pil_campos = {}
        col = 3
        for chave, rotulo, padrao, w in [("piloto_intervalo_min", "a cada (min)", "30", 48),
                                         ("piloto_max_dia", "máx/dia", "10", 44),
                                         ("piloto_inicio", "das", "08:00", 58), ("piloto_fim", "às", "22:00", 58)]:
            fr = ctk.CTkFrame(cfg, fg_color="transparent")
            fr.grid(row=0, column=col, padx=4)
            ctk.CTkLabel(fr, text=rotulo, font=F_PEQUENA).pack(side="left", padx=(0, 3))
            e = ctk.CTkEntry(fr, width=w, height=30)
            e.insert(0, db.get_config(chave) or padrao)
            e.pack(side="left")
            self._pil_campos[chave] = e
            col += 1
        botao(cfg, "Salvar", self._salvar_cfg, "azul", 80).grid(row=0, column=col, padx=(8, 14))
        self._pil_status = ctk.CTkLabel(cfg, text="", font=F_PEQUENA, text_color=TEXTO_SEC)
        self._pil_status.grid(row=1, column=0, columnspan=10, sticky="w", padx=14, pady=(0, 8))

        # Menores preços do dia
        lista = card(self, fill="both", expand=True)
        topo = ctk.CTkFrame(lista, fg_color="transparent")
        topo.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(topo, text="📉 Menores preços do dia", font=F_SUBTITULO).pack(side="left")
        botao(topo, "📤 Publicar selecionado", self._publicar, "azul", 180).pack(side="right")
        self._tabela = Tabela(lista, [("produto", "Produto", 9), ("loja", "Loja", 3), ("hoje", "Hoje", 2),
                                      ("media", "Média", 2), ("minimo", "Mín. anterior", 2), ("dias", "Dias", 1),
                                      ("destaque", "Destaque", 6)], altura=12)
        self._tabela.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._tabela.tree.bind("<Double-1>", lambda _: self._publicar())

    def refresh(self):
        r = db.resumo_radar()
        n_fontes = len(db.listar_fontes())
        self._resumo.configure(text=f"{r['produtos']} produtos monitorados · {r['precos_hoje']} preços hoje · "
                                    f"{n_fontes} fontes do radar + origens dos repasses ativos")
        self._piloto.set(db.get_config("piloto_ativo", "0") == "1")  # pode mudar pelo painel do bot
        self._pil_status.configure(text="Piloto — última rodada: " + (db.get_config("piloto_status") or "—"))
        itens = db.menores_precos_do_dia(limit=100)
        self._tabela.carregar(
            [(p["nome"], p["loja"], brl(p["preco_hoje"]), brl(p["media"]) if p["media"] else "—",
              brl(p["minimo"]) if p["minimo"] else "—", p["dias"],
              selo(p) or ("Novo no radar" if not p["dias"] else "")) for p in itens],
            ids=[p["chave"] for p in itens])

    # ── Fontes ────────────────────────────────────────────────────────────────

    def _fontes(self):
        from telegram_manager import telegram_manager
        conta_id = next(iter(telegram_manager.clients), None)
        if not conta_id:
            messagebox.showwarning("Aviso", "Conecte uma conta em 'Contas' primeiro.", parent=self)
            return
        from ui.seletor_chats import SeletorChats

        def salvar(chats):
            db.set_fontes(conta_id, [{"chat_id": c["id"], "nome": c["nome"]} for c in chats])
            telegram_manager.atualizar_radar(conta_id)
            self.refresh()
            if chats and messagebox.askyesno("Fontes salvas", f"{len(chats)} canais no radar.\n\n"
                                             "Importar o histórico deles agora?", parent=self):
                self._importar()

        atuais = [f["chat_id"] for f in db.listar_fontes() if f["conta_id"] == conta_id]
        SeletorChats(self, conta_id, "Fontes do radar (só monitorar preços)", salvar, selecionados=atuais)

    def _importar(self):
        from telegram_manager import telegram_manager
        dias = int(self._dias.get().split()[0])
        self._btn_importar.configure(state="disabled", text="Importando...")
        self._resumo.configure(text="Lendo histórico dos canais (pode levar alguns minutos; não feche o app)...")

        def progresso(txt):
            self.after(0, lambda: self._resumo.configure(text=txt))

        def concluido(res, err):
            def _ui():
                self._btn_importar.configure(state="normal", text="📥 Importar histórico")
                self.refresh()
                if err:
                    messagebox.showerror("Erro", f"Falha ao importar: {err}", parent=self)
                else:
                    messagebox.showinfo("Histórico importado", res, parent=self)
            self.after(0, _ui)

        telegram_manager.importar_historico(dias, concluido, progresso)

    # ── Configuração / publicação ─────────────────────────────────────────────

    def _salvar_cfg(self):
        v = {k: e.get().strip() for k, e in self._pil_campos.items()}
        if not (v["piloto_intervalo_min"].isdigit() and int(v["piloto_intervalo_min"]) >= 5
                and v["piloto_max_dia"].isdigit()
                and all(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v[k]) for k in ("piloto_inicio", "piloto_fim"))):
            messagebox.showwarning("Aviso", "Intervalo ≥ 5 min, máximo numérico e horários no formato HH:MM.", parent=self)
            return
        for k, val in v.items():
            db.set_config(k, val)
        db.set_config("radar_destino", self._destino.get().strip())
        db.set_config("piloto_ativo", "1" if self._piloto.get() else "0")
        if self._piloto.get() and not self._destino.get().strip():
            messagebox.showwarning("Aviso", "Informe o destino para o piloto publicar.", parent=self)
        self.refresh()

    def _publicar(self):
        chave = self._tabela.selecionado()
        destino = self._destino.get().strip()
        if not chave:
            messagebox.showwarning("Aviso", "Selecione um produto na lista.", parent=self)
            return
        if not destino:
            messagebox.showwarning("Aviso", "Informe o grupo/canal de destino.", parent=self)
            return
        from telegram_manager import telegram_manager
        conta_id = next(iter(telegram_manager.clients), None)

        def _worker():
            try:
                publicar_oferta(chave, conta_id, destino)
                self.after(0, lambda: messagebox.showinfo("Publicado", "Oferta publicada!", parent=self))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: messagebox.showerror("Erro", f"Falha ao publicar: {err}", parent=self))

        threading.Thread(target=_worker, daemon=True).start()
