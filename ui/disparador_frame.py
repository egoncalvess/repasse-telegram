import customtkinter as ctk
from tkinter import filedialog, messagebox
import threading
import time
import os
from collections import deque
from datetime import datetime
import database as db

BTN_BLUE  = ("#1a6fd4", "#1558ab")
BTN_GRAY  = ("#64748b", "#475569")
BTN_GREEN = ("#2ecc71", "#27ae60")
HDR_BG    = ("#e2e8f2", "#1e293b")

class DisparadorFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, corner_radius=0, fg_color=("#f1f5fb", "#121212"))
        self._selected_file = None
        self._dest_mapping = {}
        self._log_queue = deque()
        self._log_lines = []
        self._max_log_lines = 150
        self._build()
        self._start_queue_processor()

    def _build(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=("white", "#1e1e1e"), corner_radius=12)
        hdr.pack(fill="x", padx=16, pady=(16, 8))
        ctk.CTkLabel(hdr, text="🚀 Disparador de Mensagens Seguidas (Telegram)",
                     font=("Arial", 18, "bold")).pack(side="left", padx=16, pady=14)

        # Main Layout (Split: Left Controls, Right Status/Log)
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=8)

        # ── LEFT COLUMN (Inputs & Form Reorganized) ──
        left = ctk.CTkFrame(body, fg_color=("white", "#1e1e1e"), corner_radius=12)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=8, pady=8)

        # SEÇÃO 1: Configuração do Remetente
        s1 = ctk.CTkFrame(scroll, fg_color=("#f8fafc", "#161b22"), corner_radius=10)
        s1.pack(fill="x", padx=4, pady=(4, 10))
        
        ctk.CTkLabel(s1, text="👤 Configuração do Remetente", font=("Arial", 13, "bold")).pack(anchor="w", padx=12, pady=(10, 6))

        ctk.CTkLabel(s1, text="Conta Remetente Telegram (Conectada)", font=("Arial", 11, "bold")).pack(anchor="w", padx=12, pady=(2, 2))
        self._conta_var = ctk.StringVar(value="(carregando...)")
        self._conta_menu = ctk.CTkOptionMenu(s1, variable=self._conta_var, values=["(carregando...)"], width=320)
        self._conta_menu.pack(anchor="w", padx=12, pady=(0, 10))

        ctk.CTkLabel(s1, text="Destinatário (ID Telethon, @username ou chat)", font=("Arial", 11, "bold")).pack(anchor="w", padx=12, pady=(2, 2))
        dest_row = ctk.CTkFrame(s1, fg_color="transparent")
        dest_row.pack(anchor="w", padx=12, pady=(0, 12))
        
        self._destinatario = ctk.CTkComboBox(dest_row, values=[], width=220)
        self._destinatario.set("")
        self._destinatario.pack(side="left")
        
        self._sync_dest_btn = ctk.CTkButton(dest_row, text="↻ Sincronizar", command=self._sync_recipients, fg_color=BTN_GRAY[0], hover_color=BTN_GRAY[1], width=90)
        self._sync_dest_btn.pack(side="left", padx=(8, 0))

        # SEÇÃO 2: Conteúdo / Anexo
        s2 = ctk.CTkFrame(scroll, fg_color=("#f8fafc", "#161b22"), corner_radius=10)
        s2.pack(fill="x", padx=4, pady=(0, 10))

        ctk.CTkLabel(s2, text="📝 Conteúdo & Anexo", font=("Arial", 13, "bold")).pack(anchor="w", padx=12, pady=(10, 6))

        # Gerador Automático de Posts
        ctk.CTkLabel(s2, text="Auto-Gerador de Posts (Copiar Link do Produto)", font=("Arial", 11, "bold")).pack(anchor="w", padx=12, pady=(2, 2))
        scrape_row = ctk.CTkFrame(s2, fg_color="transparent")
        scrape_row.pack(anchor="w", padx=12, pady=(0, 10))
        
        self._product_url_entry = ctk.CTkEntry(scrape_row, placeholder_text="Cole o link da Amazon, Shopee ou ML", width=220)
        self._product_url_entry.pack(side="left")
        
        self._scrape_btn = ctk.CTkButton(scrape_row, text="🔍 Gerar Post", command=self._auto_generate_post, fg_color=BTN_BLUE[0], hover_color=BTN_BLUE[1], width=90)
        self._scrape_btn.pack(side="left", padx=(8, 0))

        # Anexo de Mídia
        ctk.CTkLabel(s2, text="Anexo de Mídia (Imagem, Vídeo, PDF)", font=("Arial", 11, "bold")).pack(anchor="w", padx=12, pady=(2, 2))
        file_row = ctk.CTkFrame(s2, fg_color="transparent")
        file_row.pack(anchor="w", padx=12, pady=(0, 10))
        
        self._file_label = ctk.CTkLabel(file_row, text="Nenhum arquivo selecionado", text_color=("#64748b", "#94a3b8"), width=200, anchor="w")
        self._file_label.pack(side="left", padx=(0, 8))
        
        ctk.CTkButton(file_row, text="Selecionar", command=self._select_file, fg_color=BTN_GRAY[0], hover_color=BTN_GRAY[1], width=100).pack(side="left")

        # Texto das Mensagens
        ctk.CTkLabel(s2, text="Conteúdo das Mensagens (Use '---' para separar mensagens seguidas)", font=("Arial", 11, "bold")).pack(anchor="w", padx=12, pady=(2, 2))
        self._messages_box = ctk.CTkTextbox(s2, width=320, height=140, border_width=1)
        self._messages_box.pack(anchor="w", padx=12, pady=(0, 12))
        self._messages_box.insert("1.0", "Mensagem 1\n---\nMensagem 2\n---\nMensagem 3")

        # SEÇÃO 3: Parâmetros de Envio
        s3 = ctk.CTkFrame(scroll, fg_color=("#f8fafc", "#161b22"), corner_radius=10)
        s3.pack(fill="x", padx=4, pady=(0, 10))

        ctk.CTkLabel(s3, text="⚙️ Parâmetros de Envio", font=("Arial", 13, "bold")).pack(anchor="w", padx=12, pady=(10, 6))

        delay_row = ctk.CTkFrame(s3, fg_color="transparent")
        delay_row.pack(anchor="w", padx=12, pady=(0, 12))
        
        ctk.CTkLabel(delay_row, text="Delay entre envios (segundos):", font=("Arial", 11, "bold")).pack(side="left", padx=(0, 8))
        self._delay_entry = ctk.CTkEntry(delay_row, width=60)
        self._delay_entry.insert(0, "2")
        self._delay_entry.pack(side="left")

        self._send_btn = ctk.CTkButton(s3, text="🚀 Disparar Mensagens", command=self._start_broadcast, fg_color=BTN_BLUE[0], hover_color=BTN_BLUE[1], width=320, height=40)
        self._send_btn.pack(anchor="w", padx=12, pady=(0, 12))

        # ── RIGHT COLUMN (Live Asynchronous Log & Progress) ──
        right = ctk.CTkFrame(body, fg_color=("white", "#1e1e1e"), corner_radius=12)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))

        ctk.CTkLabel(right, text="Status e Log de Transmissão (Assíncrono)", font=("Arial", 14, "bold")).pack(anchor="w", padx=16, pady=(16, 8))
        
        self._log_box = ctk.CTkTextbox(right, fg_color=("#f8fafc", "#0b0f19"), border_width=1, font=("Courier", 10))
        self._log_box.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self._log_box.configure(state="disabled")

        self.refresh()

    def _select_file(self):
        path = filedialog.askopenfilename(
            title="Selecionar Anexo",
            filetypes=[("Imagens e Mídias", "*.jpg;*.jpeg;*.png;*.gif;*.mp4;*.pdf"), ("Todos os Arquivos", "*.*")]
        )
        if path:
            self._selected_file = path
            self._file_label.configure(text=os.path.basename(path))
        else:
            self._selected_file = None
            self._file_label.configure(text="Nenhum arquivo selecionado")

    def refresh(self):
        """Atualiza a lista de contas Telegram conectadas disponíveis."""
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
            self._conta_var.set(opts[0])

    def _enqueue_log(self, text: str):
        """Enfileira mensagem para renderização leve e assíncrona na GUI."""
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_queue.append(f"[{ts}] {text}")

    def _start_queue_processor(self):
        """Processador leve de mensagens de log que atualiza o DOM em ticks de 100ms."""
        if not self.winfo_exists():
            return
            
        updated = False
        while self._log_queue:
            msg = self._log_queue.popleft()
            self._log_lines.append(msg)
            # Limita buffer no DOM a 150 linhas para manter renderização fluida
            if len(self._log_lines) > self._max_log_lines:
                self._log_lines.pop(0)
            updated = True
            
        if updated:
            self._log_box.configure(state="normal")
            self._log_box.delete("1.0", "end")
            self._log_box.insert("end", "\n".join(self._log_lines) + "\n")
            self._log_box.see("end")
            self._log_box.configure(state="disabled")
            
        self.after(100, self._start_queue_processor)

    def _clear_logs(self):
        self._log_lines.clear()
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.configure(state="disabled")

    def _start_broadcast(self):
        conta_label = self._conta_var.get()
        if conta_label == "(Nenhuma conta conectada)" or not self._contas_cache:
            messagebox.showwarning("Aviso", "Você precisa selecionar uma conta Telegram conectada.")
            return

        dest_val = self._destinatario.get().strip()
        if not dest_val:
            messagebox.showwarning("Aviso", "Informe o destinatário.")
            return

        if hasattr(self, "_dest_mapping") and dest_val in self._dest_mapping:
            dest = self._dest_mapping[dest_val]
        else:
            dest = dest_val

        text_content = self._messages_box.get("1.0", "end-1c").strip()
        if not text_content:
            messagebox.showwarning("Aviso", "Escreva ao menos uma mensagem para enviar.")
            return

        try:
            delay = int(self._delay_entry.get().strip())
        except ValueError:
            messagebox.showwarning("Aviso", "O delay deve ser um número inteiro.")
            return

        selected_idx = self._conta_menu.cget("values").index(conta_label)
        conta = self._contas_cache[selected_idx]
        messages = [m.strip() for m in text_content.split("---") if m.strip()]

        self._send_btn.configure(state="disabled", text="Enviando...")
        self._clear_logs()
        self._enqueue_log("🚀 Iniciando disparo de mensagens seguidas via Telegram...")
        
        t = threading.Thread(target=self._broadcast_thread, args=(conta, dest, messages, delay, self._selected_file))
        t.daemon = True
        t.start()

    def _broadcast_thread(self, conta: dict, dest: str, messages: list[str], delay: int, file_path: str):
        conta_id = conta["id"]
        from telegram_manager import telegram_manager

        total = len(messages)
        sucessos = 0
        
        for idx, text in enumerate(messages, 1):
            self._enqueue_log(f"➡️ [{idx}/{total}] Enviando mensagem Telegram...")
            success = False
            current_file = file_path if idx == 1 else None

            try:
                client = telegram_manager.clients.get(conta_id)
                if client:
                    import asyncio
                    
                    async def send_tg():
                        dest_entity = await telegram_manager.resolve_entity(client, dest)
                        await client.send_message(dest_entity, text, file=current_file)
                        return True
                        
                    future = asyncio.run_coroutine_threadsafe(send_tg(), telegram_manager.loop)
                    success = future.result(timeout=20)
                else:
                    self._enqueue_log("❌ Erro: Conta Telegram offline.")
            except Exception as e:
                self._enqueue_log(f"❌ Falha no envio: {e}")

            if success:
                sucessos += 1
                self._enqueue_log(f"✅ [{idx}/{total}] Enviada com sucesso!")
            else:
                self._enqueue_log(f"❌ [{idx}/{total}] Erro ao enviar.")

            if idx < total:
                self._enqueue_log(f"⏳ Aguardando {delay} segundos antes do próximo disparo...")
                time.sleep(delay)

        self._enqueue_log(f"🏁 Disparo concluído! {sucessos} de {total} enviadas.")
        self.after(10, lambda: self._send_btn.configure(state="normal", text="🚀 Disparar Mensagens"))

    def _sync_recipients(self):
        conta_label = self._conta_var.get()
        if conta_label == "(Nenhuma conta conectada)" or not self._contas_cache:
            messagebox.showwarning("Aviso", "Você precisa selecionar uma conta conectada para sincronizar.", parent=self)
            return

        selected_idx = self._conta_menu.cget("values").index(conta_label)
        conta = self._contas_cache[selected_idx]
        conta_id = conta["id"]

        self._sync_dest_btn.configure(state="disabled", text="Carregando...")

        def _update_combo(values):
            self._sync_dest_btn.configure(state="normal", text="↻ Sincronizar")
            if not values:
                messagebox.showinfo("Informação", "Nenhum chat ou canal Telegram encontrado.", parent=self)
                return
            self._dest_mapping = values
            opts = list(values.keys())
            self._destinatario.configure(values=opts)
            self._destinatario.set(opts[0])
            messagebox.showinfo("Sucesso", f"Sincronizados {len(opts)} chats/canais Telegram com sucesso!", parent=self)

        from telegram_manager import telegram_manager
        def cb(groups, error):
            if error:
                self.after(0, lambda: [
                    self._sync_dest_btn.configure(state="normal", text="↻ Sincronizar"),
                    messagebox.showerror("Erro", error, parent=self)
                ])
                return
            
            mapping = {}
            for g in groups:
                gid = g["id"]
                mapping[f"{g['nome']} ({gid})"] = gid
                
            self.after(0, lambda: _update_combo(mapping))

        telegram_manager.get_all_dialogs(conta_id, cb)

    def _auto_generate_post(self):
        url = self._product_url_entry.get().strip()
        if not url:
            messagebox.showwarning("Aviso", "Cole o link de um produto primeiro.", parent=self)
            return

        self._scrape_btn.configure(state="disabled", text="Extraindo...")
        self._enqueue_log("🔍 Extraindo metadados do produto...")

        tag = ""
        cookie = ""
        try:
            platform = None
            if "amazon" in url or "amzn.to" in url:
                platform = "amazon"
            elif "magazinevoce" in url:
                platform = "magalu"
            elif "shopee" in url or "shope.ee" in url:
                platform = "shopee"
            elif "mercadolivre" in url or "mlb.link" in url or "mpago.la" in url or "mpago.li" in url:
                platform = "mercadolivre"

            if platform:
                integrations = db.listar_integracoes()
                for i in integrations:
                    if i.get("tipo") == platform and i.get("ativo", 1):
                        tag = i.get("tag", "")
                        cookie = i.get("cookie", "")
                        break
        except Exception:
            pass

        def _on_complete(result, error):
            self._scrape_btn.configure(state="normal", text="🔍 Gerar Post")
            if error:
                self._enqueue_log(f"❌ Falha ao extrair produto: {error}")
                messagebox.showerror("Erro", f"Erro no Scraping: {error}", parent=self)
                return

            if not result:
                self._enqueue_log("❌ Falha: Nenhuma informação extraída.")
                messagebox.showwarning("Aviso", "Não foi possível extrair detalhes do link.", parent=self)
                return

            self._enqueue_log("✅ Produto extraído com sucesso!")
            title = result.get("title", "Produto Recomendado")
            price = result.get("price", "Consultar no site")
            aff_url = result.get("affiliate_url", url)
            img_path = result.get("image_path")

            if img_path and os.path.exists(img_path):
                self._selected_file = img_path
                self._file_label.configure(text=os.path.basename(img_path))
                self._enqueue_log(f"📸 Imagem do produto anexada: {os.path.basename(img_path)}")
            else:
                self._selected_file = None
                self._file_label.configure(text="Nenhum arquivo selecionado")

            copy = f"🔥 *PROMOÇÃO IMPERDÍVEL!* 🔥\n\n📦 *{title}*\n\n💵 Por apenas: *{price}*\n\n🛒 *Compre aqui com segurança:* {aff_url}"
            self._messages_box.delete("1.0", "end")
            self._messages_box.insert("1.0", copy)
            self._enqueue_log("✍️ Copy da oferta gerada com link de afiliado!")
            messagebox.showinfo("Sucesso", "Oferta gerada com sucesso!", parent=self)

        def _worker():
            try:
                from affiliate_helper import scrape_product_details
                res = scrape_product_details(url, tag, cookie)
                self.after(0, lambda: _on_complete(res, None))
            except Exception as e:
                self.after(0, lambda: _on_complete(None, str(e)))

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
