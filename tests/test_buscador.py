"""
Buscador automático sem rede: buscas vencidas, gravação no radar com a mesma chave dos canais,
preço "de" honesto no card, foto em data/imagens e regras da busca aplicadas antes de publicar.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import buscador  # noqa: E402
import database as db  # noqa: E402
import fontes  # noqa: E402
import oferta  # noqa: E402
import radar  # noqa: E402
from fontes.base import Fonte, FonteBloqueada, ProdutoEncontrado  # noqa: E402

URL_CANAL = "https://www.mercadolivre.com.br/mouse-sem-fio-exemplo/p/MLB21278806"


class FonteFalsa(Fonte):
    id, nome, loja = "ml", "Mercado Livre", "mercadolivre"

    def __init__(self, produtos=None, erro=None):
        super().__init__()
        self.produtos, self.erro, self.buscas = produtos or [], erro, []
        self.http.baixar = lambda url, *a, **k: self.fotos.append(url) or b"\xff\xd8jpeg"
        self.fotos = []

    def buscar(self, busca):
        self.buscas.append(busca)
        if self.erro:
            raise self.erro
        return self.produtos

    def testar(self):
        return {"ok": True, "endpoints": {}, "mensagem": ""}


def produto(preco=54.9, original=79.9, frete=True):
    return ProdutoEncontrado(chave="ml:21278806", nome="Mouse Sem Fio Exemplo", url=URL_CANAL, preco=preco,
                             preco_original=original, imagem_url="https://http2.mlstatic.com/D_1.jpg",
                             frete_gratis=frete, categoria="MLB1714", loja="Mercado Livre")


@pytest.fixture(autouse=True)
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "repasse.db")
    monkeypatch.setattr(radar, "PASTA_IMAGENS", tmp_path / "imagens")
    db.init_db()
    fontes.definir_ativa("ml", True)


@pytest.fixture
def fonte(monkeypatch):
    f = FonteFalsa([produto()])
    monkeypatch.setattr(fontes, "_registro", {"ml": f})
    return f


def nova_busca(**campos):
    d = {"fonte_id": "ml", "nome": "Mouses", "tipo": "termo", "valor": "mouse", "intervalo_min": 60} | campos
    return db.get_busca(db.adicionar_busca(d))


def test_busca_grava_no_radar_com_origem_da_fonte_e_preco_original(fonte):
    b = nova_busca()
    assert buscador.executar(b) == "ok: 1 produto(s)"
    conn = db.get_conn()
    preco = dict(conn.execute("SELECT * FROM precos").fetchone())
    conn.close()
    assert preco["origem"] == "fonte:ml" and preco["preco"] == 54.9 and preco["preco_original"] == 79.9
    [p] = db.menores_precos_do_dia()
    assert p["chave"] == "ml:21278806" and p["preco_original"] == 79.9
    b = db.get_busca(b["id"])
    assert b["ultima_execucao"] and b["ultimo_status"] == "ok: 1 produto(s)"


def test_produto_da_api_e_do_canal_caem_na_mesma_chave_do_radar(fonte):
    from datetime import datetime, timedelta
    buscador.executar(nova_busca())
    # precos tem PK (chave, visto_em) por minuto: a postagem do canal é de outro minuto
    registrados = asyncio.run(radar.capturar(None, f"Mouse sem fio por R$ 49,90\n{URL_CANAL}", "Canal X",
                                             visto_em=datetime.now() - timedelta(minutes=1)))
    assert registrados == 1
    conn = db.get_conn()
    produtos = conn.execute("SELECT COUNT(*) FROM produtos").fetchone()[0]
    origens = sorted(r[0] for r in conn.execute("SELECT origem FROM precos"))
    conn.close()
    assert produtos == 1 and origens == ["Canal X", "fonte:ml"]
    assert db.menores_precos_do_dia()[0]["preco_hoje"] == 49.9


def test_foto_vai_para_data_imagens_com_o_nome_do_radar_e_so_uma_vez(fonte):
    buscador.executar(nova_busca())
    buscador.executar(nova_busca(nome="Outra"))
    arquivo = radar.caminho_imagem("ml:21278806")
    assert arquivo.name == "ml_21278806.jpg" and arquivo.read_bytes() == b"\xff\xd8jpeg"
    assert len(fonte.fotos) == 1
    assert db.menores_precos_do_dia()[0]["imagem"] == str(arquivo)


def test_fonte_bloqueada_registra_o_status_sem_derrubar_o_loop(fonte):
    fonte.erro = FonteBloqueada("/products/search recusou acesso (HTTP 403)")
    b = nova_busca()
    assert buscador.executar(b).startswith("bloqueado:")
    assert db.get_busca(b["id"])["ultimo_status"].startswith("bloqueado:")


def test_so_executa_buscas_vencidas_ativas_e_de_fonte_liberada(fonte):
    vencida = nova_busca(nome="Vencida")
    recente = nova_busca(nome="Recente")
    inativa = nova_busca(nome="Inativa", ativo=0)
    db.marcar_execucao_busca(recente["id"], "ok")
    conn = db.get_conn()
    conn.execute("UPDATE buscas SET ultima_execucao=datetime('now', 'localtime', '-61 minutes') WHERE id=?",
                 (vencida["id"],))
    conn.commit()
    conn.close()
    assert [b["nome"] for b in db.buscas_vencidas()] == ["Vencida"]
    assert inativa["id"] not in [b["id"] for b in db.buscas_vencidas()]

    db.set_config("pausado", "1")
    assert buscador.executar_vencidas() == [] and fonte.buscas == []
    db.set_config("pausado", "0")
    fontes.pausar("ml", "teste")
    assert buscador.executar_vencidas() == []
    fontes.retomar("ml")
    fontes.definir_ativa("ml", False)
    assert buscador.executar_vencidas() == []
    fontes.definir_ativa("ml", True)
    assert buscador.executar_vencidas() == [("Vencida", "ok: 1 produto(s)")]


# ── Card e selo ───────────────────────────────────────────────────────────────

def test_de_por_so_aparece_com_preco_original_real():
    base = {"nome": "Mouse", "loja": "Mercado Livre", "preco_hoje": 54.9, "dias": 0}
    com = base | {"preco_original": 79.9}
    assert oferta.selo(com) == "🏷️ De R$ 79,90 por R$ 54,90 (-31%)"
    assert "De <s>R$ 79,90</s> por <b>R$ 54,90</b> (-31%)" in oferta.formatar_oferta(com, "https://x")
    for sem in (base, base | {"preco_original": None}, base | {"preco_original": 54.9},
                base | {"preco_original": 40.0}):
        assert oferta.selo(sem) is None
        assert "De <s>" not in oferta.formatar_oferta(sem, "https://x")


def test_regra_de_historico_continua_valendo_e_tem_prioridade():
    p = {"nome": "Mouse", "loja": "ML", "preco_hoje": 50.0, "minimo": 60.0, "media": 70.0, "dias": 8,
         "preco_original": 79.9}
    assert oferta.selo(p) == "🏆 Menor preço em 8 dias monitorados"
    texto = oferta.formatar_oferta(p, "https://x")
    assert "🏆 Menor preço em 8 dias" in texto and "De <s>R$ 79,90</s>" in texto
    assert oferta.selo(p | {"dias": 2, "preco_original": None}) is None


# ── Regras da busca no piloto ─────────────────────────────────────────────────

@pytest.mark.parametrize("regras, permitido", [
    ({}, True),
    ({"preco_max": 50}, False),
    ({"preco_max": 60}, True),
    ({"desconto_min_pct": 30}, True),     # -31% sobre o preço "de"
    ({"desconto_min_pct": 40}, False),
])
def test_piloto_aplica_as_regras_da_busca_que_achou_o_produto(fonte, regras, permitido):
    buscador.executar(nova_busca(**regras))
    [p] = db.menores_precos_do_dia()
    assert buscador.permite_publicar(p) is permitido


def test_regra_de_frete_gratis(fonte):
    fonte.produtos = [produto(frete=False)]
    buscador.executar(nova_busca(so_frete_gratis=1))
    assert buscador.permite_publicar(db.menores_precos_do_dia()[0]) is False


def test_produto_so_de_canal_nao_ganha_regra_extra():
    asyncio.run(radar.capturar(None, f"Mouse por R$ 49,90\n{URL_CANAL}", "Canal X"))
    assert buscador.permite_publicar(db.menores_precos_do_dia()[0]) is True
