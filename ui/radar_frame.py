"""
Radar de Preços: produtos vistos nos canais monitorados, comparados ao próprio histórico.
Mostra os menores preços do dia e publica com um clique.
"""
import threading
import customtkinter as ctk
from tkinter import messagebox

import database as db
from oferta import brl, selo, publicar_oferta

BTN_BLUE = ("#1a6fd4", "#1558ab")
BTN_GRAY = ("#64748b", "#4b5563")
HDR_BG   = ("#e2e8f2", "#1e293b")
COLS = [("Produto", 330), ("Loja", 110), ("Hoje", 95), ("Média", 95), ("Mín. ant.", 95), ("Dias", 45), ("Destaque", 230)]


class RadarFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, corner_radius=0, fg_color=("#f1f5fb", "#121212"))
        self._build()

    def _build(self):
        hdr = ctk.CTkFrame(self, fg_color=("white", "#1e1e1e"), corner_radius=12)
        hdr.pack(fill="x", padx=16, pady=(16, 8))
        ctk.CTkLabel(hdr, text="Radar de Preços", font=("Arial", 18, "bold")).pack(side="left", padx=16, pady=14)
        self._resumo = ctk.CTkLabel(hdr, text="", font=("Arial", 12), text_color=("#64748b", "#94a3b8"))
        self._resumo.pack(side="left", padx=8)
        ctk.CTkButton(hdr, text="↻ Atualizar", width=110, command=self.refresh,
                      fg_color=BTN_GRAY[0], hover_color=BTN_GRAY[1]).pack(side="right", padx=12)
        self._btn_importar = ctk.CTkButton(hdr, text="📥 Importar histórico", width=160, command=self._importar,
                                           fg_color=BTN_BLUE[0], hover_color=BTN_BLUE[1])
        self._btn_importar.pack(side="right", padx=4)
        self._dias = ctk.StringVar(value="30 dias")
        ctk.CTkOptionMenu(hdr, variable=self._dias, values=["7 dias", "30 dias", "90 dias"],
                          width=100).pack(side="right", padx=4)

        dest = ctk.CTkFrame(self, fg_color=("white", "#1e1e1e"), corner_radius=12)
        dest.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(dest, text="Publicar em (ID do grupo/canal):").pack(side="left", padx=(16, 8), pady=10)
        self._destino = ctk.CTkEntry(dest, width=220, placeholder_text="-100...")
        self._destino.pack(side="left")
        self._destino.insert(0, db.get_config("radar_destino") or db.get_config("nicho_scheduler_destino") or "")
        ctk.CTkButton(dest, text="Salvar", width=80, command=self._salvar_destino,
                      fg_color=BTN_BLUE[0], hover_color=BTN_BLUE[1]).pack(side="left", padx=8)
        ctk.CTkLabel(dest, text="Os preços vêm das ofertas dos canais de origem dos seus repasses.",
                     font=("Arial", 11), text_color=("#64748b", "#94a3b8")).pack(side="left", padx=12)

        card = ctk.CTkFrame(self, fg_color=("white", "#1e1e1e"), corner_radius=12)
        card.pack(fill="both", expand=True, padx=16, pady=8)
        ctk.CTkLabel(card, text="📉 Menores preços do dia", font=("Arial", 14, "bold")).pack(anchor="w", padx=12, pady=(10, 0))
        hrow = ctk.CTkFrame(card, fg_color=HDR_BG, corner_radius=8)
        hrow.pack(fill="x", padx=8, pady=(6, 0))
        for col, w in COLS:
            ctk.CTkLabel(hrow, text=col, font=("Arial", 12, "bold"), width=w, anchor="w").pack(side="left", padx=4, pady=8)
        self._list = ctk.CTkScrollableFrame(card, fg_color="transparent")
        self._list.pack(fill="both", expand=True, padx=8, pady=6)

    def refresh(self):
        r = db.resumo_radar()
        self._resumo.configure(text=f"{r['produtos']} produtos monitorados · {r['precos_hoje']} preços registrados hoje")
        for w in self._list.winfo_children():
            w.destroy()

        itens = db.menores_precos_do_dia(limit=50)
        if not itens:
            ctk.CTkLabel(self._list, text="Nenhuma oferta com preço registrada hoje.\n"
                                           "Assim que os canais de origem postarem ofertas, elas aparecem aqui.",
                         text_color=("#94a3b8", "#64748b")).pack(pady=30)
            return
        for p in itens:
            row = ctk.CTkFrame(self._list, fg_color="transparent")
            row.pack(fill="x", pady=1)
            valores = [p["nome"][:48], p["loja"], brl(p["preco_hoje"]),
                       brl(p["media"]) if p["media"] else "—", brl(p["minimo"]) if p["minimo"] else "—",
                       str(p["dias"]), selo(p) or ("Novo no radar" if not p["dias"] else "")]
            for (col, w), v in zip(COLS, valores):
                ctk.CTkLabel(row, text=v, width=w, anchor="w").pack(side="left", padx=4)
            ctk.CTkButton(row, text="Publicar", width=80, fg_color=BTN_BLUE[0], hover_color=BTN_BLUE[1],
                          command=lambda c=p["chave"], n=p["nome"]: self._publicar(c, n)).pack(side="left", padx=4)

    def _importar(self):
        """Lê as postagens antigas dos canais de origem dos repasses e registra os preços com a data original."""
        from telegram_manager import telegram_manager
        dias = int(self._dias.get().split()[0])
        self._btn_importar.configure(state="disabled", text="Importando...")
        self._resumo.configure(text="Lendo histórico dos canais (pode levar alguns minutos)...")

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

    def _salvar_destino(self):
        db.set_config("radar_destino", self._destino.get().strip())
        messagebox.showinfo("Salvo", "Destino do radar salvo.", parent=self)

    def _publicar(self, chave: str, nome: str):
        destino = self._destino.get().strip()
        if not destino:
            messagebox.showwarning("Aviso", "Informe o grupo/canal de destino.", parent=self)
            return
        from telegram_manager import telegram_manager
        conta_id = next(iter(telegram_manager.clients), None)

        def _worker():
            try:
                publicar_oferta(chave, conta_id, destino)
                self.after(0, lambda: messagebox.showinfo("Publicado", f"Oferta publicada:\n{nome[:60]}", parent=self))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: messagebox.showerror("Erro", f"Falha ao publicar: {err}", parent=self))

        threading.Thread(target=_worker, daemon=True).start()
