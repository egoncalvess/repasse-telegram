"""
Buscador automático: executa as buscas cadastradas (tabela buscas) nas fontes de fontes/ e grava cada
produto no radar (mesmo histórico dos canais). Quem publica continua sendo o piloto, que consulta
permite_publicar() para aplicar as regras da busca que achou o produto.
"""
import asyncio
from datetime import datetime

import database as db
import fontes
from fontes.base import Busca, FonteBloqueada, FonteIndisponivel

LIMITE_POR_BUSCA = 20     # produtos por execução
CICLO_S = 60              # de quanto em quanto tempo o loop procura buscas vencidas


def salvar_imagem(fonte, chave: str, imagem_url: str) -> str | None:
    """Foto em data/imagens/ com o mesmo nome que o radar usa; baixa só se o produto ainda não tem."""
    import radar
    if not imagem_url or db.tem_imagem(chave):
        return None
    destino = radar.caminho_imagem(chave)
    if destino.exists():
        return str(destino)
    conteudo = fonte.http.baixar(imagem_url)
    if not conteudo:
        return None
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(conteudo)
    return str(destino)


def executar(busca: dict) -> str:
    """Roda uma busca agora e grava o resultado. Retorna o status gravado em buscas.ultimo_status."""
    fonte = fontes.get(busca["fonte_id"])
    if not fonte:
        status = f"erro: fonte {busca['fonte_id']} não existe"
        db.marcar_execucao_busca(busca["id"], status)
        return status
    try:
        produtos = fonte.buscar(Busca(busca["tipo"], busca["valor"], LIMITE_POR_BUSCA))
    except FonteBloqueada as e:
        status = f"bloqueado: {e}"
    except FonteIndisponivel as e:
        status = f"falha: {e}"
    except Exception as e:  # valor inválido, 404 etc.: marca a execução para não repetir a cada ciclo
        status = f"erro: {e}"
    else:
        for p in produtos:
            registrar_produto(fonte, p, busca["id"])
        status = f"ok: {len(produtos)} produto(s)"
    db.marcar_execucao_busca(busca["id"], status)
    return status


def registrar_produto(fonte, p, busca_id: int = None):
    """Preço no radar (origem fonte:<id>), foto em data/imagens e, se veio de uma busca, o resultado dela."""
    imagem = None
    try:
        imagem = salvar_imagem(fonte, p.chave, p.imagem_url)
    except Exception as e:  # foto é opcional: não derruba a busca
        print(f"[Buscador] Falha ao salvar a foto de {p.chave}: {e}")
    db.registrar_preco(p.chave, p.nome, p.loja, p.url, p.preco, origem=f"fonte:{fonte.id}",
                       imagem=imagem, preco_original=p.preco_original)
    if busca_id is not None:
        db.registrar_resultado_busca(busca_id, p.chave, p.preco, p.preco_original, p.frete_gratis)


def buscar_agora(termo: str, limite: int = 10) -> tuple[list, list[str]]:
    """Busca por termo em todas as fontes ativas, grava no radar e devolve ([ProdutoEncontrado], erros),
    do maior desconto informado pela loja para o menor, e então do menor preço."""
    achados, erros = [], []
    for fonte in fontes.ativas():
        try:
            for p in fonte.buscar(Busca("termo", termo, limite)):
                registrar_produto(fonte, p)
                achados.append(p)
        except Exception as e:
            erros.append(f"{fonte.nome}: {e}")

    def desconto(p):
        return (1 - p.preco / p.preco_original) if p.preco_original else 0
    achados.sort(key=lambda p: (-desconto(p), p.preco))
    return achados, erros


def monitorar(chave: str) -> tuple[int | None, str]:
    """Cria uma busca do tipo produto para o item (ex.: botão Monitorar do /buscar). (id, mensagem)"""
    prod = db.get_produto(chave)
    fonte = fontes.get(chave.split(":")[0])
    if not prod or not fonte:
        return None, "Produto ou fonte não encontrados."
    for b in db.listar_buscas():
        if b["fonte_id"] == fonte.id and b["tipo"] == "produto" and b["valor"] == prod["url"]:
            return b["id"], f"Já monitorado: {b['nome']}"
    bid = db.adicionar_busca({"fonte_id": fonte.id, "nome": prod["nome"][:60], "tipo": "produto",
                              "valor": prod["url"], "intervalo_min": fonte.intervalo_min_padrao})
    return bid, f"Monitorando: {prod['nome'][:60]}"


def pode_executar(busca: dict) -> str | None:
    """Motivo para não rodar a busca agora (None = pode)."""
    if db.get_config("pausado", "0") == "1":
        return "pausa global"
    fonte = fontes.get(busca["fonte_id"])
    if not fonte:
        return "fonte inexistente"
    if not fontes.ativa(fonte.id):
        return "fonte desligada"
    if fontes.pausada(fonte.id):
        return "fonte pausada"
    if db.contar_chamadas_api(fonte.id, 1) >= fontes.req_por_minuto(fonte):
        return "limite da fonte no último minuto"
    return None


def executar_vencidas() -> list[tuple[str, str]]:
    """Executa as buscas vencidas que podem rodar. [(nome, status)]"""
    feitas = []
    for busca in db.buscas_vencidas():
        if pode_executar(busca):
            continue
        feitas.append((busca["nome"], executar(busca)))
    return feitas


def passa_regras(busca: dict, p: dict) -> bool:
    """O produto (linha de menores_precos_do_dia) atende às regras da busca?"""
    from oferta import desconto_pct
    if busca.get("preco_max") and p["preco_hoje"] > busca["preco_max"]:
        return False
    if busca.get("so_frete_gratis") and not busca.get("resultado_frete_gratis"):
        return False
    if busca.get("desconto_min_pct") and desconto_pct(p) < busca["desconto_min_pct"]:
        return False
    return True


def permite_publicar(p: dict) -> bool:
    """Produto achado por busca só é publicado se atender às regras de ao menos uma delas.
    Produto que só veio de canais segue a regra de sempre (sem regra extra)."""
    buscas = db.buscas_do_produto(p["chave"])
    return not buscas or any(passa_regras(b, p) for b in buscas)


async def loop_buscador(tm):
    while True:
        try:
            for nome, status in await asyncio.to_thread(executar_vencidas):
                print(f"[Buscador] {datetime.now():%H:%M} {nome}: {status}")
        except Exception as e:
            print(f"[Buscador] {e}")
        await asyncio.sleep(CICLO_S)
