import customtkinter as ctk
from tkinter import messagebox
import database as db

BTN_BLUE = ("#1747a6", "#123a88")
BTN_GRAY = ("#64748b", "#4b5563")


class ConfiguracoesFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, corner_radius=0, fg_color=("#f4f6fb", "#0f1115"))
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="Configurações",
                     font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=24, pady=(20, 4))

        # ── Tabs ──────────────────────────────────────────────────────────────
        tab = ctk.CTkTabview(self, corner_radius=12)
        tab.pack(fill="both", expand=True, padx=16, pady=8)

        tab.add("API Telegram")
        tab.add("Bot")
        tab.add("Mercado Livre")
        tab.add("Geral")
        tab.add("Sobre")

        self._build_api_tab(tab.tab("API Telegram"))
        self._build_bot_tab(tab.tab("Bot"))
        self._build_ml_tab(tab.tab("Mercado Livre"))
        self._build_geral_tab(tab.tab("Geral"))
        self._build_sobre_tab(tab.tab("Sobre"))

    # ── API Telegram ──────────────────────────────────────────────────────────

    def _build_api_tab(self, parent):
        card = ctk.CTkFrame(parent, fg_color=("#ffffff", "#181b22"), corner_radius=12)
        card.pack(fill="both", expand=True, padx=8, pady=8)

        ctk.CTkLabel(card, text="Credenciais da API Telegram",
                     font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=20, pady=(20, 4))

        ctk.CTkLabel(card,
                     text="Obtenha em https://my.telegram.org → API development tools",
                     font=("Segoe UI", 11), text_color=("#64748b", "#94a3b8")).pack(anchor="w", padx=20)

        # API ID
        ctk.CTkLabel(card, text="API ID").pack(anchor="w", padx=20, pady=(16, 4))
        self._api_id = ctk.CTkEntry(card, width=400, placeholder_text="Ex: 1234567")
        self._api_id.pack(anchor="w", padx=20)
        val = db.get_config("api_id")
        if val:
            self._api_id.insert(0, val)

        # API Hash
        ctk.CTkLabel(card, text="API Hash").pack(anchor="w", padx=20, pady=(12, 4))
        self._api_hash = ctk.CTkEntry(card, width=400, placeholder_text="Ex: a1b2c3d4e5f6...", show="*")
        self._api_hash.pack(anchor="w", padx=20)
        val = db.get_config("api_hash")
        if val:
            self._api_hash.insert(0, val)

        # Phone (default)
        ctk.CTkLabel(card, text="Telefone padrão (opcional)").pack(anchor="w", padx=20, pady=(12, 4))
        self._phone = ctk.CTkEntry(card, width=400, placeholder_text="+55 11 99999-9999")
        self._phone.pack(anchor="w", padx=20)
        val = db.get_config("phone_default")
        if val:
            self._phone.insert(0, val)

        ctk.CTkButton(card, text="Salvar Credenciais", command=self._save_api,
                      fg_color=BTN_BLUE[0], hover_color=BTN_BLUE[1],
                      width=180).pack(anchor="w", padx=20, pady=20)

        # Aviso
        warn = ctk.CTkFrame(card, fg_color=("#fef3c7", "#2d251a"), corner_radius=8)
        warn.pack(fill="x", padx=20, pady=(0, 20))
        ctk.CTkLabel(warn,
                     text="⚠️  Nunca compartilhe sua API Hash. Ela dá acesso total à sua conta Telegram.",
                     font=("Segoe UI", 11), text_color=("#92400e", "#fcd34d"),
                     wraplength=600, justify="left").pack(padx=16, pady=10, anchor="w")

    def _save_api(self):
        api_id   = self._api_id.get().strip()
        api_hash = self._api_hash.get().strip()
        phone    = self._phone.get().strip()

        if not api_id or not api_hash:
            messagebox.showwarning("Aviso", "Preencha API ID e API Hash.")
            return
        if not api_id.isdigit():
            messagebox.showwarning("Aviso", "API ID deve ser numérico.")
            return

        db.set_config("api_id", api_id)
        db.set_config("api_hash", api_hash)
        if phone:
            db.set_config("phone_default", phone)

        messagebox.showinfo("Salvo", "Credenciais salvas com sucesso.")

    # ── Bot ───────────────────────────────────────────────────────────────────

    def _build_bot_tab(self, parent):
        card = ctk.CTkFrame(parent, fg_color=("#ffffff", "#181b22"), corner_radius=12)
        card.pack(fill="both", expand=True, padx=8, pady=8)

        ctk.CTkLabel(card, text="Bot de publicação e painel de controle",
                     font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=20, pady=(20, 4))
        ctk.CTkLabel(card,
                     text="Crie o bot no @BotFather e adicione-o como administrador dos grupos/canais de destino.\n"
                          "A conta continua só lendo as origens; quem publica é o bot (API oficial, sem risco de ban da conta).",
                     font=("Segoe UI", 11), text_color=("#64748b", "#94a3b8"), justify="left").pack(anchor="w", padx=20)

        ctk.CTkLabel(card, text="Token do bot").pack(anchor="w", padx=20, pady=(16, 4))
        self._bot_token = ctk.CTkEntry(card, width=400, placeholder_text="123456789:AA...", show="*")
        self._bot_token.pack(anchor="w", padx=20)
        self._bot_token.insert(0, db.get_config("bot_token") or "")

        ctk.CTkLabel(card, text="Seu ID de usuário (admin do painel)").pack(anchor="w", padx=20, pady=(12, 4))
        self._bot_admin = ctk.CTkEntry(card, width=400,
                                       placeholder_text="Mande /start ao bot: ele responde com o seu ID")
        self._bot_admin.pack(anchor="w", padx=20)
        self._bot_admin.insert(0, db.get_config("bot_admin_id") or "")

        self._via_bot = ctk.BooleanVar(value=db.get_config("publicar_via_bot", "1") == "1")
        ctk.CTkSwitch(card, text="Publicar pelo bot (desligado = publica pela conta, modo antigo)",
                      variable=self._via_bot).pack(anchor="w", padx=20, pady=(16, 0))

        ctk.CTkButton(card, text="Salvar e conectar bot", command=self._save_bot,
                      fg_color=BTN_BLUE[0], hover_color=BTN_BLUE[1],
                      width=200).pack(anchor="w", padx=20, pady=(20, 6))
        self._bot_status = ctk.CTkLabel(card, text=self._texto_status_bot(), font=("Segoe UI", 12))
        self._bot_status.pack(anchor="w", padx=20)

        # Teste real: o bot publica uma mensagem no destino (confirma que ele é admin do canal/grupo)
        teste = ctk.CTkFrame(card, fg_color="transparent")
        teste.pack(anchor="w", padx=20, pady=(16, 4))
        ctk.CTkLabel(teste, text="Testar publicação em (ID):").pack(side="left")
        self._bot_teste_dest = ctk.CTkEntry(teste, width=180, placeholder_text="-100...")
        self._bot_teste_dest.insert(0, db.get_config("radar_destino") or "")
        self._bot_teste_dest.pack(side="left", padx=8)
        ctk.CTkButton(teste, text="Enviar mensagem de teste", command=self._testar_bot,
                      fg_color=BTN_GRAY[0], hover_color=BTN_GRAY[1], width=180).pack(side="left")
        self._bot_teste_res = ctk.CTkLabel(card, text="", font=("Segoe UI", 12), wraplength=600, justify="left")
        self._bot_teste_res.pack(anchor="w", padx=20, pady=(4, 12))

    def _testar_bot(self):
        from telegram_manager import telegram_manager
        dest = self._bot_teste_dest.get().strip()
        if not dest:
            self._bot_teste_res.configure(text="Informe o ID do canal/grupo.")
            return
        if not telegram_manager.via_bot():
            self._bot_teste_res.configure(text="🔴 Bot não conectado (ou 'Publicar pelo bot' desligado).")
            return
        self._bot_teste_res.configure(text="🟡 Enviando...")
        texto = "✅ <b>Teste do bot</b>\nSe você está vendo esta mensagem, o bot consegue publicar aqui."
        fut = telegram_manager._run(telegram_manager.enviar(None, dest, texto, html=True))

        def _done(f):
            try:
                f.result()
                txt = "🟢 Publicado! Confira no canal/grupo (pode apagar a mensagem de teste)."
            except Exception as e:
                txt = f"🔴 {e}"
            self.after(0, lambda: self._bot_teste_res.configure(text=txt))
        fut.add_done_callback(_done)

    def _texto_status_bot(self):
        from telegram_manager import telegram_manager
        return "🟢 Bot conectado" if telegram_manager.bot else "⚪ Bot desconectado"

    def _save_bot(self):
        token = self._bot_token.get().strip()
        admin = self._bot_admin.get().strip()
        if token and ":" not in token:
            messagebox.showwarning("Aviso", "Token inválido. Copie o token completo do @BotFather.")
            return
        if admin and not admin.isdigit():
            messagebox.showwarning("Aviso", "O ID do admin deve ser numérico.")
            return

        db.set_config("bot_token", token)
        db.set_config("bot_admin_id", admin)
        db.set_config("publicar_via_bot", "1" if self._via_bot.get() else "0")
        if not token:
            self._bot_status.configure(text="⚪ Sem token: publicação pela conta")
            return

        self._bot_status.configure(text="🟡 Conectando...")
        from telegram_manager import telegram_manager

        def cb(username, error):
            txt = f"🔴 Falha: {error}" if error else f"🟢 @{username} conectado. Mande /start para ele no Telegram."
            self.after(0, lambda: self._bot_status.configure(text=txt))

        telegram_manager.iniciar_bot(cb)

    # ── Mercado Livre (fonte de busca pela API oficial) ───────────────────────

    def _build_ml_tab(self, parent):
        from ui import estilo as e
        import fontes

        sc = ctk.CTkScrollableFrame(parent, fg_color=e.CARD, corner_radius=12)
        sc.pack(fill="both", expand=True, padx=8, pady=8)

        ctk.CTkLabel(sc, text="API oficial do Mercado Livre", font=e.F_SUBTITULO).pack(anchor="w", padx=20, pady=(16, 4))
        ctk.CTkLabel(sc, text="Use o app criado no DevCenter do Mercado Livre. Em Fluxos OAuth, marque "
                              "Authorization Code e Refresh Token; a URL de redirecionamento precisa ser igual à "
                              "cadastrada lá.", font=e.F_PEQUENA, text_color=e.TEXTO_SEC, wraplength=620,
                     justify="left").pack(anchor="w", padx=20)

        def campo(rotulo, chave, padrao="", oculto=False):
            ctk.CTkLabel(sc, text=rotulo, font=e.F_NORMAL).pack(anchor="w", padx=20, pady=(12, 4))
            ent = ctk.CTkEntry(sc, width=420, show="*" if oculto else "")
            ent.insert(0, db.get_config(chave) or padrao)
            ent.pack(anchor="w", padx=20)
            return ent

        from fontes.mercadolivre import REDIRECT_PADRAO
        self._ml_cid = campo("Client ID", "ml_client_id")
        self._ml_sec = campo("Client Secret", "ml_client_secret", oculto=True)
        self._ml_redirect = campo("URL de redirecionamento", "ml_redirect_uri", REDIRECT_PADRAO)

        self._ml_ativa = ctk.BooleanVar(value=fontes.ativa("ml"))
        ctk.CTkSwitch(sc, text="Usar nas buscas automáticas", variable=self._ml_ativa, font=e.F_NORMAL,
                      command=lambda: fontes.definir_ativa("ml", self._ml_ativa.get())).pack(anchor="w", padx=20,
                                                                                         pady=(16, 0))

        ctk.CTkLabel(sc, text="Conexão", font=e.F_SUBTITULO).pack(anchor="w", padx=20, pady=(20, 4))
        self._ml_status = ctk.CTkLabel(sc, text="", font=e.F_NORMAL, wraplength=620, justify="left")
        self._ml_status.pack(anchor="w", padx=20)
        ctk.CTkLabel(sc, text="1. Conectar abre o login do Mercado Livre no navegador. Autorize com a conta dona do app.\n"
                              "2. Copie a URL inteira da barra de endereço (ela termina com ?code=…) e cole abaixo.",
                     font=e.F_PEQUENA, text_color=e.TEXTO_SEC, justify="left").pack(anchor="w", padx=20, pady=(8, 4))
        linha = ctk.CTkFrame(sc, fg_color="transparent")
        linha.pack(anchor="w", padx=20, pady=4)
        e.botao(linha, "Conectar", self._ml_conectar, largura=120).pack(side="left")
        self._ml_retorno = ctk.CTkEntry(linha, width=320, placeholder_text="https://www.google.com/?code=TG-…")
        self._ml_retorno.pack(side="left", padx=8)
        e.botao(linha, "Confirmar", self._ml_confirmar, cor="cinza", largura=110).pack(side="left")

        acoes = ctk.CTkFrame(sc, fg_color="transparent")
        acoes.pack(anchor="w", padx=20, pady=(12, 4))
        e.botao(acoes, "Testar", self._ml_testar, cor="cinza", largura=110).pack(side="left")
        e.botao(acoes, "Desconectar", self._ml_desconectar, cor="vermelho", largura=120).pack(side="left", padx=8)

        self._ml_endpoints = ctk.CTkLabel(sc, text="", font=e.F_PEQUENA, text_color=e.TEXTO_SEC,
                                          justify="left", wraplength=620)
        self._ml_endpoints.pack(anchor="w", padx=20, pady=(8, 16))
        self._ml_atualizar_status()

    def _ml_fonte(self):
        import fontes
        return fontes.get("ml")

    def _ml_salvar_credenciais(self) -> bool:
        cid, sec = self._ml_cid.get().strip(), self._ml_sec.get().strip()
        redirect = self._ml_redirect.get().strip()
        if not cid or not sec:
            messagebox.showwarning("Aviso", "Preencha Client ID e Client Secret do app do Mercado Livre.")
            return False
        if not redirect.startswith("https://"):
            messagebox.showwarning("Aviso", "A URL de redirecionamento precisa começar com https://.")
            return False
        db.set_config("ml_client_id", cid)
        db.set_config("ml_client_secret", sec)
        db.set_config("ml_redirect_uri", redirect)
        return True

    def _ml_atualizar_status(self, texto: str = None):
        import fontes
        if texto is None:
            pausa = fontes.pausada("ml")
            if pausa:
                texto = f"Pausada: {pausa}"
            elif not self._ml_fonte().conectado():
                texto = "Não conectado"
            elif not db.get_config("ml_refresh_token"):
                texto = ("Conectado por até 6 horas: o Mercado Livre não enviou refresh token. Marque Refresh Token "
                         "nos Fluxos OAuth do app no DevCenter e conecte de novo.")
            else:
                texto = "Conectado"
        self._ml_status.configure(text=texto)
        linhas = [f"{ep}: {'ok' if s['status'] == 'ok' else 'bloqueado (' + (s['detalhe'] or '') + ')'}"
                  for ep, s in sorted(db.endpoints_da_fonte("ml").items())]
        self._ml_endpoints.configure(text="\n".join(linhas))

    def _ml_conectar(self):
        import webbrowser
        if not self._ml_salvar_credenciais():
            return
        webbrowser.open(self._ml_fonte().url_autorizacao())
        self._ml_atualizar_status("Aguardando a URL de retorno do navegador.")

    def _em_segundo_plano(self, trabalho, ao_terminar):
        """Rede fora da thread da interface; o resultado volta pela fila do Tk."""
        import threading

        def _rodar():
            try:
                res, err = trabalho(), None
            except Exception as ex:
                res, err = None, ex
            self.after(0, lambda: ao_terminar(res, err))
        threading.Thread(target=_rodar, daemon=True).start()

    def _ml_confirmar(self):
        if not self._ml_salvar_credenciais():
            return
        retorno = self._ml_retorno.get().strip()
        self._ml_atualizar_status("Conectando...")

        def _fim(_, err):
            self._ml_retorno.delete(0, "end")
            if err:
                self._ml_atualizar_status(f"Não conectou: {err}")
            else:
                self._ml_testar()
        self._em_segundo_plano(lambda: self._ml_fonte().conectar(retorno), _fim)

    def _ml_testar(self):
        self._ml_atualizar_status("Testando cada endpoint (uma chamada por endpoint)...")

        def _fim(res, err):
            self._ml_atualizar_status(f"Falha no teste: {err}" if err else res["mensagem"])
        self._em_segundo_plano(lambda: self._ml_fonte().testar(), _fim)

    def _ml_desconectar(self):
        if messagebox.askyesno("Desconectar", "Desconectar o Mercado Livre? As buscas pela API param até conectar de novo."):
            self._ml_fonte().desconectar()
            self._ml_atualizar_status()

    # ── Geral ─────────────────────────────────────────────────────────────────

    def _build_geral_tab(self, parent):
        card = ctk.CTkFrame(parent, fg_color=("#ffffff", "#181b22"), corner_radius=12)
        card.pack(fill="both", expand=True, padx=8, pady=8)

        ctk.CTkLabel(card, text="Configurações Gerais",
                     font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=20, pady=(20, 16))

        # Abrir com o Windows (opção A de hospedagem: roda enquanto o PC estiver ligado)
        import inicializacao
        row0 = ctk.CTkFrame(card, fg_color="transparent")
        row0.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(row0, text="Abrir junto com o Windows:", width=200, anchor="w").pack(side="left")
        self._auto_var = ctk.BooleanVar(value=inicializacao.ativo())

        def _alternar_auto():
            try:
                inicializacao.ativar() if self._auto_var.get() else inicializacao.desativar()
            except Exception as e:
                self._auto_var.set(inicializacao.ativo())
                messagebox.showerror("Erro", f"Não foi possível alterar: {e}")
        ctk.CTkSwitch(row0, text="(abre minimizado, sem precisar de admin)", variable=self._auto_var,
                      command=_alternar_auto).pack(side="left")

        # Tema
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(row, text="Tema da interface:", width=200, anchor="w").pack(side="left")
        self._theme_var = ctk.StringVar(value=db.get_config("theme", "dark"))
        ctk.CTkOptionMenu(row, variable=self._theme_var,
                          values=["dark", "light", "system"],
                          command=self._change_theme, width=160).pack(side="left")

        # Iniciar minimizado
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(row2, text="Iniciar minimizado:", width=200, anchor="w").pack(side="left")
        self._min_var = ctk.BooleanVar(value=db.get_config("start_minimized", "0") == "1")
        ctk.CTkSwitch(row2, text="", variable=self._min_var,
                      command=lambda: db.set_config("start_minimized", "1" if self._min_var.get() else "0")).pack(side="left")

        ctk.CTkButton(card, text="Salvar", command=self._save_geral,
                      fg_color=BTN_BLUE[0], hover_color=BTN_BLUE[1],
                      width=140).pack(anchor="w", padx=20, pady=20)

    def _change_theme(self, value: str):
        import customtkinter as ctk2
        ctk2.set_appearance_mode(value)

    def _save_geral(self):
        db.set_config("theme", self._theme_var.get())
        messagebox.showinfo("Salvo", "Configurações salvas.")

    # ── Sobre ─────────────────────────────────────────────────────────────────

    def _build_sobre_tab(self, parent):
        card = ctk.CTkFrame(parent, fg_color=("#ffffff", "#181b22"), corner_radius=12)
        card.pack(fill="both", expand=True, padx=8, pady=8)

        ctk.CTkLabel(card, text="🤖", font=("Segoe UI Emoji", 48)).pack(pady=(30, 8))
        ctk.CTkLabel(card, text="Repasse Automático Telegram",
                     font=("Segoe UI", 18, "bold")).pack()
        ctk.CTkLabel(card, text="Versão 1.0.0",
                     font=("Segoe UI", 12), text_color=("#64748b", "#94a3b8")).pack(pady=4)

        ctk.CTkLabel(card,
                     text="Ferramenta para automatizar o repasse de mensagens entre grupos e canais do Telegram.\nSuporta múltiplas contas, filtros, substituições e integração com afiliados.",
                     font=("Segoe UI", 12), text_color=("#475569", "#cbd5e1"),
                     justify="center", wraplength=500).pack(pady=16)

        tech = ctk.CTkFrame(card, fg_color=("#f8fafc", "#161b22"), corner_radius=8)
        tech.pack(padx=40, pady=8, fill="x")
        for lib in ["Python 3.10+", "CustomTkinter", "Telethon", "SQLite"]:
            ctk.CTkLabel(tech, text=f"• {lib}", font=("Segoe UI", 12)).pack(anchor="w", padx=16, pady=2)

    def refresh(self):
        pass  # Sem necessidade de refresh dinâmico

