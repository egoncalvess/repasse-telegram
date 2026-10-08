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
        tab.add("Geral")
        tab.add("Sobre")

        self._build_api_tab(tab.tab("API Telegram"))
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

