"""
Identifica o produto por trás de cada link de loja e evita repostar o mesmo produto em X horas,
mesmo que venha de canais diferentes, com links/encurtadores diferentes.
"""
import re
from urllib.parse import urlparse, parse_qs

from affiliate_helper import resolve_url_async

# prefixo da chave, regex do ID do produto na URL final
PADROES = [
    ("ml",  r"MLB-?(\d{6,})"),
    ("amz", r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})"),
    ("shp", r"i\.(\d+)\.(\d+)|/product/(\d+)/(\d+)"),
    ("ali", r"/item/(\d+)\.html"),
    ("mgl", r"magazine(?:voce|luiza)\.com\.br/.*?/p/([a-z0-9]{6,})"),
]
ENCURTADORES = ("amzn.to", "a.co/", "shope.ee", "s.shopee", "mercadolivre.com/sec/", "meli.la",
                "meli.to", "mlb.link", "ml.link", "s.click.aliexpress", "onelink.me")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")


def _desembrulhar(url: str) -> str:
    """Páginas de verificação/redirect das lojas trazem o destino real em ?go=."""
    go = parse_qs(urlparse(url).query).get("go")
    return go[0] if go else url


def chave_produto(url: str) -> str | None:
    for prefixo, padrao in PADROES:
        m = re.search(padrao, url, re.IGNORECASE)
        if m:
            return prefixo + ":" + "-".join(g for g in m.groups() if g).upper()
    return None


async def chaves_do_texto(texto: str) -> set[str]:
    """Chaves de produto de todos os links de loja do texto (resolve encurtadores)."""
    chaves = set()
    for url in URL_RE.findall(texto or ""):
        url = url.rstrip(".,;!?")
        if any(e in url.lower() for e in ENCURTADORES):
            url = _desembrulhar(await resolve_url_async(url))
        chave = chave_produto(url)
        if chave:
            chaves.add(chave)
    return chaves
