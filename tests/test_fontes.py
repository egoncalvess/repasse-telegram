"""
Fontes de busca sem rede: respostas simuladas para token, limites, bloqueios, cache, robots.txt e o
formato das chaves (iguais às de dedup.chave_produto para o mesmo produto vindo de um canal).
"""
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database as db  # noqa: E402
import dedup  # noqa: E402
import fontes  # noqa: E402
from fontes.base import Busca, Fonte, FonteBloqueada, FonteIndisponivel  # noqa: E402
from fontes.http import USER_AGENT, ClienteHTTP  # noqa: E402
from fontes.mercadolivre import MercadoLivre  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(nome):
    return json.loads((FIXTURES / nome).read_text(encoding="utf-8"))


class Resp:
    def __init__(self, status=200, corpo=None, headers=None, texto=None):
        self.status_code = status
        self._corpo = corpo
        self.headers = headers or {"Content-Type": "application/json"}
        self.text = texto if texto is not None else json.dumps(corpo)

    def json(self):
        if self._corpo is None:
            raise ValueError("sem json")
        return self._corpo


class Sessao:
    """requests.Session falsa: rotas por caminho; cada rota é uma lista de respostas (a última se repete)."""

    def __init__(self, rotas):
        self.rotas = {k: list(v) if isinstance(v, list) else [v] for k, v in rotas.items()}
        self.chamadas = []

    def request(self, metodo, url, params=None, data=None, headers=None, timeout=None):
        caminho = urlparse(url).path
        self.chamadas.append({"metodo": metodo, "caminho": caminho, "params": params, "data": data,
                              "headers": headers, "timeout": timeout})
        fila = self.rotas.get(caminho)
        if not fila:
            return Resp(404, {"message": "not found"})
        return fila.pop(0) if len(fila) > 1 else fila[0]

    def caminhos(self):
        return [c["caminho"] for c in self.chamadas]


class Relogio:
    def __init__(self):
        self.t = 1000.0
        self.esperas = []

    def __call__(self):
        return self.t

    def dormir(self, s):
        self.esperas.append(s)
        self.t += s


@pytest.fixture(autouse=True)
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "repasse.db")
    db.init_db()
    db.set_config("ml_client_id", "cid")
    db.set_config("ml_client_secret", "segredo")


def conectar_ml(token="A1", exp_em=3600, refresh="R1"):
    db.set_config("ml_token", token)
    db.set_config("ml_token_exp", str(time.time() + exp_em))
    db.set_config("ml_token_origem", "usuario")
    db.set_config("ml_refresh_token", refresh)


def ml_com(rotas):
    ml = MercadoLivre()
    rel = Relogio()
    sessao = Sessao(rotas)
    ml.http = ClienteHTTP(ml, sessao=sessao, relogio=rel, dormir=rel.dormir)
    return ml, sessao, rel


TOKEN_NOVO = Resp(200, {"access_token": "A2", "refresh_token": "R2", "expires_in": 21600, "token_type": "Bearer"})
BUSCA = {"/products/search": Resp(200, fixture("ml_products_search.json")),
         "/products/MLB21278806/items": Resp(200, fixture("ml_product_items.json"))}


# ── Token ─────────────────────────────────────────────────────────────────────

def test_token_expirado_renova_pelo_refresh_token_e_guarda_o_novo():
    conectar_ml(exp_em=-10)
    ml, sessao, _ = ml_com({"/oauth/token": TOKEN_NOVO, **BUSCA})
    ml.buscar(Busca("termo", "mouse"))
    post = sessao.chamadas[0]
    assert post["caminho"] == "/oauth/token" and post["data"]["grant_type"] == "refresh_token"
    assert post["data"]["refresh_token"] == "R1"
    assert sessao.chamadas[1]["headers"]["Authorization"] == "Bearer A2"
    assert db.get_config("ml_refresh_token") == "R2"


def test_401_renova_o_token_uma_vez_e_repete_a_chamada():
    conectar_ml()
    ml, sessao, _ = ml_com({"/oauth/token": TOKEN_NOVO,
                            "/products/search": [Resp(401, {"message": "invalid_token"}),
                                                 Resp(200, {"results": []})]})
    assert ml.buscar(Busca("termo", "mouse")) == []
    assert sessao.caminhos() == ["/products/search", "/oauth/token", "/products/search"]
    assert sessao.chamadas[2]["headers"]["Authorization"] == "Bearer A2"
    assert db.endpoints_da_fonte("ml")["/products/search"]["status"] == "ok"


def test_token_de_app_antigo_e_ignorado_sem_login_do_usuario():
    db.set_config("ml_token", "token_client_credentials")
    db.set_config("ml_token_exp", str(time.time() + 3600))
    ml, sessao, _ = ml_com({})
    with pytest.raises(FonteBloqueada, match="não conectado"):
        ml.buscar(Busca("termo", "mouse"))
    assert sessao.chamadas == []


def test_refresh_token_revogado_desconecta_e_pausa_a_fonte():
    conectar_ml(exp_em=-10)
    ml, _, _ = ml_com({"/oauth/token": Resp(400, {"error": "invalid_grant", "message": "invalid_grant"})})
    with pytest.raises(FonteBloqueada):
        ml.buscar(Busca("termo", "mouse"))
    assert db.get_config("ml_refresh_token") == ""
    assert "Conecte de novo" in fontes.pausada("ml")


def test_conectar_troca_o_codigo_da_url_de_retorno():
    ml, sessao, _ = ml_com({"/oauth/token": TOKEN_NOVO})
    ml.conectar("https://www.google.com/?code=TG-abc-123")
    assert sessao.chamadas[0]["data"]["grant_type"] == "authorization_code"
    assert sessao.chamadas[0]["data"]["code"] == "TG-abc-123"
    assert ml.conectado() and db.get_config("ml_refresh_token") == "R2"


# ── Limites e bloqueios ───────────────────────────────────────────────────────

def test_429_espera_o_retry_after_e_tenta_de_novo():
    conectar_ml()
    ml, sessao, rel = ml_com({"/products/search": [Resp(429, {"message": "too many"}, {"Retry-After": "5"}),
                                                   Resp(200, {"results": []})]})
    ml.buscar(Busca("termo", "mouse"))
    assert rel.esperas == [5.0]
    assert sessao.caminhos().count("/products/search") == 2


def test_5xx_usa_backoff_exponencial_e_tres_falhas_abrem_o_circuito():
    conectar_ml()
    ml, sessao, rel = ml_com({"/products/search": Resp(503, {"message": "indisponivel"})})
    for _ in range(3):
        with pytest.raises(FonteIndisponivel):
            ml.buscar(Busca("termo", "mouse"))
    assert len(sessao.chamadas) == 9                       # 3 buscas x 3 tentativas
    assert 2 <= rel.esperas[0] < 4 and 4 <= rel.esperas[1] < 6   # 2s, 4s (+ jitter < 2s)
    with pytest.raises(FonteIndisponivel, match="em pausa"):
        ml.buscar(Busca("termo", "mouse"))
    assert len(sessao.chamadas) == 9                       # circuito aberto: nem tenta


def test_403_bloqueia_o_endpoint_ate_um_teste_manual():
    conectar_ml()
    ml, sessao, _ = ml_com({"/products/search": Resp(403, {"message": "At least one policy returned UNAUTHORIZED."})})
    with pytest.raises(FonteBloqueada, match="recusou acesso"):
        ml.buscar(Busca("termo", "mouse"))
    assert db.endpoints_da_fonte("ml")["/products/search"]["status"] == "bloqueado"

    with pytest.raises(FonteBloqueada, match="bloqueado desde"):
        ml.buscar(Busca("termo", "mouse"))
    assert sessao.caminhos().count("/products/search") == 1   # não insiste

    sessao.rotas.update({"/products/search": [Resp(200, fixture("ml_products_search.json"))],
                         "/oauth/token": [TOKEN_NOVO]})
    resultado = ml.testar()
    assert resultado["endpoints"]["/products/search"] == "ok"
    assert db.endpoints_da_fonte("ml")["/products/search"]["status"] == "ok"


def test_endpoint_fora_da_lista_aprovada_nunca_e_chamado():
    conectar_ml()
    ml, sessao, _ = ml_com({})
    with pytest.raises(ValueError, match="não aprovado"):
        ml._get("/sites/MLB/search", "/sites/MLB/search", params={"q": "x"})
    assert sessao.chamadas == []


def test_limite_de_requisicoes_por_minuto_espera_a_janela():
    conectar_ml()
    db.set_config("fonte_ml_req_por_minuto", "2")
    ml, sessao, rel = ml_com({"/categories/MLB1648": Resp(200, {"id": "MLB1648"})})
    for _ in range(3):
        ml._get("/categories/{id}", "/categories/MLB1648")
    assert len(sessao.chamadas) == 3
    assert rel.esperas == [60.0]


def test_cache_evita_repetir_a_mesma_chamada():
    conectar_ml()
    ml, sessao, _ = ml_com(BUSCA)
    ml.buscar(Busca("termo", "mouse"))
    ml.buscar(Busca("termo", "mouse"))
    assert sessao.caminhos().count("/products/search") == 1


def test_cada_chamada_vai_para_api_chamadas_e_as_antigas_expiram():
    conectar_ml()
    conn = db.get_conn()
    conn.execute("INSERT INTO api_chamadas (fonte, endpoint, status, ms, criado_em) "
                 "VALUES ('ml', '/x', 200, 1, datetime('now', 'localtime', '-31 days'))")
    conn.commit()
    conn.close()
    ml, _, _ = ml_com({"/categories/MLB1648": Resp(200, {"id": "MLB1648"})})
    ml._get("/categories/{id}", "/categories/MLB1648")
    conn = db.get_conn()
    linhas = [dict(r) for r in conn.execute("SELECT fonte, endpoint, status FROM api_chamadas")]
    conn.close()
    assert linhas == [{"fonte": "ml", "endpoint": "/categories/{id}", "status": 200}]
    assert db.contar_chamadas_api("ml", 1) == 1


# ── Resultado da busca ────────────────────────────────────────────────────────

def test_busca_por_termo_usa_o_menor_preco_e_so_preco_original_real():
    conectar_ml()
    ml, _, _ = ml_com(BUSCA)
    [p] = ml.buscar(Busca("termo", "mouse"))      # o 2º produto não tem anúncio ativo (404)
    assert p.preco == 54.9 and p.preco_original == 79.9 and p.frete_gratis
    assert p.url == "https://www.mercadolivre.com.br/p/MLB21278806"
    assert p.imagem_url.startswith("https://") and p.loja == "Mercado Livre"


def test_chave_da_api_e_igual_a_do_mesmo_produto_vindo_de_um_canal():
    conectar_ml()
    ml, _, _ = ml_com({**BUSCA, "/highlights/MLB/category/MLB1648": Resp(200, fixture("ml_highlights.json")),
                       "/products/MLB21278806": Resp(200, {"id": "MLB21278806", "name": "Mouse", "pictures": []}),
                       "/items": Resp(200, fixture("ml_items.json"))})
    [catalogo] = ml.buscar(Busca("termo", "mouse"))
    assert catalogo.chave == dedup.chave_produto(
        "https://www.mercadolivre.com.br/mouse-sem-fio-exemplo/p/MLB21278806?pdp_filters=item_id") == "ml:21278806"

    por_categoria = {p.chave: p for p in ml.buscar(Busca("categoria", "MLB1648"))}
    anuncio = por_categoria["ml:4964975723"]
    assert anuncio.chave == dedup.chave_produto("https://produto.mercadolivre.com.br/MLB-4964975723-mouse-_JM")
    assert anuncio.preco == 59.9 and anuncio.preco_original == 89.9
    assert "ml:21278806" in por_categoria


# ── Fonte tipo scraping ───────────────────────────────────────────────────────

class LojaExemplo(Fonte):
    id, nome, loja, tipo = "ex", "Loja Exemplo", "exemplo", "scraping"
    req_por_minuto = 10

    def buscar(self, busca):
        return []

    def testar(self):
        return {"ok": True, "endpoints": {}, "mensagem": ""}


def loja_com(rotas):
    f = LojaExemplo()
    rel = Relogio()
    sessao = Sessao(rotas)
    f.http = ClienteHTTP(f, sessao=sessao, relogio=rel, dormir=rel.dormir)
    return f, sessao


ROBOTS = Resp(200, None, {"Content-Type": "text/plain"}, "User-agent: *\nDisallow: /busca\n")


def test_robots_txt_bloqueando_impede_a_requisicao():
    f, sessao = loja_com({"/robots.txt": ROBOTS, "/busca": Resp(200, None, {}, "<html></html>")})
    with pytest.raises(FonteBloqueada, match="robots.txt"):
        f.http.get("https://loja.exemplo/busca?q=tv", "/busca")
    assert sessao.caminhos() == ["/robots.txt"]
    with pytest.raises(FonteBloqueada):
        f.http.get("https://loja.exemplo/busca?q=radio", "/busca")
    assert sessao.caminhos() == ["/robots.txt"]       # robots.txt em cache


def test_scraping_usa_user_agent_honesto_e_pagina_permitida_passa():
    f, sessao = loja_com({"/robots.txt": ROBOTS, "/ofertas": Resp(200, None, {"Content-Type": "text/html"}, "<p>ok</p>")})
    assert f.http.get("https://loja.exemplo/ofertas", "/ofertas") == "<p>ok</p>"
    assert all(c["headers"]["User-Agent"] == USER_AGENT for c in sessao.chamadas)


@pytest.mark.parametrize("resp", [
    Resp(200, None, {"Content-Type": "text/html"}, "<div class='g-recaptcha'>Confirme que não é um robô</div>"),
    Resp(403, None, {"Content-Type": "text/html"}, "Forbidden"),
    Resp(429, None, {"Content-Type": "text/html"}, "Slow down"),
])
def test_scraping_para_a_fonte_no_primeiro_bloqueio(resp):
    f, sessao = loja_com({"/robots.txt": ROBOTS, "/ofertas": resp})
    avisos = []
    fontes.ao_bloquear(lambda fid, txt: avisos.append(fid))
    with pytest.raises(FonteBloqueada):
        f.http.get("https://loja.exemplo/ofertas", "/ofertas")
    assert fontes.pausada("ex") and "ex" in avisos
    with pytest.raises(FonteBloqueada, match="pausada"):
        f.http.get("https://loja.exemplo/ofertas", "/ofertas")
    assert sessao.caminhos().count("/ofertas") == 1    # sem nova tentativa
