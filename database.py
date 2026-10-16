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

        -- Várias origens por repasse (antes era uma só, em repasses.origem_id)
        CREATE TABLE IF NOT EXISTS repasse_origens (
            repasse_id  INTEGER NOT NULL,
            origem_id   TEXT    NOT NULL,     -- ID marcado (-100… canal/supergrupo, -… grupo)
            origem_nome TEXT,
            PRIMARY KEY (repasse_id, origem_id)
        );

        -- Canais monitorados só para o Radar de Preços (não repassam nada)
        CREATE TABLE IF NOT EXISTS fontes (
            chat_id  TEXT PRIMARY KEY,
            nome     TEXT,
            conta_id INTEGER
        );

        -- Cada requisição das fontes de busca (pasta fontes/): auditoria de limite e saúde, expurgo em 30 dias
        CREATE TABLE IF NOT EXISTS api_chamadas (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            fonte     TEXT    NOT NULL,
            endpoint  TEXT    NOT NULL,       -- modelo do caminho, ex.: /products/{id}/items
            status    INTEGER NOT NULL,       -- HTTP; 0 = sem resposta (rede/timeout)
            ms        INTEGER NOT NULL,
            criado_em TEXT    NOT NULL        -- YYYY-MM-DD HH:MM:SS (hora local)
        );
        CREATE INDEX IF NOT EXISTS idx_api_chamadas_criado ON api_chamadas(criado_em);

        -- Buscas automáticas nas fontes (buscador.py): o que procurar, a cada quanto e as regras de publicação
        CREATE TABLE IF NOT EXISTS buscas (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            fonte_id         TEXT    NOT NULL,       -- id em fontes.registro() ("ml")
            nome             TEXT    NOT NULL,
            tipo             TEXT    NOT NULL,       -- categoria | termo | produto
            valor            TEXT    NOT NULL,
            intervalo_min    INTEGER NOT NULL DEFAULT 60,
            desconto_min_pct REAL    DEFAULT 0,      -- 0 = sem exigência
            preco_max        REAL    DEFAULT 0,      -- 0 = sem teto
            so_frete_gratis  INTEGER DEFAULT 0,
            ativo            INTEGER DEFAULT 1,
            ultima_execucao  TEXT,                   -- YYYY-MM-DD HH:MM:SS (hora local)
            ultimo_status    TEXT
        );

        -- Último resultado de cada produto em cada busca: o piloto aplica as regras da busca que o achou
        CREATE TABLE IF NOT EXISTS busca_resultados (
            busca_id       INTEGER NOT NULL,
            chave          TEXT    NOT NULL,
            preco          REAL    NOT NULL,
            preco_original REAL,
            frete_gratis   INTEGER DEFAULT 0,
            visto_em       TEXT    NOT NULL,
            PRIMARY KEY (busca_id, chave)
        );

        -- Endpoint que respondeu 401/403: fica bloqueado até um novo teste manual da fonte
        CREATE TABLE IF NOT EXISTS fonte_endpoints (
            fonte_id      TEXT NOT NULL,
            endpoint      TEXT NOT NULL,
            status        TEXT NOT NULL,      -- ok | bloqueado
            detalhe       TEXT,
            atualizado_em TEXT NOT NULL,
            PRIMARY KEY (fonte_id, endpoint)
        );

        CREATE TABLE IF NOT EXISTS ofertas_vistas (
            chave    TEXT PRIMARY KEY,
            visto_em TEXT NOT NULL
        );

        -- Mensagens enviadas por repasse em cada dia (limite diário sobrevive a reinícios do app)
        CREATE TABLE IF NOT EXISTS repasse_envios_dia (
            repasse_id INTEGER NOT NULL,
            dia        TEXT    NOT NULL,      -- YYYY-MM-DD (hora local)
            enviadas   INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (repasse_id, dia)
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
    # Migração: origem única antiga -> tabela repasse_origens
    conn.execute("""
        INSERT OR IGNORE INTO repasse_origens (repasse_id, origem_id, origem_nome)
        SELECT id, origem_id, origem_nome FROM repasses
        WHERE origem_id IS NOT NULL AND origem_id != ''
          AND id NOT IN (SELECT repasse_id FROM repasse_origens)
    """)
    conn.commit()
    # Migração automática de banco para adicionar coluna 'cookie' caso não exista
    try:
        conn.execute("ALTER TABLE integracoes ADD COLUMN cookie TEXT DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    # Migração: preço "de" informado pela loja (fontes de busca); NULL nos preços vindos de canais
    try:
        conn.execute("ALTER TABLE precos ADD COLUMN preco_original REAL")
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
    conn.execute("DELETE FROM repasse_origens WHERE repasse_id=?", (repasse_id,))
    conn.execute("DELETE FROM repasse_envios_dia WHERE repasse_id=?", (repasse_id,))
    conn.execute("DELETE FROM repasses WHERE id=?", (repasse_id,))
    conn.commit()
    conn.close()


def incrementar_repasse(repasse_id: int):
    conn = get_conn()
    conn.execute("UPDATE repasses SET total=total+1 WHERE id=?", (repasse_id,))
    conn.commit()
    conn.close()


def enviadas_hoje(repasse_id: int) -> int:
    """Mensagens que o repasse já enviou hoje (base do limite diário)."""
    conn = get_conn()
    row = conn.execute("SELECT enviadas FROM repasse_envios_dia WHERE repasse_id=? AND dia=date('now', 'localtime')",
                       (repasse_id,)).fetchone()
    conn.close()
    return row["enviadas"] if row else 0


def registrar_envio_dia(repasse_id: int):
    conn = get_conn()
    conn.execute("""
        INSERT INTO repasse_envios_dia (repasse_id, dia, enviadas) VALUES (?, date('now', 'localtime'), 1)
        ON CONFLICT(repasse_id, dia) DO UPDATE SET enviadas = enviadas + 1
    """, (repasse_id,))
    conn.execute("DELETE FROM repasse_envios_dia WHERE dia < date('now', 'localtime', '-30 days')")
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


# ── Origens (várias por repasse) e fontes do radar ───────────────────────────

def listar_origens(repasse_id: int):
    conn = get_conn()
    rows = conn.execute("SELECT origem_id, origem_nome FROM repasse_origens WHERE repasse_id=?",
                        (repasse_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_origens(repasse_id: int, origens: list):
    """origens: [{'origem_id', 'origem_nome'}]. Mantém repasses.origem_* como resumo para telas antigas."""
    conn = get_conn()
    conn.execute("DELETE FROM repasse_origens WHERE repasse_id=?", (repasse_id,))
    conn.executemany("INSERT OR IGNORE INTO repasse_origens (repasse_id, origem_id, origem_nome) VALUES (?,?,?)",
                     [(repasse_id, o["origem_id"], o["origem_nome"]) for o in origens])
    resumo = origens[0]["origem_nome"] if len(origens) == 1 else f"{len(origens)} grupos"
    conn.execute("UPDATE repasses SET origem_id=?, origem_nome=? WHERE id=?",
                 (origens[0]["origem_id"] if origens else "", resumo if origens else "", repasse_id))
    conn.commit()
    conn.close()


def listar_fontes():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM fontes ORDER BY nome").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_fontes(conta_id: int, fontes: list):
    """fontes: [{'chat_id', 'nome'}] monitoradas pela conta (substitui a lista dessa conta)."""
    conn = get_conn()
    conn.execute("DELETE FROM fontes WHERE conta_id=?", (conta_id,))
    conn.executemany("INSERT OR REPLACE INTO fontes (chat_id, nome, conta_id) VALUES (?,?,?)",
                     [(f["chat_id"], f["nome"], conta_id) for f in fontes])
    conn.commit()
    conn.close()


def chats_do_radar(conta_id: int) -> dict:
    """{chat_id: nome} que a conta observa para o radar: fontes + origens dos repasses ativos."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT chat_id, nome FROM fontes WHERE conta_id = ?
        UNION
        SELECT o.origem_id, o.origem_nome FROM repasse_origens o
        JOIN repasses r ON r.id = o.repasse_id WHERE r.conta_id = ? AND r.ativo = 1
    """, (conta_id, conta_id)).fetchall()
    conn.close()
    chats = {r[0]: r[1] for r in rows}
    # ID antigo sem prefixo e o mesmo chat com prefixo (-100…/-…): fica só a forma marcada
    return {cid: nome for cid, nome in chats.items()
            if not (cid.isdigit() and (f"-100{cid}" in chats or f"-{cid}" in chats))}


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

def registrar_preco(chave: str, nome: str, loja: str, url: str, preco: float, origem: str = "", imagem: str = None,
                    visto_em: datetime = None, preco_original: float = None):
    """Upsert do produto + uma observação de preço (mesmo minuto não duplica).
    visto_em: data original da postagem (importação de histórico); padrão = agora.
    preco_original: preço "de" informado pela loja (só fontes de busca; nunca inventado)."""
    agora = (visto_em or datetime.now()).strftime("%Y-%m-%d %H:%M")
    conn = get_conn()
    # Importação pode chegar fora de ordem: nome/url só são trocados por uma observação mais recente
    conn.execute("""
        INSERT INTO produtos (chave, nome, loja, url, imagem, criado_em, atualizado_em)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chave) DO UPDATE SET
            nome = CASE WHEN excluded.atualizado_em >= produtos.atualizado_em THEN excluded.nome ELSE produtos.nome END,
            url  = CASE WHEN excluded.atualizado_em >= produtos.atualizado_em THEN excluded.url ELSE produtos.url END,
            atualizado_em = MAX(produtos.atualizado_em, excluded.atualizado_em),
            criado_em = MIN(produtos.criado_em, excluded.criado_em),
            imagem = COALESCE(produtos.imagem, excluded.imagem)
    """, (chave, nome, loja, url, imagem, agora, agora))
    conn.execute("INSERT OR IGNORE INTO precos (chave, preco, visto_em, origem, preco_original) VALUES (?, ?, ?, ?, ?)",
                 (chave, preco, agora, origem, preco_original))
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
        -- menor preço de hoje e o preço "de" da loja na mesma observação (SQLite: coluna nua acompanha o MIN)
        hoje AS (SELECT chave, MIN(preco) AS preco, preco_original FROM precos
                 WHERE visto_em >= date('now', 'localtime') GROUP BY chave),
        antes AS (SELECT chave, MIN(preco) AS minimo, AVG(preco) AS media, COUNT(*) AS dias
                  FROM diario WHERE dia < date('now', 'localtime') GROUP BY chave)
        SELECT p.*, h.preco AS preco_hoje, h.preco_original, a.minimo, a.media, COALESCE(a.dias, 0) AS dias
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


# ── Fontes de busca (pasta fontes/) ───────────────────────────────────────────

def registrar_chamada_api(fonte: str, endpoint: str, status: int, ms: int):
    conn = get_conn()
    conn.execute("INSERT INTO api_chamadas (fonte, endpoint, status, ms, criado_em) "
                 "VALUES (?, ?, ?, ?, datetime('now', 'localtime'))", (fonte, endpoint, status, ms))
    conn.execute("DELETE FROM api_chamadas WHERE criado_em < datetime('now', 'localtime', '-30 days')")
    conn.commit()
    conn.close()


def contar_chamadas_api(fonte: str, minutos: int = 60) -> int:
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM api_chamadas WHERE fonte=? AND criado_em >= datetime('now', 'localtime', ?)",
                     (fonte, f"-{int(minutos)} minutes")).fetchone()[0]
    conn.close()
    return n


def marcar_endpoint(fonte_id: str, endpoint: str, status: str, detalhe: str = ""):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO fonte_endpoints (fonte_id, endpoint, status, detalhe, atualizado_em) "
                 "VALUES (?, ?, ?, ?, datetime('now', 'localtime'))", (fonte_id, endpoint, status, detalhe))
    conn.commit()
    conn.close()


def endpoints_da_fonte(fonte_id: str) -> dict:
    """{endpoint: {status, detalhe, atualizado_em}} do último resultado conhecido."""
    conn = get_conn()
    rows = conn.execute("SELECT endpoint, status, detalhe, atualizado_em FROM fonte_endpoints WHERE fonte_id=?",
                        (fonte_id,)).fetchall()
    conn.close()
    return {r["endpoint"]: dict(r) for r in rows}


def liberar_endpoints(fonte_id: str):
    """Teste manual: endpoints bloqueados voltam a ser tentados (uma vez) pelo próprio teste."""
    conn = get_conn()
    conn.execute("DELETE FROM fonte_endpoints WHERE fonte_id=? AND status='bloqueado'", (fonte_id,))
    conn.commit()
    conn.close()


# ── Buscas automáticas (buscador.py) ──────────────────────────────────────────

CAMPOS_BUSCA = ("fonte_id", "nome", "tipo", "valor", "intervalo_min", "desconto_min_pct", "preco_max",
                "so_frete_gratis", "ativo")


def listar_buscas():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM buscas ORDER BY nome").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_busca(busca_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM buscas WHERE id=?", (busca_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def adicionar_busca(d: dict) -> int:
    campos = [c for c in CAMPOS_BUSCA if c in d]
    conn = get_conn()
    cur = conn.execute(f"INSERT INTO buscas ({', '.join(campos)}) VALUES ({', '.join('?' * len(campos))})",
                       [d[c] for c in campos])
    conn.commit()
    conn.close()
    return cur.lastrowid


def atualizar_busca(busca_id: int, d: dict):
    campos = [c for c in CAMPOS_BUSCA if c in d]
    if not campos:
        return
    conn = get_conn()
    conn.execute(f"UPDATE buscas SET {', '.join(c + '=?' for c in campos)} WHERE id=?",
                 [d[c] for c in campos] + [busca_id])
    conn.commit()
    conn.close()


def remover_busca(busca_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM busca_resultados WHERE busca_id=?", (busca_id,))
    conn.execute("DELETE FROM buscas WHERE id=?", (busca_id,))
    conn.commit()
    conn.close()


def buscas_vencidas():
    """Buscas ativas cujo intervalo já passou desde a última execução (ou que nunca rodaram)."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM buscas WHERE ativo=1 AND (ultima_execucao IS NULL OR
            datetime(ultima_execucao, '+' || MAX(1, intervalo_min) || ' minutes') <= datetime('now', 'localtime'))
        ORDER BY ultima_execucao IS NOT NULL, ultima_execucao
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def marcar_execucao_busca(busca_id: int, status: str):
    conn = get_conn()
    conn.execute("UPDATE buscas SET ultima_execucao=datetime('now', 'localtime'), ultimo_status=? WHERE id=?",
                 (status[:300], busca_id))
    conn.commit()
    conn.close()


def registrar_resultado_busca(busca_id: int, chave: str, preco: float, preco_original: float = None,
                              frete_gratis: bool = False):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO busca_resultados (busca_id, chave, preco, preco_original, frete_gratis, "
                 "visto_em) VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))",
                 (busca_id, chave, preco, preco_original, int(bool(frete_gratis))))
    conn.execute("DELETE FROM busca_resultados WHERE visto_em < datetime('now', 'localtime', '-30 days')")
    conn.commit()
    conn.close()


def buscas_do_produto(chave: str):
    """Buscas que acharam o produto nos últimos 2 dias, com as regras e o último resultado de cada uma."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT b.*, r.preco AS resultado_preco, r.preco_original AS resultado_preco_original,
               r.frete_gratis AS resultado_frete_gratis
        FROM busca_resultados r JOIN buscas b ON b.id = r.busca_id
        WHERE r.chave=? AND r.visto_em >= datetime('now', 'localtime', '-2 days')
    """, (chave,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
