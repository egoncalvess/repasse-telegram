"""
Configurações em seções verticais: Telegram, Bot, Fontes, Aparência, Inicialização e Dados.
Rede sempre fora da thread da interface; o resultado volta por after().
"""
import webbrowser

import customtkinter as ctk
from tkinter import messagebox

import database as db
from ui import estilo as e
from ui.fundo import em_segundo_plano

TEMAS = {"Claro": "light", "Escuro": "dark", "Sistema": "system"}


class ConfiguracoesFrame(ctk.CTkFrame):
    def __init__(self, parent, app=None):
        super().__init__(parent, corner_radius=0, fg_color=e.FUNDO)
        self._app = app
        e.cabecalho(self, "Configurações")
        self._area = e.area_rolavel(self)
        self._area.pack(fill="both", expand=True, padx=(0, e.E1))
        self._fontes_ui: dict[str, dict] = {}
        self._build_telegram()
        self._build_bot()
        self._build_fontes()
        self._build_aparencia()
        self._build_inicializacao()
        self._build_dados()

    def _em_segundo_plano(self, trabalho, ao_terminar):
        em_segundo_plano(self, trabalho, ao_terminar)

    # ── Telegram ─────────────────────────────────────────────────────────────

    def _build_telegram(self):
        sec = e.secao(self._area, "Telegram", linha=False)
        e.paragrafo(sec, "Credenciais da API do Telegram, obtidas em my.telegram.org → API development tools. "
                      "A API Hash dá acesso total à conta: não compartilhe.", pady=(0, e.E2))
        self._api_id = e.campo(sec, "API ID", db.get_config("api_id") or "", dica="1234567")
        self._api_hash = e.campo(sec, "API Hash", db.get_config("api_hash") or "", oculto=True)
        self._phone = e.campo(sec, "Telefone padrão (opcional)", db.get_config("phone_default") or "",
                              dica="+5571999999999")
        linha = ctk.CTkFrame(sec, fg_color="transparent")
        linha.pack(anchor="w")
        e.botao(linha, "Salvar", self._save_api).pack(side="left")
        self._api_res = e.rotulo(linha, "", e.F_LEGENDA, secundario=True)
        self._api_res.pack(side="left", padx=(e.E2, 0))

    def _save_api(self):
        api_id, api_hash, phone = self._api_id.get().strip(), self._api_hash.get().strip(), self._phone.get().strip()
        if not api_id or not api_hash:
            messagebox.showwarning("Telegram", "Preencha API ID e API Hash.", parent=self)
            return
        if not api_id.isdigit():
            messagebox.showwarning("Telegram", "O API ID tem só números. Copie de novo em my.telegram.org.",
                                   parent=self)
            return
        db.set_config("api_id", api_id)
        db.set_config("api_hash", api_hash)
        if phone:
            db.set_config("phone_default", phone)
        self._api_res.configure(text="Salvo.")

    # ── Bot ──────────────────────────────────────────────────────────────────

    def _build_bot(self):
        sec = e.secao(self._area, "Bot")
        e.paragrafo(sec, "Crie o bot no @BotFather e adicione-o como administrador dos grupos e canais de destino. Com o "
                      "bot configurado, tudo é publicado por ele; a conta só lê os canais onde o bot não entra. "
                      "Para o bot ler uma origem sozinho, adicione-o a ela (em canal, como administrador).", pady=(0, e.E2))
        self._bot_token = e.campo(sec, "Token do bot", db.get_config("bot_token") or "", oculto=True,
                                  dica="123456789:AA…")
        self._bot_admin = e.campo(sec, "Seu ID de usuário (admin do painel)", db.get_config("bot_admin_id") or "",
                                  dica="Mande /start ao bot: ele responde com o seu ID")
        linha = ctk.CTkFrame(sec, fg_color="transparent")
        linha.pack(anchor="w", pady=(0, e.E2))
        e.botao(linha, "Salvar e conectar", self._save_bot).pack(side="left")
        self._bot_status = e.ponto_status(linha, "inativo", "", fonte=e.F_CORPO)
        self._bot_status.pack(side="left", padx=(e.E2, 0))

        teste = ctk.CTkFrame(sec, fg_color="transparent")
        teste.pack(anchor="w")
        self._bot_teste_dest = e.campo(teste, "Testar publicação em (ID do canal ou grupo)",
                                       db.get_config("radar_destino") or "", largura=200, dica="-100…",
                                       side="left", fill=None, padx=(0, e.E1))
        e.botao(teste, "Enviar mensagem de teste", self._testar_bot).pack(side="left", anchor="s", pady=(0, e.E2))
        self._bot_teste_res = e.rotulo(sec, "", e.F_LEGENDA, wraplength=640)
        self._bot_teste_res.pack(anchor="w")
        self._atualizar_bot()

    def _atualizar_bot(self, estado=None, texto=None):
        from telegram_manager import telegram_manager
        if estado is None:
            if telegram_manager.bot:
                estado, texto = "ok", "Bot conectado"
            elif (db.get_config("bot_token") or "").strip():
                estado, texto = "falha", "Bot desconectado"
            else:
                estado, texto = "inativo", "Sem bot: os repasses saem pela conta"
        self._bot_status.atualizar(estado, texto)

    def _testar_bot(self):
        from telegram_manager import telegram_manager
        dest = self._bot_teste_dest.get().strip()
        self._bot_teste_res.configure(text_color=e.TINTA_2)
        if not dest:
            self._bot_teste_res.configure(text="Informe o ID do canal ou grupo.")
            return
        if not telegram_manager.via_bot():
            self._bot_teste_res.configure(text="O bot não está conectado. Salve o token e conecte.", text_color=e.ERRO)
            return
        self._bot_teste_res.configure(text="Enviando…")
        texto = "✅ <b>Teste do bot</b>\nSe você está vendo esta mensagem, o bot consegue publicar aqui."
        fut = telegram_manager._run(telegram_manager.enviar(None, dest, texto, html=True))

        def _fim(_, err):
            if err:
                self._bot_teste_res.configure(text=f"Não publicou: {err}", text_color=e.ERRO)
            else:
                self._bot_teste_res.configure(text="Publicado. Confira no canal ou grupo (pode apagar a mensagem "
                                                   "de teste).", text_color=e.TINTA_2)
        self._em_segundo_plano(lambda: fut.result(timeout=90), _fim)

    def _save_bot(self):
        token, admin = self._bot_token.get().strip(), self._bot_admin.get().strip()
        if token and ":" not in token:
            messagebox.showwarning("Bot", "Token inválido. Copie o token completo do @BotFather.", parent=self)
            return
        if admin and not admin.isdigit():
            messagebox.showwarning("Bot", "O ID do admin tem só números. Mande /start ao bot para ver o seu.",
                                   parent=self)
            return
        db.set_config("bot_token", token)
        db.set_config("bot_admin_id", admin)
        if not token:
            self._atualizar_bot()
            return
        self._atualizar_bot("inativo", "Conectando…")
        from telegram_manager import telegram_manager

        def cb(username, error):
            if error:
                self.after(0, lambda: self._atualizar_bot("falha", f"Não conectou: {error}"))
            else:
                self.after(0, lambda: self._atualizar_bot("ok", f"@{username} conectado. Mande /start para ele."))

        telegram_manager.iniciar_bot(cb)

    # ── Fontes de busca ──────────────────────────────────────────────────────

    def _build_fontes(self):
        import fontes
        sec = e.secao(self._area, "Fontes")
        e.paragrafo(sec, "De onde o app busca ofertas sozinho. Só APIs oficiais; uma fonte que recusa acesso pausa e "
                      "avisa o admin.", pady=(0, e.E2))
        for f in fontes.registro().values():
            self._bloco_fonte(sec, f)

    def _bloco_fonte(self, sec, f):
        import fontes
        ui = {}
        topo = ctk.CTkFrame(sec, fg_color="transparent")
        topo.pack(fill="x", pady=(0, e.E2))
        e.rotulo(topo, f.nome, e.F_CORPO_FORTE).pack(side="left")
        ativa = ctk.BooleanVar(value=fontes.ativa(f.id))
        e.interruptor(topo, "Usar nas buscas automáticas", ativa,
                      lambda: (fontes.definir_ativa(f.id, ativa.get()), self._atualizar_fonte(f))).pack(
            side="left", padx=(e.E3, 0))

        if f.id == "ml":
            from fontes.mercadolivre import REDIRECT_PADRAO
            e.paragrafo(sec, "App do DevCenter do Mercado Livre: em Fluxos OAuth, marque Authorization Code e Refresh "
                          "Token; a URL de redirecionamento precisa ser igual à cadastrada lá.", pady=(0, e.E2))
            ui["cid"] = e.campo(sec, "Client ID", db.get_config("ml_client_id") or "")
            ui["sec"] = e.campo(sec, "Client Secret", db.get_config("ml_client_secret") or "", oculto=True)
            ui["redirect"] = e.campo(sec, "URL de redirecionamento",
                                     db.get_config("ml_redirect_uri") or REDIRECT_PADRAO)
            e.rotulo(sec, "1. Conectar abre o login do Mercado Livre no navegador; autorize com a conta dona do app.\n"
                          "2. Copie a URL inteira da barra de endereço (termina com ?code=…), cole abaixo e confirme.",
                     e.F_LEGENDA, secundario=True).pack(anchor="w", pady=(0, e.E1))
            linha = ctk.CTkFrame(sec, fg_color="transparent")
            linha.pack(anchor="w", pady=(0, e.E2))
            e.botao(linha, "Conectar", lambda: self._ml_conectar(f)).pack(side="left")
            ui["retorno"] = e.entrada(linha, 280, placeholder_text="https://www.google.com/?code=TG-…")
            ui["retorno"].pack(side="left", padx=e.E1)
            e.botao(linha, "Confirmar", lambda: self._ml_confirmar(f)).pack(side="left")

        acoes = ctk.CTkFrame(sec, fg_color="transparent")
        acoes.pack(anchor="w", pady=(0, e.E1))
        e.botao(acoes, "Testar", lambda: self._testar_fonte(f)).pack(side="left")
        if hasattr(f, "desconectar"):
            e.botao_texto(acoes, "Desconectar", lambda: self._desconectar_fonte(f), perigo=True).pack(
                side="left", padx=(e.E1, 0))
        ui["status"] = e.ponto_status(sec, "inativo", "", fonte=e.F_CORPO)
        ui["status"].pack(anchor="w", pady=(e.E1, e.E1))
        ui["endpoints"] = ctk.CTkFrame(sec, fg_color="transparent")
        ui["endpoints"].pack(anchor="w", fill="x", pady=(0, e.E2))
        self._fontes_ui[f.id] = ui
        self._atualizar_fonte(f)

    def _atualizar_fonte(self, f, texto=None, estado=None):
        import fontes
        ui = self._fontes_ui[f.id]
        if texto is None:
            pausa = fontes.pausada(f.id)
            conectado = f.conectado() if hasattr(f, "conectado") else True
            if pausa:
                estado, texto = "falha", f"Pausada: {pausa}"
            elif not conectado:
                estado, texto = "inativo", "Não conectado"
            elif f.id == "ml" and not db.get_config("ml_refresh_token"):
                estado, texto = "falha", ("Conectado por até 6 horas: sem refresh token. Marque Refresh Token nos "
                                          "Fluxos OAuth do app e conecte de novo.")
            else:
                estado, texto = ("ok", "Conectado") if fontes.ativa(f.id) else ("inativo", "Conectado, desligado")
        ui["status"].atualizar(estado or "inativo", texto)
        for w in ui["endpoints"].winfo_children():
            w.destroy()
        for ep, s in sorted(db.endpoints_da_fonte(f.id).items()):
            ok = s["status"] == "ok"
            e.ponto_status(ui["endpoints"], "ok" if ok else "falha",
                           ep if ok else f"{ep}: bloqueado ({(s['detalhe'] or '')[:80]})").pack(anchor="w", pady=2)

    def _ml_salvar(self) -> bool:
        ui = self._fontes_ui["ml"]
        cid, sec, redirect = ui["cid"].get().strip(), ui["sec"].get().strip(), ui["redirect"].get().strip()
        if not cid or not sec:
            messagebox.showwarning("Mercado Livre", "Preencha Client ID e Client Secret do app do Mercado Livre.",
                                   parent=self)
            return False
        if not redirect.startswith("https://"):
            messagebox.showwarning("Mercado Livre", "A URL de redirecionamento precisa começar com https://.",
                                   parent=self)
            return False
        db.set_config("ml_client_id", cid)
        db.set_config("ml_client_secret", sec)
        db.set_config("ml_redirect_uri", redirect)
        return True

    def _ml_conectar(self, f):
        if self._ml_salvar():
            webbrowser.open(f.url_autorizacao())
            self._atualizar_fonte(f, "Aguardando a URL de retorno do navegador.", "inativo")

    def _ml_confirmar(self, f):
        if not self._ml_salvar():
            return
        ui = self._fontes_ui["ml"]
        retorno = ui["retorno"].get().strip()
        self._atualizar_fonte(f, "Conectando…", "inativo")

        def _fim(_, err):
            ui["retorno"].delete(0, "end")
            if err:
                self._atualizar_fonte(f, f"Não conectou: {err}", "falha")
            else:
                self._testar_fonte(f)
        self._em_segundo_plano(lambda: f.conectar(retorno), _fim)

    def _testar_fonte(self, f):
        self._atualizar_fonte(f, "Testando cada endpoint (uma chamada por endpoint)…", "inativo")

        def _fim(res, err):
            if err:
                self._atualizar_fonte(f, f"O teste falhou: {err}", "falha")
            else:
                self._atualizar_fonte(f, res["mensagem"], "ok" if res["ok"] else "falha")
        self._em_segundo_plano(f.testar, _fim)

    def _desconectar_fonte(self, f):
        if messagebox.askyesno("Desconectar", f"Desconectar {f.nome}? As buscas nessa fonte param até conectar de "
                                              "novo.", parent=self):
            f.desconectar()
            self._atualizar_fonte(f)

    # ── Aparência ────────────────────────────────────────────────────────────

    def _build_aparencia(self):
        sec = e.secao(self._area, "Aparência")
        atual = db.get_config("theme", "dark")
        self._tema = ctk.StringVar(value=next((k for k, v in TEMAS.items() if v == atual), "Escuro"))
        e.segmentado(sec, list(TEMAS), self._tema, self._mudar_tema).pack(anchor="w")

    def _mudar_tema(self, nome: str):
        db.set_config("theme", TEMAS[nome])
        e.aplicar_tema(TEMAS[nome])

    # ── Inicialização ────────────────────────────────────────────────────────

    def _build_inicializacao(self):
        import inicializacao
        sec = e.secao(self._area, "Inicialização")
        self._auto_var = ctk.BooleanVar(value=inicializacao.ativo())

        def _alternar_auto():
            try:
                inicializacao.ativar() if self._auto_var.get() else inicializacao.desativar()
            except Exception as ex:
                self._auto_var.set(inicializacao.ativo())
                messagebox.showerror("Inicialização", f"Não foi possível alterar a abertura com o Windows: {ex}",
                                     parent=self)
        e.interruptor(sec, "Abrir junto com o Windows (minimizado, sem precisar de administrador)", self._auto_var,
                      _alternar_auto).pack(anchor="w", pady=(0, e.E1))
        self._min_var = ctk.BooleanVar(value=db.get_config("start_minimized", "0") == "1")
        e.interruptor(sec, "Iniciar minimizado", self._min_var,
                      lambda: db.set_config("start_minimized", "1" if self._min_var.get() else "0")).pack(anchor="w")

    # ── Dados ────────────────────────────────────────────────────────────────

    def _build_dados(self):
        sec = e.secao(self._area, "Dados")
        e.paragrafo(sec, "Banco local em data/repasse.db, com cópia diária em data/backups (as 7 mais recentes).", pady=(0, e.E2))
        e.botao(sec, "Abrir o banco de dados", self._abrir_banco).pack(anchor="w")
        e.rotulo(sec, "PROMO DO BAIANO — Repasse & Radar · versão 1.0.0", e.F_LEGENDA, secundario=True).pack(
            anchor="w", pady=(e.E3, 0))

    def _abrir_banco(self):
        if self._app is not None:
            self._app.show_frame("banco")

    def refresh(self):
        import fontes
        self._atualizar_bot()
        for f in fontes.registro().values():
            if f.id in self._fontes_ui:
                self._atualizar_fonte(f)
