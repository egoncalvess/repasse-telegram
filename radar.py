"""
Radar de preços: cada oferta que passa pelos canais monitorados vira uma observação de preço.
Com o histórico, o app sabe quais produtos estão no menor preço do dia (dado real, não estimado).
"""
import re
from pathlib import Path

import database as db

LOJAS = {"ml": "Mercado Livre", "amz": "Amazon", "shp": "Shopee", "ali": "AliExpress", "mgl": "Magalu"}
PASTA_IMAGENS = Path("data/imagens")

# R$ 1.234,56 | R$1234,56 | R$ 99 | R$ 99,9
VALOR_RE = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?")
# Valores que não são o preço do produto (cupom, desconto, frete, economia, parcela)
NAO_PRECO_RE = re.compile(r"(cupom|desconto|off|frete|economi|cashback|parcela|\dx\s*de|x\s*$)", re.IGNORECASE)


def caminho_imagem(chave: str) -> Path:
    """Arquivo da foto do produto (mesmo nome para canais e fontes de busca)."""
    return PASTA_IMAGENS / (re.sub(r"[^\w-]", "_", chave) + ".jpg")


def _valor(m) -> float:
    return float(m.group(1).replace(".", "") + "." + (m.group(2) or "0"))


def extrair_preco(texto: str) -> float | None:
    """
    Preço final anunciado. Prioriza 'por R$ X' (padrão 'de R$ A por R$ B');
    senão, o menor valor que não seja cupom/desconto/frete/parcela.
    """
    texto = texto or ""
    por = re.search(r"\bpor\s*:?\s*R\$", texto, re.IGNORECASE)
    if por:
        m = VALOR_RE.search(texto, por.end() - 2)
        if m:
            return _valor(m)
    candidatos = []
    for m in VALOR_RE.finditer(texto):
        antes = texto[texto.rfind("\n", 0, m.start()) + 1:m.start()]  # contexto: a linha até o valor
        depois = texto[m.end():m.end() + 6]
        if NAO_PRECO_RE.search(antes) or re.match(r"\s*(off|de desconto)", depois, re.IGNORECASE):
            continue
        candidatos.append(_valor(m))
    candidatos = [v for v in candidatos if v >= 1]
    return min(candidatos) if candidatos else None


def extrair_nome(texto: str) -> str:
    """Primeira linha com cara de nome de produto (ignora linhas só de emoji/chamada/preço/link)."""
    for linha in (texto or "").splitlines():
        limpa = re.sub(r"https?://\S+", "", linha).split("R$")[0]  # nome vem antes do preço
        limpa = re.sub(r"[*_`~>#\[\]]", "", limpa)
        limpa = re.sub(r"[^\w\s\-+/.,()%'\"&ºª]", "", limpa).strip(" -:|")
        limpa = re.sub(r"(?i)\s*\b(por|de|apenas|só|a partir de)\s*$", "", limpa)
        if len(re.findall(r"[A-Za-zÀ-ÿ]", limpa)) < 6:
            continue
        if re.fullmatch(r"(?i)(oferta|promo[cç][aã]o|achadinho|corre|imperd[ií]vel|link)[\w\s!]*", limpa):
            continue
        return limpa[:150]
    return "Produto sem título"


async def capturar(msg, texto: str, origem: str, visto_em=None) -> int:
    """Registra o preço da oferta da mensagem. Retorna quantos produtos foram registrados (0 ou 1)."""
    import dedup

    preco = extrair_preco(texto)
    if not preco:
        return 0
    produtos = await dedup.produtos_do_texto(texto)
    if len(produtos) != 1:  # vários produtos numa msg: não dá para saber de qual é o preço
        return 0
    chave, url = next(iter(produtos.items()))

    imagem = None
    if msg is not None and getattr(msg, "photo", None) and not db.tem_imagem(chave):
        PASTA_IMAGENS.mkdir(parents=True, exist_ok=True)
        destino = caminho_imagem(chave)
        try:
            await msg.download_media(file=str(destino))
            imagem = str(destino)
        except Exception as e:
            print(f"[Radar] Falha ao salvar imagem de {chave}: {e}")

    nome = extrair_nome(texto)
    db.registrar_preco(chave, nome, LOJAS.get(chave.split(":")[0], "Loja"), url, preco,
                       origem=origem, imagem=imagem, visto_em=visto_em)
    if visto_em is None:
        print(f"[Radar] {origem[:25]}: {nome[:40]} = R$ {preco:.2f}")
    return 1


async def importar_historico(client, entity, origem: str, dias: int = 30, progresso=None) -> tuple[int, int]:
    """
    Lê as postagens antigas do canal (conta de usuário) e registra os preços com a data original.
    Retorna (mensagens lidas, preços registrados). Mensagens repetidas não duplicam (mesmo minuto).
    """
    from datetime import datetime, timedelta, timezone
    limite = datetime.now(timezone.utc) - timedelta(days=dias)
    lidas = registrados = 0
    async for msg in client.iter_messages(entity):
        if msg.date < limite:
            break
        lidas += 1
        if msg.text:
            try:
                registrados += await capturar(msg, msg.text, origem,
                                              visto_em=msg.date.astimezone().replace(tzinfo=None))
            except Exception as e:
                print(f"[Radar] Falha ao importar msg {msg.id} de {origem}: {e}")
        if progresso and lidas % 25 == 0:
            progresso(lidas, registrados)
    return lidas, registrados
