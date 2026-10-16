"""
Visualizador do banco local (somente leitura). Colunas com segredos aparecem mascaradas.
Aberto por Configurações → Dados.
"""
import re
import sqlite3

import customtkinter as ctk

import database as db
from ui import estilo as e

LIMITE = 500
SEGREDO = re.compile(r"hash|token|secret|session|senha|password|cookie", re.IGNORECASE)


def _conectar():
    # mode=ro: impossível alterar o banco por esta tela
    return sqlite3.connect(f"file:{db.DB_PATH.resolve().as_posix()}?mode=ro", uri=True)


def _mascarar(tabela: str, colunas: list[str], linha: tuple) -> list:
    valores = []
    for col, v in zip(colunas, linha):
        segredo = SEGREDO.search(col) or (tabela == "config" and col == "valor" and SEGREDO.search(str(linha[0])))
        if segredo and v:
            v = "****" + str(v)[-4:] if len(str(v)) > 12 else "****"
        valores.append("" if v is None else str(v)[:300])
    return valores


class BancoFrame(ctk.CTkFrame):
    def __init__(self, parent, app=None):
        super().__init__(parent, corner_radius=0, fg_color=e.FUNDO)
        self._app = app
        acoes = e.cabecalho(self, "Banco de dados")
        e.acao(acoes, e.botao_texto(acoes, "Voltar para Configurações",
                                    lambda: app.show_frame("configuracoes") if app else None))
        e.acao(acoes, e.botao(acoes, "Atualizar", self.refresh))

        filtros = ctk.CTkFrame(self, fg_color="transparent")
        filtros.pack(fill="x", padx=e.MARGEM, pady=(0, e.E2))
        self._tabela_nome = ctk.StringVar()
        self._menu = e.menu(filtros, self._tabela_nome, [""], lambda _: self._carregar(), largura=220)
        self._menu.pack(side="left")
        self._busca = e.entrada(filtros, 220, placeholder_text="Filtrar (qualquer coluna)")
        self._busca.pack(side="left", padx=(e.E1, 0))
        self._busca.bind("<Return>", lambda _: self._carregar())
        self._info = e.rotulo(filtros, "", e.F_LEGENDA, secundario=True)
        self._info.pack(side="right")

        e.rotulo(self, f"Somente leitura. Mostra até {LIMITE} linhas, as mais recentes primeiro; colunas de senha e "
                       "token aparecem mascaradas.", e.F_LEGENDA, secundario=True).pack(side="bottom", anchor="w",
                                                                                         padx=e.MARGEM, pady=e.E2)
        self._lista = ctk.CTkFrame(self, fg_color="transparent")
        self._lista.pack(fill="both", expand=True, padx=e.MARGEM)
        self._tabela = None
        self._colunas: list[str] = []

    def refresh(self):
        with _conectar() as conn:
            tabelas = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        self._menu.configure(values=tabelas)
        if self._tabela_nome.get() not in tabelas:
            self._tabela_nome.set("produtos" if "produtos" in tabelas else tabelas[0])
        self._carregar()

    def _carregar(self):
        tabela = self._tabela_nome.get()
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

        if colunas != self._colunas:  # outra tabela: colunas novas (largura fixa, com rolagem horizontal)
            if self._tabela is not None:
                self._tabela.destroy()
            self._tabela = e.Tabela(self._lista, [(c, c, max(96, min(320, len(c) * 12))) for c in colunas], fixa=True)
            self._tabela.pack(fill="both", expand=True)
            self._colunas = colunas
        self._tabela.carregar([_mascarar(tabela, colunas, linha) for linha in linhas])
        self._info.configure(text=f"{len(linhas)} de {total} linhas" + (f" (filtro: {filtro})" if filtro else ""))
