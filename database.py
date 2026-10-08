import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path("data/repasse.db")


def get_conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS contas (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            telefone TEXT    UNIQUE NOT NULL,
            apelido  TEXT,
            session  TEXT,
            status   TEXT    DEFAULT 'desconectada',
            tipo     TEXT    DEFAULT 'telegram'
        );

        CREATE TABLE IF NOT EXISTS repasses (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao        TEXT    NOT NULL,
            conta_id         INTEGER,
            origem_id        TEXT,
            origem_nome      TEXT,
            ativo            INTEGER DEFAULT 1,
            total            INTEGER DEFAULT 0,
            filtros          TEXT    DEFAULT '{}',
            substituicoes    TEXT    DEFAULT '[]',
            delay            INTEGER DEFAULT 1,
            limite_diario    INTEGER DEFAULT 0,
            horario_inicio   TEXT    DEFAULT '00:00',
            horario_fim      TEXT    DEFAULT '00:00',
            termos_bloquear  TEXT    DEFAULT '',
            termos_permitir  TEXT    DEFAULT '',
            FOREIGN KEY(conta_id) REFERENCES contas(id)
        );

        CREATE TABLE IF NOT EXISTS destinos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            repasse_id  INTEGER NOT NULL,
            grupo_id    TEXT,
            grupo_nome  TEXT,
            FOREIGN KEY(repasse_id) REFERENCES repasses(id)
        );

        CREATE TABLE IF NOT EXISTS integracoes (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            nome  TEXT    UNIQUE NOT NULL,
            tipo  TEXT    NOT NULL,
            tag   TEXT    DEFAULT '',
            cookie TEXT    DEFAULT '',
            ativo INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS historico (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            repasse_id  INTEGER,
            data        TEXT,
            destino     TEXT,
            status      TEXT,
            detalhes    TEXT,
            FOREIGN KEY(repasse_id) REFERENCES repasses(id)
        );

        CREATE TABLE IF NOT EXISTS config (
            chave TEXT PRIMARY KEY,
            valor TEXT
        );

        -- Radar de preços: produtos vistos nos canais monitorados e cada preço observado
        CREATE TABLE IF NOT EXISTS produtos (
            chave         TEXT PRIMARY KEY,   -- ex.: ml:3530990045 (ver dedup.chave_produto)
            nome          TEXT NOT NULL,
            loja          TEXT NOT NULL,
            url           TEXT NOT NULL,
            imagem        TEXT,               -- caminho local da foto da oferta
            criado_em     TEXT NOT NULL,
            atualizado_em TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS precos (
            chave    TEXT NOT NULL,
            preco    REAL NOT NULL,
            visto_em TEXT NOT NULL,           -- YYYY-MM-DD HH:MM (hora local)
            origem   TEXT,
            PRIMARY KEY (chave, visto_em)
        );
        CREATE INDEX IF NOT EXISTS idx_precos_visto ON precos(visto_em);

        CREATE TABLE IF NOT EXISTS ofertas_vistas (
            chave    TEXT PRIMARY KEY,
            visto_em TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS publicacoes (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            chave    TEXT,
            destino  TEXT,
            data     TEXT NOT NULL,           -- YYYY-MM-DD HH:MM:SS
            status   TEXT NOT NULL,
            detalhes TEXT
        );
    """)
    conn.commit()
    # Migração automática de banco para adicionar coluna 'tipo' caso não exista
    try:
        conn.execute("ALTER TABLE contas ADD COLUMN tipo TEXT DEFAULT 'telegram'")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    # Migração automática de banco para adicionar coluna 'cookie' caso não exista
    try:
        conn.execute("ALTER TABLE integracoes ADD COLUMN cookie TEXT DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    conn.close()


# ── Contas ──────────────────────────────────────────────────────────────────

def listar_contas():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM contas ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def adicionar_conta(telefone: str, apelido: str, tipo: str = "telegram") -> int:
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO contas (telefone, apelido, tipo) VALUES (?,?,?)", (telefone, apelido, tipo))
    conn.commit()
    row = conn.execute("SELECT id FROM contas WHERE telefone=?", (telefone,)).fetchone()
    conn.close()
    return row["id"]


def atualizar_conta(conta_id: int, session: str, status: str):
    conn = get_conn()
    conn.execute("UPDATE contas SET session=?, status=? WHERE id=?", (session, status, conta_id))
    conn.commit()
    conn.close()


def remover_conta(conta_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM contas WHERE id=?", (conta_id,))
    conn.commit()
    conn.close()


# ── Repasses ─────────────────────────────────────────────────────────────────

def listar_repasses():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM repasses ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_repasse(repasse_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM repasses WHERE id=?", (repasse_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def adicionar_repasse(d: dict) -> int:
    conn = get_conn()
    conn.execute("""
        INSERT INTO repasses
            (descricao, conta_id, origem_id, origem_nome, filtros, substituicoes,
             delay, limite_diario, horario_inicio, horario_fim,
             termos_bloquear, termos_permitir)
        VALUES
            (:descricao, :conta_id, :origem_id, :origem_nome, :filtros, :substituicoes,
             :delay, :limite_diario, :horario_inicio, :horario_fim,
             :termos_bloquear, :termos_permitir)
    """, d)
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return rid


def atualizar_repasse(repasse_id: int, d: dict):
    conn = get_conn()
    conn.execute("""
        UPDATE repasses SET
            descricao=:descricao, conta_id=:conta_id,
            origem_id=:origem_id, origem_nome=:origem_nome,
            filtros=:filtros, substituicoes=:substituicoes,
            delay=:delay, limite_diario=:limite_diario,
            horario_inicio=:horario_inicio, horario_fim=:horario_fim,
            termos_bloquear=:termos_bloquear, termos_permitir=:termos_permitir
        WHERE id=:id
    """, {**d, "id": repasse_id})
    conn.commit()
    conn.close()


def toggle_repasse(repasse_id: int, ativo: int):
    conn = get_conn()
    conn.execute("UPDATE repasses SET ativo=? WHERE id=?", (ativo, repasse_id))
    conn.commit()
    conn.close()


def remover_repasse(repasse_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM destinos WHERE repasse_id=?", (repasse_id,))
    conn.execute("DELETE FROM repasses WHERE id=?", (repasse_id,))
    conn.commit()
    conn.close()


def incrementar_repasse(repasse_id: int):
    conn = get_conn()
    conn.execute("UPDATE repasses SET total=total+1 WHERE id=?", (repasse_id,))
    conn.commit()
    conn.close()


# ── Destinos ─────────────────────────────────────────────────────────────────

def listar_destinos(repasse_id: int):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM destinos WHERE repasse_id=?", (repasse_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_destinos(repasse_id: int, destinos: list):
    conn = get_conn()
    conn.execute("DELETE FROM destinos WHERE repasse_id=?", (repasse_id,))
    for d in destinos:
        conn.execute(
            "INSERT INTO destinos (repasse_id, grupo_id, grupo_nome) VALUES (?,?,?)",
            (repasse_id, d["grupo_id"], d["grupo_nome"])
        )
    conn.commit()
    conn.close()


# ── Integrações ───────────────────────────────────────────────────────────────

def listar_integracoes():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM integracoes ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def adicionar_integracao(nome: str, tipo: str, tag: str, cookie: str = ""):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO integracoes (nome, tipo, tag, cookie) VALUES (?,?,?,?)", (nome, tipo, tag, cookie))
    conn.commit()
    conn.close()


def get_integracao(int_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM integracoes WHERE id=?", (int_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def atualizar_integracao(int_id: int, nome: str, tipo: str, tag: str, cookie: str):
    conn = get_conn()
    conn.execute(
        "UPDATE integracoes SET nome=?, tipo=?, tag=?, cookie=? WHERE id=?",
        (nome, tipo, tag, cookie, int_id)
    )
    conn.commit()
    conn.close()


def remover_integracao(int_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM integracoes WHERE id=?", (int_id,))
    conn.commit()
    conn.close()


# ── Histórico ─────────────────────────────────────────────────────────────────

def adicionar_historico(repasse_id: int, destino: str, status: str, detalhes: str = ""):
    conn = get_conn()
    data = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    conn.execute(
        "INSERT INTO historico (repasse_id, data, destino, status, detalhes) VALUES (?,?,?,?,?)",
        (repasse_id, data, destino, status, detalhes)
    )
    conn.commit()
    conn.close()


def listar_historico(repasse_id: int = None, limit: int = 200):
    conn = get_conn()
    if repasse_id:
        rows = conn.execute(
            "SELECT * FROM historico WHERE repasse_id=? ORDER BY id DESC LIMIT ?",
            (repasse_id, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM historico ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Config ───────────────────────────────────────────────────────────────────

def get_config(chave: str, default=None):
    conn = get_conn()
    row = conn.execute("SELECT valor FROM config WHERE chave=?", (chave,)).fetchone()
    conn.close()
    return row["valor"] if row else default


def set_config(chave: str, valor: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO config (chave, valor) VALUES (?,?)", (chave, valor))
    conn.commit()
    conn.close()


# ── Radar de preços ───────────────────────────────────────────────────────────

def registrar_preco(chave: str, nome: str, loja: str, url: str, preco: float, origem: str = "", imagem: str = None):
    """Upsert do produto + uma observação de preço (mesmo minuto não duplica)."""
    agora = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = get_conn()
    conn.execute("""
        INSERT INTO produtos (chave, nome, loja, url, imagem, criado_em, atualizado_em)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chave) DO UPDATE SET
            nome = excluded.nome, url = excluded.url, atualizado_em = excluded.atualizado_em,
            imagem = COALESCE(excluded.imagem, produtos.imagem)
    """, (chave, nome, loja, url, imagem, agora, agora))
    conn.execute("INSERT OR IGNORE INTO precos (chave, preco, visto_em, origem) VALUES (?, ?, ?, ?)",
                 (chave, preco, agora, origem))
    conn.execute("DELETE FROM precos WHERE visto_em < date('now', 'localtime', '-180 days')")
    conn.commit()
    conn.close()


def tem_imagem(chave: str) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT imagem FROM produtos WHERE chave=?", (chave,)).fetchone()
    conn.close()
    return bool(row and row["imagem"])


def menores_precos_do_dia(limit: int = 50, chave: str = None):
    """
    Produtos com preço visto hoje, comparados ao próprio histórico (menor preço por dia, 90 dias):
    minimo/media/dias = dias anteriores a hoje. Ordena pela maior queda em relação à média.
    """
    conn = get_conn()
    rows = conn.execute(f"""
        WITH diario AS (
            SELECT chave, date(visto_em) AS dia, MIN(preco) AS preco
            FROM precos WHERE visto_em >= date('now', 'localtime', '-90 days')
            GROUP BY chave, dia),
        hoje AS (SELECT chave, preco FROM diario WHERE dia = date('now', 'localtime')),
        antes AS (SELECT chave, MIN(preco) AS minimo, AVG(preco) AS media, COUNT(*) AS dias
                  FROM diario WHERE dia < date('now', 'localtime') GROUP BY chave)
        SELECT p.*, h.preco AS preco_hoje, a.minimo, a.media, COALESCE(a.dias, 0) AS dias
        FROM hoje h JOIN produtos p USING (chave) LEFT JOIN antes a USING (chave)
        {"WHERE p.chave = ?" if chave else ""}
        ORDER BY a.media IS NULL, (a.media - h.preco) / a.media DESC
        LIMIT ?
    """, ((chave,) if chave else ()) + (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def resumo_radar() -> dict:
    conn = get_conn()
    r = conn.execute("""
        SELECT (SELECT COUNT(*) FROM produtos) AS produtos,
               (SELECT COUNT(*) FROM precos WHERE visto_em >= date('now', 'localtime')) AS precos_hoje
    """).fetchone()
    conn.close()
    return dict(r)


def registrar_publicacao(chave: str, destino: str, status: str, detalhes: str = ""):
    conn = get_conn()
    conn.execute("INSERT INTO publicacoes (chave, destino, data, status, detalhes) VALUES (?, ?, ?, ?, ?)",
                 (chave, destino, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), status, detalhes))
    conn.commit()
    conn.close()


def contar_envios_hoje() -> int:
    """Repasses com sucesso + ofertas publicadas pelo radar hoje."""
    conn = get_conn()
    repasses = conn.execute("SELECT COUNT(*) FROM historico WHERE status='Sucesso' AND data LIKE ?",
                            (datetime.now().strftime("%d/%m/%Y") + "%",)).fetchone()[0]
    radar = conn.execute("SELECT COUNT(*) FROM publicacoes WHERE status='enviado' AND data >= date('now', 'localtime')"
                         ).fetchone()[0]
    conn.close()
    return repasses + radar


# ── Deduplicação de ofertas ───────────────────────────────────────────────────

def ofertas_recentes(chaves, horas: int = 24) -> set:
    """Quais dessas chaves de produto já foram publicadas nas últimas X horas."""
    if not chaves:
        return set()
    conn = get_conn()
    marks = ",".join("?" * len(chaves))
    rows = conn.execute(
        f"SELECT chave FROM ofertas_vistas WHERE chave IN ({marks}) AND visto_em >= datetime('now', 'localtime', ?)",
        (*chaves, f"-{horas} hours")).fetchall()
    conn.close()
    return {r["chave"] for r in rows}


def marcar_ofertas(chaves):
    conn = get_conn()
    conn.executemany("INSERT OR REPLACE INTO ofertas_vistas (chave, visto_em) VALUES (?, datetime('now', 'localtime'))",
                     [(c,) for c in chaves])
    conn.execute("DELETE FROM ofertas_vistas WHERE visto_em < datetime('now', 'localtime', '-30 days')")
    conn.commit()
    conn.close()
