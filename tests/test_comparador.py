"""
Comparador de preços (/precos) e lojas só de histórico: estatísticas do radar, busca por palavras sem acento,
leitura na hora da Ferreira Costa e nenhuma publicação de Ferreira Costa, Casas Bahia ou Magalu.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database as db  # noqa: E402
import comparador  # noqa: E402
import oferta  # noqa: E402
from fontes.base import ProdutoEncontrado  # noqa: E402


@pytest.fixture(autouse=True)
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "repasse.db")
    db.init_db()


def preco(chave, nome, loja, valor, dias_atras):
    quando = datetime.now().replace(hour=10, minute=0) - timedelta(days=dias_atras)
    db.registrar_preco(chave, nome, loja, f"https://loja/{chave}", valor, origem="teste", visto_em=quando)


def test_estatisticas_do_historico_por_produto():
    preco("fc:1", "Geladeira Midea 394L", "Ferreira Costa", 3100, 10)
    preco("fc:1", "Geladeira Midea 394L", "Ferreira Costa", 2800, 5)
    preco("fc:1", "Geladeira Midea 394L", "Ferreira Costa", 2950, 0)
    preco("fc:1", "Geladeira Midea 394L", "Ferreira Costa", 2900, 200)   # fora da janela de 90 dias
    [s] = db.estatisticas_precos(90)
    assert s["ultimo"] == 2950 and s["minimo"] == 2800 and s["maximo"] == 3100 and s["dias"] == 3
    assert s["dia_minimo"] == (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")


def test_comparar_casa_todas_as_palavras_sem_acento_e_ordena_pelo_ultimo_preco():
    preco("fc:1", "Geladeira Midea Frost Free", "Ferreira Costa", 2919.9, 0)
    preco("mgl:abc123", "Geladeira MIDEA frost free inox", "Magalu", 2799.0, 1)
    preco("cb:5501234", "Geladeira Midea Frost Free", "Casas Bahia", 3099.0, 0)
    preco("cb:5509999", "Geladeira Midea Frost Free", "Casas Bahia", 2999.0, 0)
    preco("ml:1", "Geladeira Brastemp", "Mercado Livre", 1999.0, 0)
    preco("fc:2", "Refrigerador Midea Duplex Ação", "Ferreira Costa", 2500.0, 0)
    res = comparador.comparar("geladeira midea")
    assert [p["chave"] for p in res["produtos"]] == ["mgl:abc123", "fc:1", "cb:5509999", "cb:5501234"]
    assert {l: p["ultimo"] for l, p in res["por_loja"].items()} == \
        {"Magalu": 2799.0, "Ferreira Costa": 2919.9, "Casas Bahia": 2999.0}
    assert comparador.comparar("acao")["total"] == 1          # sem acento acha "Ação"
    assert comparador.comparar("")["total"] == 0


def test_tendencia_marca_menor_preco_e_distancia_da_media():
    for dias, v in ((3, 100), (2, 120), (0, 90)):
        preco("fc:1", "Furadeira Bosch", "Ferreira Costa", v, dias)
    [p] = comparador.comparar("furadeira")["produtos"]
    assert p["no_minimo"] and p["vs_media_pct"] < 0


def test_link_da_ferreira_costa_le_o_preco_agora_e_mostra_o_historico(monkeypatch):
    import fontes
    fc = fontes.get("fc")
    lido = ProdutoEncontrado(chave="fc:658753", nome="Geladeira LG", url="https://www.ferreiracosta.com/produto/658753",
                             preco=5999.9, preco_original=6739.9, loja="Ferreira Costa")
    monkeypatch.setattr(fc, "buscar", lambda busca: [lido])
    preco("fc:658753", "Geladeira LG", "Ferreira Costa", 6299.9, 4)
    p, aviso = comparador.consultar_link("https://www.ferreiracosta.com/produto/658753/geladeira-lg")
    assert aviso is None and p["ultimo"] == 5999.9 and p["maximo"] == 6299.9 and p["dias"] == 2


def test_link_da_casas_bahia_nao_faz_requisicao_e_usa_so_o_historico():
    preco("cb:5501234", "TV 50", "Casas Bahia", 2199.0, 1)
    p, aviso = comparador.consultar_link("https://www.casasbahia.com.br/tv-50/p/5501234")
    assert p["ultimo"] == 2199.0 and "canais" in aviso
    assert comparador.consultar_link("https://exemplo.com/x") == \
        (None, "Link não reconhecido: não é de uma loja acompanhada pelo radar.")


@pytest.mark.parametrize("chave", ["fc:1", "cb:5501234", "mgl:abc123"])
def test_lojas_so_de_historico_nunca_sao_publicadas(chave):
    preco(chave, "Produto", "Loja", 100, 0)
    assert not oferta.publicavel(chave)
    with pytest.raises(RuntimeError, match="só para histórico"):
        oferta.publicar_oferta(chave, None, "-100123")
    assert oferta.publicavel("ml:1") and oferta.publicavel("amz:B0ABCDEFGH")
