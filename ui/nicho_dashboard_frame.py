import customtkinter as ctk
from tkinter import messagebox
import threading
import os
from datetime import datetime
import database as db
import niche_scraper as scraper
from niche_scheduler import niche_scheduler, download_image, gerar_url_afiliada_produto

BTN_BLUE  = ("#1a6fd4", "#1558ab")
BTN_GRAY  = ("#cbd5e1", "#475569")
BTN_GREEN = ("#2ecc71", "#27ae60")
BTN_RED   = ("#e74c3c", "#c0392b")
HDR_BG    = ("#e2e8f2", "#1e293b")
ROW_SEL   = ("#dbeafe", "#1e3a5f")
SUCCESS   = "#27ae60"

PLATAFORMAS = ["Mercado Livre"]

NICHOS_LIST = ["Todos os Nichos", "Som automotivo", "Peças de computador", "Beleza", "Tênis", "Moda", "Produtos de casa", "Peças de carro"]

class NichoDashboardFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, corner_radius=0, fg_color=("#f1f5fb", "#121212"))
        self._selected_niche = "Todos os Nichos"
        self._contas_cache = []
        self._build()
        
    def _build(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=("white", "#1e1e1e"), corner_radius=12)
        hdr.pack(fill="x", padx=16, pady=(16, 8))
        
        ctk.CTkLabel(hdr, text="📊 Monitor de Nichos & Painel de Vendas",
                     font=("Arial", 18, "bold")).pack(side="left", padx=16, pady=14)
                     
        # Live System Health Indicator
        self._health_indicator = ctk.CTkFrame(hdr, corner_radius=8, width=150, height=36)
        self._health_indicator.pack(side="right", padx=16, pady=10)
        self._health_indicator.pack_propagate(False)
        self._health_label = ctk.CTkLabel(self._health_indicator, text="🟢 SISTEMA SAUDÁVEL", font=("Arial", 11, "bold"), text_color="white")
        self._health_label.pack(fill="both", expand=True)

        # Main Split Frame: Left Column (Materials & Niche Products), Right Column (Controls & Analytics)
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=8)
        
        # ──────────────────────────────────────────────────────────────────────
        # LEFT COLUMN (70% Width) - Niche Products & Materials
        # ──────────────────────────────────────────────────────────────────────
        left_col = ctk.CTkFrame(body, fg_color=("white", "#1e1e1e"), corner_radius=12)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 6))
        
        # Niche Select Segment
        segment_frame = ctk.CTkFrame(left_col, fg_color="transparent")
        segment_frame.pack(fill="x", padx=12, pady=(12, 4))
        
        ctk.CTkLabel(segment_frame, text="Filtrar por Nicho:", font=("Arial", 12, "bold")).pack(side="left", padx=(4, 8))
        
        self._niche_menu = ctk.CTkOptionMenu(
            segment_frame, 
            values=NICHOS_LIST, 
            command=self._change_niche,
            fg_color=BTN_GRAY[0],
            button_color=BTN_GRAY[1],
            text_color=("black", "white"),
            width=220
        )
        self._niche_menu.pack(side="left")
        
        # Manual Scrape and Table title row
        actions_row = ctk.CTkFrame(left_col, fg_color="transparent")
        actions_row.pack(fill="x", padx=12, pady=(8, 4))
        
        self._table_title = ctk.CTkLabel(actions_row, text="100 Produtos Mais Famosos (Som automotivo)", font=("Arial", 13, "bold"))
        self._table_title.pack(side="left", padx=4)
        
        # Table Header Row
        table_hdr = ctk.CTkFrame(left_col, fg_color=HDR_BG, corner_radius=8, height=36)
        table_hdr.pack(fill="x", padx=12, pady=(8, 2))
        table_hdr.pack_propagate(False)
        
        cols = [
            ("Loja", 100),
            ("Nome do Produto", 300),
            ("Preço Atual", 100),
            ("Mínimo Histórico (Data)", 180),
            ("Ação", 100)
        ]
        for name, width in cols:
            ctk.CTkLabel(table_hdr, text=name, font=("Arial", 11, "bold"), width=width, anchor="w").pack(side="left", padx=8, pady=6)
            
        # Scrollable table container
        self._table_scroll = ctk.CTkScrollableFrame(left_col, fg_color="transparent")
        self._table_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 12))
        
        # ──────────────────────────────────────────────────────────────────────
        # RIGHT COLUMN (30% Width) - Controls, Configs & Dashboard Stats
        # ──────────────────────────────────────────────────────────────────────
        right_col = ctk.CTkFrame(body, fg_color="transparent", width=340)
        right_col.pack(side="right", fill="both", padx=(6, 0))
        right_col.pack_propagate(False)
        
        # Right Tabview: Configs / Analytics
        self._right_tabs = ctk.CTkTabview(right_col, corner_radius=12, fg_color=("white", "#1e1e1e"))
        self._right_tabs.pack(fill="both", expand=True)
        
        self._tab_automation = self._right_tabs.add("⚙️ Automação")
        self._tab_stats = self._right_tabs.add("📈 Estatísticas")
        
        # --- TAB 1: AUTOMATION CONTROLS ---
        scroll_auto = ctk.CTkScrollableFrame(self._tab_automation, fg_color="transparent")
        scroll_auto.pack(fill="both", expand=True, padx=4, pady=4)
        
        # Active Toggle
        ctk.CTkLabel(scroll_auto, text="Status do Agendador Automático", font=("Arial", 11, "bold")).pack(anchor="w", padx=8, pady=(4, 2))
        self._scheduler_active_var = ctk.StringVar(value="0")
        self._scheduler_active_switch = ctk.CTkSwitch(scroll_auto, text="Agendador Ligado", variable=self._scheduler_active_var, onvalue="1", offvalue="0", command=self._save_configs_db)
        self._scheduler_active_switch.pack(anchor="w", padx=12, pady=(0, 12))
        
        # Hour selector
        ctk.CTkLabel(scroll_auto, text="Horário de Execução Diária", font=("Arial", 11, "bold")).pack(anchor="w", padx=8, pady=(4, 2))
        self._scheduler_hour_entry = ctk.CTkEntry(scroll_auto, placeholder_text="09:00", width=140)
        self._scheduler_hour_entry.pack(anchor="w", padx=8, pady=(0, 12))
        
        # Account Selector
        ctk.CTkLabel(scroll_auto, text="Conta Remetente Telegram", font=("Arial", 11, "bold")).pack(anchor="w", padx=8, pady=(4, 2))
        self._conta_var = ctk.StringVar(value="(carregando...)")
        self._conta_menu = ctk.CTkOptionMenu(scroll_auto, variable=self._conta_var, values=["(carregando...)"], width=280)
        self._conta_menu.pack(anchor="w", padx=8, pady=(0, 12))
        
        # Destination ID/Username
        ctk.CTkLabel(scroll_auto, text="Canal/Grupo Destino (Telethon ID ou @username)", font=("Arial", 11, "bold")).pack(anchor="w", padx=8, pady=(4, 2))
        self._destination_entry = ctk.CTkEntry(scroll_auto, placeholder_text="Ex: -10012345678 ou @meugrupo", width=280)
        self._destination_entry.pack(anchor="w", padx=8, pady=(0, 12))
        
        # Google Sheets URL Webhook
        ctk.CTkLabel(scroll_auto, text="Webhook Google Sheets (Apps Script URL)", font=("Arial", 11, "bold")).pack(anchor="w", padx=8, pady=(4, 2))
        self._sheets_url_entry = ctk.CTkEntry(scroll_auto, placeholder_text="Cole a URL exposta do script aqui", width=280)
        self._sheets_url_entry.pack(anchor="w", padx=8, pady=(0, 12))
        
        # Settings Save Buttons
        save_btn = ctk.CTkButton(scroll_auto, text="💾 Salvar Configurações", command=self._save_configs_db, fg_color=BTN_BLUE[0], hover_color=BTN_BLUE[1], height=34, width=280)
        save_btn.pack(anchor="w", padx=8, pady=(4, 12))
        
        # Manual Routine Execution
        ctk.CTkLabel(scroll_auto, text="Ações Manuais e Testes", font=("Arial", 11, "bold")).pack(anchor="w", padx=8, pady=(8, 2))
        self._run_now_btn = ctk.CTkButton(scroll_auto, text="🔍 Buscar e Disparar Agora", command=self._run_scheduler_manually, fg_color=BTN_GREEN[0], hover_color=BTN_GREEN[1], height=34, width=280)
        self._run_now_btn.pack(anchor="w", padx=8, pady=(0, 8))
        
        self._sync_sheets_btn = ctk.CTkButton(scroll_auto, text="📊 Forçar Sincronização Planilha", command=self._run_sheets_sync_manually, fg_color=BTN_GRAY[0], hover_color=BTN_GRAY[1], height=34, width=280)
        self._sync_sheets_btn.pack(anchor="w", padx=8, pady=(0, 16))
        
        # Real-time console logs inside Tabview
        ctk.CTkLabel(scroll_auto, text="Console de Execução em Tempo Real", font=("Arial", 11, "bold")).pack(anchor="w", padx=8, pady=(4, 2))
        self._logs_box = ctk.CTkTextbox(scroll_auto, height=180, fg_color=("#f8fafc", "#0b0f19"), border_width=1, font=("Courier", 10))
        self._logs_box.pack(fill="x", padx=8, pady=(0, 8))
        self._logs_box.configure(state="disabled")
        
        # --- TAB 2: CONVERSIONS & FINANCIAL ANALYTICS ---
        scroll_stats = ctk.CTkScrollableFrame(self._tab_stats, fg_color="transparent")
        scroll_stats.pack(fill="both", expand=True, padx=4, pady=4)
        
        # Quick Financial Summary Cards
        summary_frame = ctk.CTkFrame(scroll_stats, fg_color=HDR_BG, corner_radius=10)
        summary_frame.pack(fill="x", padx=4, pady=6)
        
        ctk.CTkLabel(summary_frame, text="Métricas Gerais (Últimos 30 dias)", font=("Arial", 12, "bold")).pack(padx=10, pady=(8, 4), anchor="w")
        
        self._stats_revenue_label = ctk.CTkLabel(summary_frame, text="Faturamento: R$ 0,00", font=("Arial", 13, "bold"), text_color=SUCCESS)
        self._stats_revenue_label.pack(padx=10, anchor="w")
        
        self._stats_conversion_label = ctk.CTkLabel(summary_frame, text="Taxa Conversão: 0,00%", font=("Arial", 12, "bold"))
        self._stats_conversion_label.pack(padx=10, anchor="w")
        
        self._stats_clicks_label = ctk.CTkLabel(summary_frame, text="Cliques Totais: 0", font=("Arial", 11))
        self._stats_clicks_label.pack(padx=10, anchor="w")
        
        self._stats_sales_label = ctk.CTkLabel(summary_frame, text="Vendas Totais: 0", font=("Arial", 11))
        self._stats_sales_label.pack(padx=10, pady=(0, 8), anchor="w")
        
        # Manual Input Form
        form_frame = ctk.CTkFrame(scroll_stats, fg_color="transparent")
        form_frame.pack(fill="x", padx=4, pady=8)
        
        ctk.CTkLabel(form_frame, text="➕ Registrar Métricas Diárias", font=("Arial", 12, "bold")).pack(anchor="w", padx=4, pady=(4, 8))
        
        # Platform Menu
        ctk.CTkLabel(form_frame, text="Plataforma:", font=("Arial", 10, "bold")).pack(anchor="w", padx=4)
        self._stat_plat_var = ctk.StringVar(value=PLATAFORMAS[0])
        self._stat_plat_menu = ctk.CTkOptionMenu(form_frame, variable=self._stat_plat_var, values=PLATAFORMAS, width=280)
        self._stat_plat_menu.pack(anchor="w", padx=4, pady=(0, 8))
        
        # Clicks Input
        ctk.CTkLabel(form_frame, text="Cliques:", font=("Arial", 10, "bold")).pack(anchor="w", padx=4)
        self._stat_clicks_entry = ctk.CTkEntry(form_frame, placeholder_text="Cliques gerados", width=280)
        self._stat_clicks_entry.pack(anchor="w", padx=4, pady=(0, 8))
        
        # Sales Input
        ctk.CTkLabel(form_frame, text="Vendas:", font=("Arial", 10, "bold")).pack(anchor="w", padx=4)
        self._stat_sales_entry = ctk.CTkEntry(form_frame, placeholder_text="Vendas convertidas", width=280)
        self._stat_sales_entry.pack(anchor="w", padx=4, pady=(0, 8))
        
        # Earnings Input
        ctk.CTkLabel(form_frame, text="Faturamento (R$):", font=("Arial", 10, "bold")).pack(anchor="w", padx=4)
        self._stat_revenue_entry = ctk.CTkEntry(form_frame, placeholder_text="Faturamento total", width=280)
        self._stat_revenue_entry.pack(anchor="w", padx=4, pady=(0, 12))
        
        save_stats_btn = ctk.CTkButton(form_frame, text="📈 Salvar Estatísticas", command=self._save_manual_statistics, fg_color=BTN_BLUE[0], hover_color=BTN_BLUE[1], height=34, width=280)
        save_stats_btn.pack(anchor="w", padx=4, pady=(0, 12))
        
        # Load initially
        self.load_configurations()
        self.load_niche_products()
        self.load_dashboard_statistics()
        
        # Bind logs redirection
        niche_scheduler.log_callback = self._append_console_log
        
    def _change_niche(self, niche_name: str):
        self._selected_niche = niche_name
        self._table_title.configure(text=f"100 Produtos Mais Famosos ({niche_name})")
        self.load_niche_products()
        
    def _append_console_log(self, text: str):
        self._logs_box.configure(state="normal")
        self._logs_box.insert("end", f"{text}\n")
        self._logs_box.see("end")
        self._logs_box.configure(state="disabled")
        
    def refresh(self):
        self.refresh_contas()
        self.load_niche_products()
        self.load_dashboard_statistics()
        self.load_configurations()
        self._update_health_status()
        
    def refresh_contas(self):
        contas = db.listar_contas()
        self._contas_cache = [c for c in contas if c.get("status") == "conectada" and c.get("tipo", "telegram") == "telegram"]
        opts = []
        for c in self._contas_cache:
            opts.append(f"✈️ TG | {c['apelido']} ({c['telefone']})")
        
        if not opts:
            self._conta_menu.configure(values=["(Nenhuma conta conectada)"])
            self._conta_var.set("(Nenhuma conta conectada)")
        else:
            self._conta_menu.configure(values=opts)
            salva_id = db.get_config("nicho_scheduler_conta", "")
            selecionado = False
            if salva_id:
                for idx, c in enumerate(self._contas_cache):
                    if str(c["id"]) == salva_id:
                        self._conta_var.set(opts[idx])
                        selecionado = True
                        break
            if not selecionado:
                self._conta_var.set(opts[0])
                
    def _update_health_status(self):
        # Checks if any scraper errors or failures occurred in the logs
        errors = scraper.SCRAPING_LOGS["errors"]
        status = scraper.SCRAPING_LOGS["status"]
        
        if status == "running":
            self._health_indicator.configure(fg_color="#f39c12")
            self._health_label.configure(text="🟡 EXECUTANDO CRAWLER")
        elif errors or status == "warning":
            self._health_indicator.configure(fg_color="#e74c3c")
            self._health_label.configure(text="🔴 INTERVENÇÃO REQUERIDA")
        else:
            self._health_indicator.configure(fg_color="#2ecc71")
            self._health_label.configure(text="🟢 SISTEMA SAUDÁVEL")
            
    def load_configurations(self):
        # Scheduler active switch
        active = db.get_config("nicho_scheduler_ativo", "0")
        self._scheduler_active_var.set(active)
        if active == "1":
            self._scheduler_active_switch.select()
        else:
            self._scheduler_active_switch.deselect()
            
        # Hour
        hour = db.get_config("nicho_scheduler_hora", "09:00")
        self._scheduler_hour_entry.delete(0, "end")
        self._scheduler_hour_entry.insert(0, hour)
        
        # Destination
        dest = db.get_config("nicho_scheduler_destino", "")
        self._destination_entry.delete(0, "end")
        self._destination_entry.insert(0, dest)
        
        # Webhook
        webhook = db.get_config("nicho_scheduler_sheets_webhook", "")
        self._sheets_url_entry.delete(0, "end")
        self._sheets_url_entry.insert(0, webhook)
        
        # Accounts
        self.refresh_contas()
        self._update_health_status()
        
    def _save_configs_db(self):
        db.set_config("nicho_scheduler_ativo", self._scheduler_active_var.get())
        db.set_config("nicho_scheduler_hora", self._scheduler_hour_entry.get().strip() or "09:00")
        db.set_config("nicho_scheduler_destino", self._destination_entry.get().strip())
        db.set_config("nicho_scheduler_sheets_webhook", self._sheets_url_entry.get().strip())
        
        # Accounts
        conta_text = self._conta_var.get()
        if conta_text != "(Nenhuma conta conectada)" and self._contas_cache:
            idx = self._conta_menu.cget("values").index(conta_text)
            conta = self._contas_cache[idx]
            db.set_config("nicho_scheduler_conta", str(conta["id"]))
            
        # Re-start scheduler thread if active
        if self._scheduler_active_var.get() == "1":
            niche_scheduler.start()
        else:
            niche_scheduler.stop()
            
        messagebox.showinfo("Configurações", "Configurações da Automação salvas com sucesso!", parent=self)
        
    def load_niche_products(self):
        # Clears list
        for w in self._table_scroll.winfo_children():
            w.destroy()
            
        products = db.listar_produtos_nicho(nicho=self._selected_niche, limit=150)
        
        if not products:
            no_lbl = ctk.CTkLabel(self._table_scroll, text="Nenhum produto indexado neste nicho hoje. Use 'Buscar e Disparar Agora' para iniciar a busca.", text_color=("#64748b", "#94a3b8"), wraplength=500)
            no_lbl.pack(pady=40)
            return

        # Prioriza Mercado Livre no topo da lista exibida
        ml_products = [p for p in products if p.get("marketplace") == "Mercado Livre"]
        other_products = [p for p in products if p.get("marketplace") != "Mercado Livre"]
        sorted_products = (ml_products + other_products)[:50]
            
        for p in sorted_products:
            row = ctk.CTkFrame(self._table_scroll, fg_color="transparent", corner_radius=6)
            row.pack(fill="x", pady=1)
            
            # Platform label with color icon
            shop = p["marketplace"]
            emoji = "🟡" if shop == "Mercado Livre" else "🟠" if shop == "Amazon" else "🔴" if shop == "Shopee" else "🔵" if shop == "Magalu" else "🔴"
            ctk.CTkLabel(row, text=f"{emoji} {shop}", width=100, anchor="w", font=("Arial", 11, "bold")).pack(side="left", padx=8)
            
            # Title
            name = p["nome"]
            title_lbl = ctk.CTkLabel(row, text=name[:50] + ("..." if len(name) > 50 else ""), width=300, anchor="w", font=("Arial", 11), justify="left")
            title_lbl.pack(side="left", padx=8)
            
            # Current Price
            curr = p["preco_atual"]
            curr_str = f"R$ {curr:.2f}".replace(".", ",") if curr else "Consultar"
            ctk.CTkLabel(row, text=curr_str, width=100, anchor="w", font=("Arial", 11, "bold"), text_color=BTN_BLUE[0]).pack(side="left", padx=8)
            
            # Historical Low with Timestamp
            low = p["menor_preco"]
            low_str = f"R$ {low:.2f}".replace(".", ",") if low else curr_str
            low_date = ""
            if p.get("menor_preco_data"):
                try:
                    low_date = datetime.strptime(p["menor_preco_data"], "%Y-%m-%d").strftime("%d/%m/%Y")
                except Exception:
                    low_date = str(p["menor_preco_data"])
            
            is_min = False
            if curr and low:
                is_min = abs(curr - low) < 0.05
                
            hist_color = SUCCESS if is_min else None
            hist_weight = "bold" if is_min else "normal"
            
            ctk.CTkLabel(
                row, 
                text=f"{low_str} ({low_date})" if low_date else low_str, 
                width=180, 
                anchor="w", 
                font=("Arial", 11, hist_weight), 
                text_color=hist_color
            ).pack(side="left", padx=8)
            
            # Action: Post Manual
            btn = ctk.CTkButton(
                row, 
                text="✈️ Disparar", 
                width=80, 
                fg_color=BTN_GREEN[0], 
                hover_color=BTN_GREEN[1],
                command=lambda p_obj=p: self._disparar_produto_individual(p_obj)
            )
            btn.pack(side="left", padx=8, pady=4)
            
            # Separator line
            sep = ctk.CTkFrame(self._table_scroll, fg_color=("#e2e8f2", "#2e2e2e"), height=1)
            sep.pack(fill="x", padx=4)

        # Informação de limite e delegação para a planilha
        footer_info = ctk.CTkFrame(self._table_scroll, fg_color=("#eff6ff", "#1e293b"), corner_radius=8)
        footer_info.pack(fill="x", padx=4, pady=12)
        ctk.CTkLabel(
            footer_info,
            text="ℹ️ Exibindo os 50 principais produtos no painel local (Mercado Livre priorizado).\nO histórico completo de preços e registros é sincronizado diretamente na planilha do Google Drive.",
            font=("Arial", 11),
            text_color=("#1e40af", "#93c5fd"),
            justify="center"
        ).pack(padx=12, pady=8)

    def _disparar_produto_individual(self, p: dict):
        conta_text = self._conta_var.get()
        destino = self._destination_entry.get().strip()
        
        if conta_text == "(Nenhuma conta conectada)" or not self._contas_cache:
            messagebox.showwarning("Aviso", "Selecione uma conta remetente do Telegram ativa.")
            return
        if not destino:
            messagebox.showwarning("Aviso", "Preencha o campo 'Canal/Grupo Destino'.")
            return
            
        idx = self._conta_menu.cget("values").index(conta_text)
        conta = self._contas_cache[idx]
        conta_id = conta["id"]
        
        self._append_console_log(f"⚡ Iniciando envio manual do produto: {p['nome'][:30]}...")
        
        def _worker():
            try:
                from telegram_manager import telegram_manager
                client = telegram_manager.clients.get(conta_id)
                if not client:
                    raise RuntimeError("Sessão Telegram offline.")
                    
                aff_url = gerar_url_afiliada_produto(p)
                p["url_afiliado"] = aff_url
                db.salvar_produto_nicho(p)
                
                preco_atual_fmt = f"R$ {p['preco_atual']:.2f}".replace(".", ",") if p['preco_atual'] else "Consultar no site"
                menor_preco_fmt = f"R$ {p['menor_preco']:.2f}".replace(".", ",") if p['menor_preco'] else preco_atual_fmt
                menor_data = datetime.strptime(p['menor_preco_data'], "%Y-%m-%d").strftime("%d/%m/%Y") if p['menor_preco_data'] else datetime.now().strftime("%d/%m/%Y")
                
                text_copy = (
                    f"🔥 *OFERTA EXCLUSIVA INDIVIDUAL!* 🔥\n\n"
                    f"📦 *{p['nome']}*\n"
                    f"🏷️ Nicho: *{p['nicho']}*\n"
                    f"🏪 Loja: *{p['marketplace']}*\n\n"
                    f"💵 Preço Atual: *{preco_atual_fmt}*\n"
                    f"📉 *MENOR PREÇO HISTÓRICO:* *{menor_preco_fmt}*\n"
                    f"📅 (Registrado em: {menor_data})\n\n"
                    f"🛒 *Compre com segurança pelo link de afiliado:* {aff_url}"
                )
                
                local_img = download_image(p["imagem_url"])
                
                async def _send():
                    dest_entity = await telegram_manager.resolve_entity(client, destino)
                    await client.send_message(dest_entity, text_copy, file=local_img)
                    return True
                    
                future = telegram_manager._run(_send())
                future.result(timeout=25)
                
                if local_img and os.path.exists(local_img):
                    try:
                        os.remove(local_img)
                    except Exception:
                        pass
                        
                db.salvar_disparo_status(p["id"], datetime.now().strftime("%Y-%m-%d"), "enviado")
                self.after(0, lambda: [
                    self._append_console_log(f"✅ Oferta individual enviada: {p['nome'][:30]}..."),
                    messagebox.showinfo("Sucesso", "Mensagem enviada com sucesso no Telegram!", parent=self)
                ])
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda err=err_msg: [
                    self._append_console_log(f"❌ Falha no envio manual: {err}"),
                    messagebox.showerror("Erro", f"Erro ao enviar: {err}", parent=self)
                ])
                
        threading.Thread(target=_worker, daemon=True).start()

    def _run_scheduler_manually(self):
        # Validação de configs antes
        conta_text = self._conta_var.get()
        destino = self._destination_entry.get().strip()
        if conta_text == "(Nenhuma conta conectada)" or not self._contas_cache:
            messagebox.showwarning("Aviso", "Selecione uma conta Telegram conectada nas configurações primeiro.")
            return
        if not destino:
            messagebox.showwarning("Aviso", "Insira o grupo de destino Telegram primeiro.")
            return
            
        # Salva primeiro
        self._save_configs_db()
        
        self._run_now_btn.configure(state="disabled", text="Buscando...")
        self._append_console_log("⚡ Iniciando rotina completa manual de busca & disparos em background...")
        
        def _worker():
            try:
                success = niche_scheduler.executar_rotina_completa()
                self.after(0, lambda: [
                    self._run_now_btn.configure(state="normal", text="🔍 Buscar e Disparar Agora"),
                    self._update_health_status(),
                    self.load_niche_products(),
                    messagebox.showinfo("Automação", "Rotina completa executada com sucesso!", parent=self) if success else messagebox.showwarning("Automação", "Rotina completada, mas alguns itens falharam. Verifique os logs.", parent=self)
                ])
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda err=err_msg: [
                    self._run_now_btn.configure(state="normal", text="🔍 Buscar e Disparar Agora"),
                    self._update_health_status(),
                    self._append_console_log(f"❌ Erro crítico na rotina: {err}"),
                    messagebox.showerror("Erro", f"Falha na rotina manual: {err}", parent=self)
                ])
                
        threading.Thread(target=_worker, daemon=True).start()

    def _run_sheets_sync_manually(self):
        webhook = self._sheets_url_entry.get().strip()
        if not webhook:
            messagebox.showwarning("Aviso", "Insira a URL do Webhook do Google Sheets primeiro.")
            return
            
        self._sync_sheets_btn.configure(state="disabled", text="Sincronizando...")
        self._append_console_log("⚡ Sincronizando dados com a Planilha do Google Drive...")
        
        def _worker():
            from niche_scheduler import sync_to_google_sheets
            ok, msg = sync_to_google_sheets(webhook)
            if ok:
                self.after(0, lambda m=msg: [
                    self._sync_sheets_btn.configure(state="normal", text="📊 Forçar Sincronização Planilha"),
                    self._append_console_log(f"✅ Sincronização concluída! {m}"),
                    messagebox.showinfo("Google Sheets", f"Planilha atualizada com sucesso!\n\nDetalhes:\n{m}", parent=self)
                ])
            else:
                self.after(0, lambda m=msg: [
                    self._sync_sheets_btn.configure(state="normal", text="📊 Forçar Sincronização Planilha"),
                    self._append_console_log(f"❌ Falha ao sincronizar: {m}"),
                    messagebox.showerror("Erro", f"Falha na sincronização da planilha.\n\nDetalhes:\n{m}", parent=self)
                ])
                
        threading.Thread(target=_worker, daemon=True).start()

    def _save_manual_statistics(self):
        plat = self._stat_plat_var.get()
        
        try:
            clicks = int(self._stat_clicks_entry.get().strip() or "0")
            vendas = int(self._stat_sales_entry.get().strip() or "0")
            
            rev_str = self._stat_revenue_entry.get().strip().replace("R$", "").replace(" ", "")
            if "," in rev_str:
                rev_str = rev_str.replace(".", "").replace(",", ".")
            revenue = float(rev_str or "0.0")
        except ValueError:
            messagebox.showwarning("Erro de Entrada", "Cliques e Vendas devem ser inteiros. Faturamento deve ser um número válido.")
            return
            
        hoje = datetime.now().strftime("%Y-%m-%d")
        
        try:
            db.salvar_stats_dashboard(hoje, plat, clicks, vendas, revenue)
            self._stat_clicks_entry.delete(0, "end")
            self._stat_sales_entry.delete(0, "end")
            self._stat_revenue_entry.delete(0, "end")
            
            self.load_dashboard_statistics()
            messagebox.showinfo("Estatísticas", f"Métricas de hoje salvas para {plat} com sucesso!", parent=self)
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao salvar estatísticas: {e}", parent=self)

    def load_dashboard_statistics(self):
        try:
            stats = db.listar_stats_dashboard(30)
            
            total_clicks = 0
            total_sales = 0
            total_revenue = 0.0
            
            for s in stats:
                total_clicks += s.get("cliques", 0)
                total_sales += s.get("vendas", 0)
                total_revenue += s.get("faturamento", 0.0)
                
            conv_rate = (total_sales / total_clicks * 100.0) if total_clicks > 0 else 0.0
            
            # Update labels
            self._stats_revenue_label.configure(text=f"Faturamento: R$ {total_revenue:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
            self._stats_conversion_label.configure(text=f"Taxa Conversão: {conv_rate:.2f}%")
            self._stats_clicks_label.configure(text=f"Cliques Totais: {total_clicks:,}")
            self._stats_sales_label.configure(text=f"Vendas Totais: {total_sales:,}")
        except Exception as e:
            print(f"Erro ao carregar estatísticas: {e}")
