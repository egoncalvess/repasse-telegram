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

        CREATE TABLE IF NOT EXISTS nicho_produtos (
            id                 TEXT PRIMARY KEY,
            nome               TEXT NOT NULL,
            nicho              TEXT NOT NULL,
            marketplace        TEXT NOT NULL,
            url_original       TEXT NOT NULL,
            url_afiliado       TEXT NOT NULL,
            imagem_url         TEXT,
            preco_atual        REAL,
            menor_preco        REAL,
            menor_preco_data   TEXT,
            ultima_atualizacao TEXT
        );

        CREATE TABLE IF NOT EXISTS nicho_precos_historico (
            produto_id TEXT NOT NULL,
            data       TEXT NOT NULL,
            preco      REAL NOT NULL,
            PRIMARY KEY (produto_id, data),
            FOREIGN KEY(produto_id) REFERENCES nicho_produtos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS nicho_dashboard_stats (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            data        TEXT NOT NULL,
            plataforma  TEXT NOT NULL,
            cliques     INTEGER DEFAULT 0,
            vendas      INTEGER DEFAULT 0,
            faturamento REAL DEFAULT 0.0,
            UNIQUE(data, plataforma)
        );

        CREATE TABLE IF NOT EXISTS nicho_disparos_status (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            data       TEXT NOT NULL,
            produto_id TEXT,
            status     TEXT NOT NULL,
            detalhes   TEXT
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


# ── Nichos e Dashboard ────────────────────────────────────────────────────────

def _parse_price(val) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        # Limpeza de string monetária brasileira
        s = str(val).replace("R$", "").replace(" ", "")
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(".", "") # se não houver vírgula, remove pontos de milhar
        return float(s)
    except Exception:
        return 0.0

def salvar_produto_nicho(p: dict):
    """
    Salva ou atualiza um produto de nicho no banco de dados.
    Calcula automaticamente o menor preço histórico e a data dele.
    p keys: id, nome, nicho, marketplace, url_original, url_afiliado, imagem_url, preco_atual, data_atual (opcional)
    """
    conn = get_conn()
    data_atual = p.get("data_atual") or datetime.now().strftime("%Y-%m-%d")
    preco_atual = _parse_price(p.get("preco_atual")) if p.get("preco_atual") else None
    
    # 1. Busca se produto já existe
    row = conn.execute("SELECT menor_preco, menor_preco_data FROM nicho_produtos WHERE id = ?", (p["id"],)).fetchone()
    
    menor_preco = preco_atual
    menor_preco_data = data_atual
    
    if row:
        hist_menor_preco = row["menor_preco"]
        hist_menor_preco_data = row["menor_preco_data"]
        
        if hist_menor_preco is not None and preco_atual is not None:
            if preco_atual < hist_menor_preco:
                menor_preco = preco_atual
                menor_preco_data = data_atual
            else:
                menor_preco = hist_menor_preco
                menor_preco_data = hist_menor_preco_data
    
    conn.execute("""
        INSERT OR REPLACE INTO nicho_produtos 
            (id, nome, nicho, marketplace, url_original, url_afiliado, imagem_url, preco_atual, menor_preco, menor_preco_data, ultima_atualizacao)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        p["id"],
        p["nome"],
        p["nicho"],
        p["marketplace"],
        p["url_original"],
        p["url_afiliado"],
        p.get("imagem_url"),
        preco_atual,
        menor_preco,
        menor_preco_data,
        data_atual
    ))
    
    # Insere também no histórico de preços se houver preço
    if preco_atual is not None:
        conn.execute("""
            INSERT OR REPLACE INTO nicho_precos_historico (produto_id, data, preco)
            VALUES (?, ?, ?)
        """, (p["id"], data_atual, preco_atual))
        
    conn.commit()
    conn.close()

def adicionar_preco_historico(produto_id: str, preco: float, data_str: str = None):
    conn = get_conn()
    if not data_str:
        data_str = datetime.now().strftime("%Y-%m-%d")
    
    preco = _parse_price(preco)
    
    conn.execute("""
        INSERT OR REPLACE INTO nicho_precos_historico (produto_id, data, preco)
        VALUES (?, ?, ?)
    """, (produto_id, data_str, preco))
    
    # Recalcula o menor preço na tabela de produtos
    rows = conn.execute("SELECT preco, data FROM nicho_precos_historico WHERE produto_id = ? ORDER BY preco ASC, data ASC", (produto_id,)).fetchall()
    if rows:
        menor = rows[0]["preco"]
        menor_data = rows[0]["data"]
        conn.execute("""
            UPDATE nicho_produtos 
            SET preco_atual = ?, menor_preco = ?, menor_preco_data = ?, ultima_atualizacao = ?
            WHERE id = ?
        """, (preco, menor, menor_data, data_str, produto_id))
        
    conn.commit()
    conn.close()

def contar_dias_historico(produto_id: str) -> int:
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM nicho_precos_historico WHERE produto_id=?", (produto_id,)).fetchone()[0]
    conn.close()
    return n

def contar_envios_hoje() -> int:
    """Repasses com sucesso + ofertas de nicho enviadas hoje."""
    conn = get_conn()
    repasses = conn.execute("SELECT COUNT(*) FROM historico WHERE status='Sucesso' AND data LIKE ?",
                            (datetime.now().strftime("%d/%m/%Y") + "%",)).fetchone()[0]
    ofertas = conn.execute("SELECT COUNT(*) FROM nicho_disparos_status WHERE status='enviado' AND data=?",
                           (datetime.now().strftime("%Y-%m-%d"),)).fetchone()[0]
    conn.close()
    return repasses + ofertas

def listar_produtos_nicho(nicho: str = None, order_by: str = None, limit: int = 100):
    conn = get_conn()
    query = "SELECT * FROM nicho_produtos"
    params = []
    
    if nicho and nicho.strip().lower() not in ["todos os nichos", "todos", "all"]:
        query += " WHERE nicho = ?"
        params.append(nicho)
        
    if order_by == "preco_asc":
        query += " ORDER BY preco_atual ASC"
    elif order_by == "preco_desc":
        query += " ORDER BY preco_atual DESC"
    elif order_by == "desconto":
        query += " ORDER BY (menor_preco - preco_atual) DESC" # Produtos com maior desconto histórico
    else:
        query += " ORDER BY ultima_atualizacao DESC"
        
    query += " LIMIT ?"
    params.append(limit)
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def prunar_precos_historicos_90_dias():
    conn = get_conn()
    # Compara strings de datas diretas YYYY-MM-DD
    conn.execute("DELETE FROM nicho_precos_historico WHERE date(data) < date('now', '-90 days')")
    conn.commit()
    conn.close()

def salvar_stats_dashboard(data_str: str, plataforma: str, cliques: int, vendas: int, faturamento: float):
    conn = get_conn()
    conn.execute("""
        INSERT INTO nicho_dashboard_stats (data, plataforma, cliques, vendas, faturamento)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(data, plataforma) DO UPDATE SET
            cliques = excluded.cliques,
            vendas = excluded.vendas,
            faturamento = excluded.faturamento
    """, (data_str, plataforma, cliques, vendas, faturamento))
    conn.commit()
    conn.close()

def listar_stats_dashboard(periodo_dias: int = 30):
    conn = get_conn()
    rows = conn.execute("""
        SELECT data, plataforma, cliques, vendas, faturamento 
        FROM nicho_dashboard_stats 
        WHERE date(data) >= date('now', ?)
        ORDER BY data DESC, plataforma ASC
    """, (f"-{periodo_dias} days",)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def salvar_disparo_status(produto_id: str, data_str: str, status: str, detalhes: str = ""):
    conn = get_conn()
    conn.execute("""
        INSERT INTO nicho_disparos_status (data, produto_id, status, detalhes)
        VALUES (?, ?, ?, ?)
    """, (data_str, produto_id, status, detalhes))
    conn.commit()
    conn.close()

def listar_disparos_hoje():
    conn = get_conn()
    data_str = datetime.now().strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT d.*, p.nome, p.marketplace, p.preco_atual 
        FROM nicho_disparos_status d
        LEFT JOIN nicho_produtos p ON d.produto_id = p.id
        WHERE d.data = ?
        ORDER BY d.id DESC
    """, (data_str,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
