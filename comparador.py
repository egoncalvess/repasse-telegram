"""
Consulta e comparação de preços (sem publicar nada): histórico do radar, de qualquer loja, mais uma leitura
na hora quando a loja tem fonte de busca por produto (ex.: Ferreira Costa).

- comparar(termo): produtos do histórico cujo nome tem todas as palavras do termo, do menor último preço
  para o maior, e o melhor preço de cada loja.
- consultar_link(url): histórico do produto do link; se a fonte da loja busca por produto, lê o preço agora.

Casas Bahia e Magalu bloqueiam acesso automático: o histórico delas vem só dos links que aparecem nos canais
monitorados pelo radar (nenhuma requisição é feita a esses sites).
"""
import re
import unicodedata

import database as db
import fontes
from fontes.base import Busca

DIAS = 90


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()


def _com_tendencia(p: dict) -> dict:
    """Acrescenta onde o último preço está em relação ao histórico do produto."""
    ultimo, minimo, media = p["ultimo"], p["minimo"], p["media"]
    p["no_minimo"] = p["dias"] >= 2 and ultimo <= minimo
    p["vs_media_pct"] = round((ultimo / media - 1) * 100) if p["dias"] >= 2 and media else None
    return p


def comparar(termo: str, limite: int = 10, dias: int = DIAS) -> dict:
    """{"produtos": [...] do menor último preço, "por_loja": {loja: produto mais barato}, "total": n}"""
    palavras = [w for w in _normalizar(termo).split() if len(w) > 1]
    if not palavras:
        return {"produtos": [], "por_loja": {}, "total": 0}
    candidatas = [chave for chave, nome in db.listar_nomes_produtos()
                  if all(w in _normalizar(nome) for w in palavras)]
    if not candidatas:
        return {"produtos": [], "por_loja": {}, "total": 0}
    achados = [_com_tendencia(p) for p in db.estatisticas_precos(dias, chaves=candidatas)]
    achados.sort(key=lambda p: p["ultimo"])
    por_loja = {}
    for p in achados:
        por_loja.setdefault(p["loja"], p)
    return {"produtos": achados[:limite], "por_loja": por_loja, "total": len(achados)}


def consultar_link(url: str, dias: int = DIAS) -> tuple[dict | None, str | None]:
    """(estatísticas do produto ou None, aviso). Lê o preço agora quando a loja tem fonte de produto."""
    import buscador
    import dedup
    chave = dedup.chave_produto(url or "")
    if not chave:
        return None, "Link não reconhecido: não é de uma loja acompanhada pelo radar."
    aviso = None
    fonte = fontes.get(chave.split(":")[0])
    if fonte and "produto" in fonte.tipos_busca:
        try:
            for p in fonte.buscar(Busca("produto", url, 1)):
                buscador.registrar_produto(fonte, p)
        except Exception as e:  # sem leitura na hora, mostra o histórico que houver
            aviso = f"Sem preço atual de {fonte.nome}: {e}"[:200]
    elif not fonte:
        aviso = "Sem leitura na hora para esta loja: histórico só dos canais monitorados."
    stats = db.estatisticas_precos(dias, chaves=[chave])
    return (_com_tendencia(stats[0]) if stats else None), aviso
