import customtkinter as ctk
from tkinter import messagebox
import database as db

BTN_BLUE = ("#1a6fd4", "#1558ab")
BTN_GRAY = ("#64748b", "#4b5563")


class ConfiguracoesFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, corner_radius=0, fg_color=("#f1f5fb", "#121212"))
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="Configurações",
                     font=("Arial", 18, "bold")).pack(anchor="w", padx=24, pady=(20, 4))

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
        card = ctk.CTkFrame(parent, fg_color=("white", "#1e1e1e"), corner_radius=12)
        card.pack(fill="both", expand=True, padx=8, pady=8)

        ctk.CTkLabel(card, text="Credenciais da API Telegram",
                     font=("Arial", 15, "bold")).pack(anchor="w", padx=20, pady=(20, 4))

        ctk.CTkLabel(card,
                     text="Obtenha em https://my.telegram.org → API development tools",
                     font=("Arial", 11), text_color=("#64748b", "#94a3b8")).pack(anchor="w", padx=20)

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
                     font=("Arial", 11), text_color=("#92400e", "#fcd34d"),
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
        card = ctk.CTkFrame(parent, fg_color=("white", "#1e1e1e"), corner_radius=12)
        card.pack(fill="both", expand=True, padx=8, pady=8)

        ctk.CTkLabel(card, text="Bot de publicação e painel de controle",
                     font=("Arial", 15, "bold")).pack(anchor="w", padx=20, pady=(20, 4))
        ctk.CTkLabel(card,
                     text="Crie o bot no @BotFather e adicione-o como administrador dos grupos/canais de destino.\n"
                          "A conta continua só lendo as origens; quem publica é o bot (API oficial, sem risco de ban da conta).",
                     font=("Arial", 11), text_color=("#64748b", "#94a3b8"), justify="left").pack(anchor="w", padx=20)

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
        self._bot_status = ctk.CTkLabel(card, text=self._texto_status_bot(), font=("Arial", 12))
        self._bot_status.pack(anchor="w", padx=20)

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

    # ── Mercado Livre (API oficial) ───────────────────────────────────────────

    def _build_ml_tab(self, parent):
        card = ctk.CTkFrame(parent, fg_color=("white", "#1e1e1e"), corner_radius=12)
        card.pack(fill="both", expand=True, padx=8, pady=8)

        ctk.CTkLabel(card, text="API oficial do Mercado Livre (busca de ofertas por nicho)",
                     font=("Arial", 15, "bold")).pack(anchor="w", padx=20, pady=(20, 4))
        ctk.CTkLabel(card,
                     text="A busca pública do ML e o site bloqueiam robôs. Com um app gratuito do DevCenter,\n"
                          "o agendador lê os mais vendidos de cada nicho com preço real.\n"
                          "Crie em developers.mercadolivre.com.br/devcenter → Criar aplicação e copie Client ID e Secret.",
                     font=("Arial", 11), text_color=("#64748b", "#94a3b8"), justify="left").pack(anchor="w", padx=20)

        ctk.CTkLabel(card, text="Client ID (App ID)").pack(anchor="w", padx=20, pady=(16, 4))
        self._ml_id = ctk.CTkEntry(card, width=400, placeholder_text="Ex: 1234567890123456")
        self._ml_id.pack(anchor="w", padx=20)
        self._ml_id.insert(0, db.get_config("ml_client_id") or "")

        ctk.CTkLabel(card, text="Client Secret").pack(anchor="w", padx=20, pady=(12, 4))
        self._ml_secret = ctk.CTkEntry(card, width=400, show="*")
        self._ml_secret.pack(anchor="w", padx=20)
        self._ml_secret.insert(0, db.get_config("ml_client_secret") or "")

        ctk.CTkButton(card, text="Salvar e testar conexão", command=self._save_ml,
                      fg_color=BTN_BLUE[0], hover_color=BTN_BLUE[1],
                      width=200).pack(anchor="w", padx=20, pady=(20, 6))
        self._ml_status = ctk.CTkLabel(card, text="", font=("Arial", 12), wraplength=600, justify="left")
        self._ml_status.pack(anchor="w", padx=20)

    def _save_ml(self):
        db.set_config("ml_client_id", self._ml_id.get().strip())
        db.set_config("ml_client_secret", self._ml_secret.get().strip())
        self._ml_status.configure(text="🟡 Testando...")

        def _worker():
            import niche_scraper
            try:
                txt = "🟢 " + niche_scraper.testar_conexao_ml()
            except Exception as e:
                txt = f"🔴 {e}"
            self.after(0, lambda: self._ml_status.configure(text=txt))

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    # ── Geral ─────────────────────────────────────────────────────────────────

    def _build_geral_tab(self, parent):
        card = ctk.CTkFrame(parent, fg_color=("white", "#1e1e1e"), corner_radius=12)
        card.pack(fill="both", expand=True, padx=8, pady=8)

        ctk.CTkLabel(card, text="Configurações Gerais",
                     font=("Arial", 15, "bold")).pack(anchor="w", padx=20, pady=(20, 16))

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
        card = ctk.CTkFrame(parent, fg_color=("white", "#1e1e1e"), corner_radius=12)
        card.pack(fill="both", expand=True, padx=8, pady=8)

        ctk.CTkLabel(card, text="🤖", font=("Segoe UI Emoji", 48)).pack(pady=(30, 8))
        ctk.CTkLabel(card, text="Repasse Automático Telegram",
                     font=("Arial", 18, "bold")).pack()
        ctk.CTkLabel(card, text="Versão 1.0.0",
                     font=("Arial", 12), text_color=("#64748b", "#94a3b8")).pack(pady=4)

        ctk.CTkLabel(card,
                     text="Ferramenta para automatizar o repasse de mensagens entre grupos e canais do Telegram.\nSuporta múltiplas contas, filtros, substituições e integração com afiliados.",
                     font=("Arial", 12), text_color=("#475569", "#cbd5e1"),
                     justify="center", wraplength=500).pack(pady=16)

        tech = ctk.CTkFrame(card, fg_color=("#f8fafc", "#161b22"), corner_radius=8)
        tech.pack(padx=40, pady=8, fill="x")
        for lib in ["Python 3.10+", "CustomTkinter", "Telethon", "SQLite"]:
            ctk.CTkLabel(tech, text=f"• {lib}", font=("Arial", 12)).pack(anchor="w", padx=16, pady=2)

    def refresh(self):
        pass  # Sem necessidade de refresh dinâmico

