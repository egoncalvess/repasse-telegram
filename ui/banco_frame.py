"""
Visualizador do banco local (somente leitura). Colunas com segredos aparecem mascaradas.
"""
import re
import sqlite3
import customtkinter as ctk
from tkinter import ttk

from database import DB_PATH

BTN_GRAY = ("#64748b", "#4b5563")
LIMITE = 500
SEGREDO = re.compile(r"hash|token|secret|session|senha|password|cookie", re.IGNORECASE)


def _conectar():
    # mode=ro: impossível alterar o banco por esta tela
    return sqlite3.connect(f"file:{DB_PATH.resolve().as_posix()}?mode=ro", uri=True)


def _mascarar(tabela: str, colunas: list[str], linha: tuple) -> list:
    valores = []
    for col, v in zip(colunas, linha):
        segredo = SEGREDO.search(col) or (tabela == "config" and col == "valor" and SEGREDO.search(str(linha[0])))
        if segredo and v:
            v = "****" + str(v)[-4:] if len(str(v)) > 12 else "****"
        valores.append("" if v is None else str(v)[:300])
    return valores


class BancoFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, corner_radius=0, fg_color=("#f4f6fb", "#0f1115"))
        self._build()

    def _build(self):
        hdr = ctk.CTkFrame(self, fg_color=("#ffffff", "#181b22"), corner_radius=12)
        hdr.pack(fill="x", padx=16, pady=(16, 8))
        ctk.CTkLabel(hdr, text="Banco de Dados", font=("Segoe UI", 18, "bold")).pack(side="left", padx=16, pady=14)
        self._tabela = ctk.StringVar()
        self._menu = ctk.CTkOptionMenu(hdr, variable=self._tabela, values=[""], width=220,
                                       command=lambda _: self._carregar())
        self._menu.pack(side="left", padx=8)
        self._busca = ctk.CTkEntry(hdr, width=200, placeholder_text="Filtrar (qualquer coluna)")
        self._busca.pack(side="left", padx=8)
        self._busca.bind("<Return>", lambda _: self._carregar())
        ctk.CTkButton(hdr, text="↻ Atualizar", width=110, command=self.refresh,
                      fg_color=BTN_GRAY[0], hover_color=BTN_GRAY[1]).pack(side="right", padx=12)
        self._info = ctk.CTkLabel(hdr, text="", font=("Segoe UI", 12), text_color=("#64748b", "#94a3b8"))
        self._info.pack(side="right", padx=8)

        card = ctk.CTkFrame(self, fg_color=("#ffffff", "#181b22"), corner_radius=12)
        card.pack(fill="both", expand=True, padx=16, pady=8)
        self._tree = ttk.Treeview(card, show="headings", style="Banco.Treeview")
        ys = ttk.Scrollbar(card, orient="vertical", command=self._tree.yview)
        xs = ttk.Scrollbar(card, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        ys.pack(side="right", fill="y", pady=8)
        xs.pack(side="bottom", fill="x", padx=8)
        self._tree.pack(fill="both", expand=True, padx=(8, 0), pady=(8, 0))

        ctk.CTkLabel(self, text=f"Somente leitura · mostra até {LIMITE} linhas (mais recentes primeiro) · "
                                f"colunas de senha/token aparecem mascaradas",
                     font=("Segoe UI", 11), text_color=("#64748b", "#94a3b8")).pack(anchor="w", padx=20, pady=(0, 10))

    def _estilo(self):
        escuro = ctk.get_appearance_mode() == "Dark"
        fundo, texto, cab = ("#1e1e1e", "#e5e7eb", "#1e293b") if escuro else ("white", "#111827", "#e2e8f2")
        st = ttk.Style()
        st.theme_use("clam")
        st.configure("Banco.Treeview", background=fundo, fieldbackground=fundo, foreground=texto,
                     rowheight=24, font=("Segoe UI", 10), borderwidth=0)
        st.configure("Banco.Treeview.Heading", background=cab, foreground=texto, font=("Segoe UI", 10, "bold"))
        st.map("Banco.Treeview", background=[("selected", "#1a6fd4")])

    def refresh(self):
        self._estilo()
        with _conectar() as conn:
            tabelas = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        self._menu.configure(values=tabelas)
        if self._tabela.get() not in tabelas:
            self._tabela.set("produtos" if "produtos" in tabelas else tabelas[0])
        self._carregar()

    def _carregar(self):
        tabela = self._tabela.get()
        filtro = self._busca.get().strip()
        with _conectar() as conn:
            colunas = [r[1] for r in conn.execute(f'PRAGMA table_info("{tabela}")')]
            total = conn.execute(f'SELECT COUNT(*) FROM "{tabela}"').fetchone()[0]
            where, params = "", ()
            if filtro:
                where = " WHERE " + " OR ".join(f'CAST("{c}" AS TEXT) LIKE ?' for c in colunas)
                params = (f"%{filtro}%",) * len(colunas)
            linhas = conn.execute(f'SELECT * FROM "{tabela}"{where} ORDER BY rowid DESC LIMIT {LIMITE}',
                                  params).fetchall()

        self._tree.delete(*self._tree.get_children())
        self._tree["columns"] = colunas
        for c in colunas:
            self._tree.heading(c, text=c, anchor="w")
            self._tree.column(c, width=max(80, min(320, len(c) * 12)), anchor="w", stretch=False)
        for linha in linhas:
            self._tree.insert("", "end", values=_mascarar(tabela, colunas, linha))
        self._info.configure(text=f"{len(linhas)} de {total} linhas" + (f" (filtro: {filtro})" if filtro else ""))
