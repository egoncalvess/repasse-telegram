"""
Testes integrados da Camada Web (Fase 1 e Fase 2):
- Índices SQLite, PRAGMAs, expurgo fora do caminho quente e latência < 200ms no comparador.
- Segurança: setup local vs bloqueio remoto sem senha, login PBKDF2, rate-limit, CSRF, mascaramento de segredos e bloqueio de path traversal.
- Rotas funcionais: Home Comparador (termo, link ao vivo, busca ao vivo), Detalhe 90d SVG, Ofertas/Fila do Piloto e Buscas Automáticas.
"""
import concurrent.futures
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import comparador  # noqa: E402
import database as db  # noqa: E402
import fontes  # noqa: E402
from fontes.base import ProdutoEncontrado  # noqa: E402
from web import auth  # noqa: E402
from web.app import app  # noqa: E402


@pytest.fixture(autouse=True)
def ambiente_isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "repasse.db")
    monkeypatch.delenv("WEB_PASSWORD", raising=False)
    auth.resetar_rate_limit()
    db.init_db()


def _extrair_csrf(html_txt: str) -> str:
    m = re.search(r'name="csrf_token"\s+value="([0-9a-f]+)"', html_txt)
    assert m, "Token CSRF não encontrado no HTML"
    return m.group(1)


def _cliente_autenticado(senha: str = "senhaForte123") -> TestClient:
    auth.definir_senha_web(senha)
    client = TestClient(app)
    r = client.post("/login", data={"senha": senha, "next": "/"}, follow_redirects=False)
    assert r.status_code == 303
    assert auth.COOKIE_NOME in r.cookies
    return client


# ── Fase 1: SQLite, Índices, Concorrência e Performance ───────────────────────

def test_indices_pragmas_e_expurgo_desacoplado():
    conn = db.get_conn()
    sync = conn.execute("PRAGMA synchronous;").fetchone()[0]
    busy = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
    idxs = {r["name"] for r in conn.execute("PRAGMA index_list('precos')").fetchall()}
    idxs_prod = {r["name"] for r in conn.execute("PRAGMA index_list('produtos')").fetchall()}
    conn.close()

    assert sync == 1  # NORMAL = 1
    assert busy == 30000
    assert "idx_precos_chave_visto" in idxs
    assert "idx_produtos_loja" in idxs_prod

    antigo = datetime.now() - timedelta(days=200)
    db.registrar_preco("ml:antigo", "Item Antigo", "Mercado Livre", "https://ml/1", 99.0, visto_em=antigo)
    db.registrar_preco("ml:novo", "Item Novo", "Mercado Livre", "https://ml/2", 89.0)
    # Fora do caminho quente: continua gravado até a manutenção rodar limpar_precos_antigos
    removidos = db.limpar_precos_antigos(180)
    assert removidos == 1


def test_latencia_comparador_abaixo_de_200ms_e_escrita_concorrente():
    agora = datetime.now().replace(hour=12, minute=0)
    conn = db.get_conn()
    prods = []
    precos_rows = []
    for i in range(600):
        chave = f"ml:{100000 + i}"
        nome = f"Produto Sintético Linha {i}" if i % 50 != 0 else f"Furadeira Impacto Bosch {i}W"
        prods.append((chave, nome, "Mercado Livre", f"https://ml/{i}", None, "2026-11-01 10:00", "2026-11-18 10:00"))
        for d in (0, 3, 10, 25):
            dt = (agora - timedelta(days=d)).strftime("%Y-%m-%d %H:%M")
            precos_rows.append((chave, 250.0 + (i % 40) - d, dt, "teste", None))
    conn.executemany("INSERT INTO produtos VALUES (?, ?, ?, ?, ?, ?, ?)", prods)
    conn.executemany("INSERT INTO precos VALUES (?, ?, ?, ?, ?)", precos_rows)
    conn.commit()
    conn.close()

    t0 = time.perf_counter()
    res = comparador.comparar("furadeira bosch")
    ms = (time.perf_counter() - t0) * 1000
    assert res["total"] == 12
    assert ms < 200, f"Comparador demorou {ms:.1f}ms (esperado < 200ms)"

    # Teste de concorrência real: escritas simultâneas de preços + leituras do comparador sem database is locked
    def _gravar(idx: int):
        db.registrar_preco(f"fc:{idx}", f"Furadeira Bosch Concorrente {idx}", "Ferreira Costa", f"https://fc/{idx}", 199.9 + idx)

    def _ler(_idx: int):
        return comparador.comparar("furadeira bosch")["total"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(_gravar if k % 2 == 0 else _ler, k) for k in range(24)]
        for f in futs:
            f.result(timeout=10)


# ── Fase 1: Segurança, Setup Local, Rate-Limit, CSRF e Mascaramento ───────────

def test_fluxo_setup_local_vs_bloqueio_remoto_sem_senha():
    client = TestClient(app)
    assert client.get("/health").json() == {"ok": True}

    # Acesso remoto simulado antes de existir senha -> 403 bloqueado
    remoto = client.get("/", headers={"X-Forwarded-For": "192.168.1.44"}, follow_redirects=False)
    assert remoto.status_code == 403
    assert "Defina a senha no computador primeiro" in remoto.text

    # Acesso local sem senha -> redireciona para /setup-senha e permite definir
    local_get = client.get("/", follow_redirects=False)
    assert local_get.status_code == 303
    assert local_get.headers["location"] == "/setup-senha"

    setup_ok = client.post(
        "/setup-senha",
        data={"senha": "minhaSenha99", "confirmar": "minhaSenha99"},
        follow_redirects=False,
    )
    assert setup_ok.status_code == 303
    assert setup_ok.headers["location"] == "/"
    assert auth.tem_senha_web()
    assert auth.verificar_senha_web("minhaSenha99")


def test_login_redirect_rate_limit_csrf_segredos_e_path_traversal(tmp_path):
    auth.definir_senha_web("correta123")
    anon = TestClient(app)

    # Sem cookie redireciona ao /login
    r = anon.get("/ofertas", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")

    # 5 falhas retornam 401; a 6ª falha bate no rate-limit 429
    for _ in range(5):
        bad = anon.post("/login", data={"senha": "errada"}, headers={"X-Forwarded-For": "10.0.0.9"})
        assert bad.status_code == 401
    bloqueado = anon.post("/login", data={"senha": "correta123"}, headers={"X-Forwarded-For": "10.0.0.9"})
    assert bloqueado.status_code == 429

    # Cliente autenticado em outro IP: POST sem CSRF é rejeitado com 403
    client = _cliente_autenticado("correta123")
    sem_csrf = client.post("/ofertas/descartar", data={"chave": "ml:1"})
    assert sem_csrf.status_code == 403

    # Mascaramento de segredos
    mascarado = auth.mascarar_config({
        "api_id": "12345",
        "api_hash": "segredo_hash",
        "bot_token": "999:AAABBB",
        "session": "1BVtsOHoBu...",
        "web_password_hash": db.get_config("web_password_hash"),
        "theme": "dark",
    })
    assert mascarado["api_id"] == "12345"
    assert mascarado["theme"] == "dark"
    for k in ("api_hash", "bot_token", "session", "web_password_hash"):
        assert mascarado[k] == "••••••••"

    # Proteção contra path traversal em /imagens/
    imgs = tmp_path / "imagens"
    imgs.mkdir(parents=True, exist_ok=True)
    (imgs / "foto_ok.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (tmp_path / "segredo.jpg").write_bytes(b"nao-pode")

    assert client.get("/imagens/foto_ok.jpg").status_code == 200
    assert client.get("/imagens/..%2Fsegredo.jpg").status_code == 404
    assert client.get("/imagens/repasse.db").status_code == 404


# ── Fase 2: Rotas Web do Comparador, Produto 90d, Ofertas/Fila e Buscas ───────

def test_rotas_comparador_termo_link_e_busca_ao_vivo(monkeypatch):
    agora = datetime.now().replace(hour=9, minute=0)
    for dias, valor in ((12, 3299.0), (5, 2999.0), (0, 2799.0)):
        db.registrar_preco(
            "mgl:gel1",
            "Geladeira Midea Frost Free 347L",
            "Magalu",
            "https://www.magazineluiza.com.br/geladeira/p/gel1/",
            valor,
            visto_em=agora - timedelta(days=dias),
        )
    db.registrar_preco(
        "fc:658753",
        "Geladeira Midea Frost Free Inox",
        "Ferreira Costa",
        "https://www.ferreiracosta.com/produto/658753/geladeira-midea",
        2899.0,
        visto_em=agora - timedelta(days=2),
    )

    fc = fontes.get("fc")
    ml = fontes.get("ml")
    lido_fc = ProdutoEncontrado(
        chave="fc:658753",
        nome="Geladeira Midea Frost Free Inox",
        url="https://www.ferreiracosta.com/produto/658753/geladeira-midea",
        preco=2699.0,
        preco_original=3199.0,
        loja="Ferreira Costa",
    )
    lido_ml = ProdutoEncontrado(
        chave="ml:777888",
        nome="Geladeira Midea Frost Free Smart",
        url="https://produto.mercadolivre.com.br/MLB-777888",
        preco=2649.0,
        preco_original=3099.0,
        loja="Mercado Livre",
    )
    monkeypatch.setattr(fc, "buscar", lambda busca: [lido_fc])
    monkeypatch.setattr(ml, "buscar", lambda busca: [lido_ml])
    fontes.definir_ativa("fc", True)
    fontes.definir_ativa("ml", True)

    client = _cliente_autenticado()

    # 1. Home vazia (dashboard com quedas do dia)
    home = client.get("/")
    assert home.status_code == 200
    assert "Geladeira Midea Frost Free 347L" in home.text

    # 2. Busca por termo no histórico
    termo_resp = client.get("/?q=geladeira+midea")
    assert termo_resp.status_code == 200
    assert "Menor preço atual por loja" in termo_resp.text
    assert "Magalu" in termo_resp.text
    assert "Ferreira Costa" in termo_resp.text

    # 3. Busca ao vivo nas fontes ativas
    csrf = _extrair_csrf(termo_resp.text)
    vivo = client.post("/comparar/ao-vivo", data={"termo": "geladeira midea", "csrf_token": csrf}, follow_redirects=True)
    assert vivo.status_code == 200
    assert "R$ 2.649,00" in vivo.text

    # 4. Consulta por URL direta + gráfico SVG de 90 dias
    link_resp = client.get("/?q=https://www.ferreiracosta.com/produto/658753/geladeira-midea")
    assert link_resp.status_code == 200
    assert '<svg class="price-chart"' in link_resp.text
    assert "R$ 2.699,00" in link_resp.text

    # 5. Página de detalhe do produto + monitorar
    det = client.get("/produto?chave=fc%3A658753")
    assert det.status_code == 200
    assert "Curva de preço (últimos 90 dias)" in det.text
    csrf_det = _extrair_csrf(det.text)
    mon = client.post("/produto/monitorar", data={"chave": "fc:658753", "csrf_token": csrf_det}, follow_redirects=True)
    assert mon.status_code == 200
    assert "Monitorando" in mon.text


def test_ofertas_fila_publicacao_sem_duplicar_sessao_e_crud_buscas(monkeypatch):
    import oferta
    publicados = []

    def _fake_publicar(chave, conta_id, destino, timeout=60, origem="manual"):
        publicados.append((chave, destino, origem))

    monkeypatch.setattr(oferta, "publicar_oferta", _fake_publicar)
    db.set_config("radar_destino", "-100999888")
    db.registrar_preco("ml:999", "Parafusadeira Makita 12V", "Mercado Livre", "https://produto.mercadolivre.com.br/MLB-999", 299.0, preco_original=429.0)
    fila_id = db.adicionar_fila("ml:999")

    client = _cliente_autenticado()

    # Fila de aprovação do Piloto
    pag_fila = client.get("/ofertas?aba=fila")
    assert pag_fila.status_code == 200
    assert "Parafusadeira Makita 12V" in pag_fila.text
    csrf = _extrair_csrf(pag_fila.text)

    aprov = client.post(f"/ofertas/fila/{fila_id}/aprovar", data={"csrf_token": csrf}, follow_redirects=True)
    assert aprov.status_code == 200
    assert publicados == [("ml:999", "-100999888", "fila_web")]
    assert db.get_fila(fila_id)["status"] == "aprovada"

    # CRUD de Buscas Automáticas
    pag_buscas = client.get("/buscas")
    assert pag_buscas.status_code == 200
    csrf_b = _extrair_csrf(pag_buscas.text)

    nova = client.post(
        "/buscas/nova",
        data={
            "fonte_id": "ml",
            "tipo": "termo",
            "nome": "Furadeiras",
            "valor": "furadeira",
            "intervalo_min": "45",
            "preco_max": "500",
            "csrf_token": csrf_b,
        },
        follow_redirects=True,
    )
    assert nova.status_code == 200
    buscas_lista = db.listar_buscas()
    assert len(buscas_lista) == 1 and buscas_lista[0]["nome"] == "Furadeiras"
    bid = buscas_lista[0]["id"]

    client.post(f"/buscas/{bid}/toggle", data={"csrf_token": csrf_b})
    assert db.get_busca(bid)["ativo"] == 0

    client.post(f"/buscas/{bid}/remover", data={"csrf_token": csrf_b})
    assert db.get_busca(bid) is None
