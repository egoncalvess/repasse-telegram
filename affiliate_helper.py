"""
Motor de afiliação: troca links de loja pelos SEUS links de afiliado antes do envio.

Regras:
- Link de terceiros é reconstruído do zero (URL canônica do produto + seus parâmetros),
  então tags/etiquetas de outros afiliados nunca sobrevivem.
- Mercado Livre não tem API de links: usamos o formato do "link completo" do Gerador de Links
  do Portal do Afiliado (matt_word + matt_tool), extraído de um link que você mesmo gerou.
- Loja sem integração configurada (ou sem conversão oficial possível, ex.: Shopee sem API)
  fica como "não convertida" para o chamador decidir (bloquear ou repassar como está).
"""
import re
import urllib.request
import asyncio
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import database as db

ML_PARAMS = ("matt_word", "matt_tool")

# loja -> trechos de domínio (inclui encurtadores)
DOMINIOS = {
    "amazon": ("amazon.com", "amzn.to", "amzn.com", "a.co/"),
    "mercadolivre": ("mercadolivre.com", "mercadolibre.com", "meli.la", "meli.to", "mlb.link", "ml.link",
                     "mpago.la", "mpago.li"),
    "shopee": ("shopee.", "shope.ee"),
    "magalu": ("magazinevoce.com.br", "magazineluiza.com.br"),
    "aliexpress": ("aliexpress.", "s.click.aliexpress"),
}


def get_active_integrations() -> dict:
    """Integrações ativas indexadas pelo tipo (ex.: 'mercadolivre': {'tag': ...})."""
    try:
        return {i["tipo"]: {"tag": i.get("tag", "")} for i in db.listar_integracoes() if i.get("ativo", 1)}
    except Exception:
        return {}


def loja_da_url(url: str) -> str | None:
    u = url.lower()
    return next((loja for loja, doms in DOMINIOS.items() if any(d in u for d in doms)), None)


def parametros_ml(tag: str) -> dict:
    """matt_word/matt_tool a partir do link completo do portal (ou da query já normalizada)."""
    tag = (tag or "").strip()
    q = parse_qs(urlparse(tag).query if "://" in tag else tag)
    return {k: q[k][0] for k in ML_PARAMS if q.get(k)}


def normalizar_tag(tipo: str, tag: str) -> tuple[str, str | None]:
    """Como a tag é guardada + aviso para o usuário (None = ok)."""
    tag = (tag or "").strip()
    if tipo == "mercadolivre":
        params = parametros_ml(tag)
        if set(params) == set(ML_PARAMS):
            return urlencode(params), None
        return tag, ("Para o Mercado Livre, cole um LINK COMPLETO gerado no Gerador de Links do Portal do "
                     "Afiliado (ele contém matt_word e matt_tool). Sem isso, links do ML não serão convertidos.")
    if tipo == "shopee":
        return tag, "A Shopee só gera link de afiliado pela API oficial (App ID + Secret); a tag sozinha não converte."
    return tag, None


def resolve_url(url: str) -> str:
    """Resolve o redirecionamento de uma URL encurtada de forma síncrona."""
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        # Segue redirecionamentos automaticamente
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.geturl()
    except Exception:
        return url

async def resolve_url_async(url: str) -> str:
    """Resolve o redirecionamento de uma URL encurtada de forma assíncrona usando executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, resolve_url, url)


def update_amazon_url(url: str, tag: str) -> str:
    """URL canônica do produto (/dp/ASIN) com a sua tag; sem ASIN, troca só o parâmetro tag."""
    m = re.search(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})", url, re.IGNORECASE)
    if m:
        return f"https://www.amazon.com.br/dp/{m.group(1).upper()}?{urlencode({'tag': tag})}"
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        query['tag'] = [tag]
        return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
    except Exception:
        return url

def update_magalu_url(url: str, tag: str) -> str:
    """Substitui a loja de divulgação da Magalu pela loja do usuário."""
    # Ex: https://www.magazinevoce.com.br/magazineluiza/p/geladeira... -> https://www.magazinevoce.com.br/SUA_LOJA/p/geladeira...
    try:
        match = re.match(r'^(https?://(?:www\.)?magazinevoce\.com\.br/)([^/]+)(/.*)?$', url, re.IGNORECASE)
        if match:
            prefix, old_store, suffix = match.groups()
            suffix = suffix or ""
            return f"{prefix}{tag}{suffix}"
    except Exception:
        pass
    return url

def update_mercadolivre_url(url: str, tag: str, cookie: str = "") -> str:
    """
    URL canônica do anúncio/produto + seus matt_word/matt_tool (formato do 'link completo' do portal).
    Retorna a URL original quando não dá para converter (sem link completo configurado ou sem ID MLB).
    """
    params = parametros_ml(tag)
    if set(params) != set(ML_PARAMS):
        return url
    catalogo = re.search(r"/p/(MLB\d+)", url, re.IGNORECASE)
    if catalogo:
        base = f"https://www.mercadolivre.com.br/p/{catalogo.group(1).upper()}"
    else:
        item = re.search(r"MLB-?(\d{6,})", url, re.IGNORECASE)
        if not item:
            return url
        base = f"https://produto.mercadolivre.com.br/MLB-{item.group(1)}"
    return f"{base}?{urlencode(params)}"


def converter_url(loja: str, url: str, integracao: dict | None) -> str | None:
    """Link de afiliado da URL (já resolvida) ou None se não for possível converter."""
    tag = (integracao or {}).get("tag", "")
    if not tag:
        return None
    if loja == "mercadolivre":
        novo = update_mercadolivre_url(url, tag)
    elif loja == "amazon":
        novo = update_amazon_url(url, tag)
    elif loja == "magalu":
        novo = update_magalu_url(url, tag)
        if novo == url and f"/{tag.lower()}/" in url.lower():  # já é a sua loja
            return url
    else:  # shopee/aliexpress: só via API oficial, ainda não integrada
        return None
    return novo if novo != url else None


async def converter_links(text: str) -> tuple[str, list[str]]:
    """
    Troca todos os links de loja do texto pelos seus links de afiliado.
    Retorna (texto, links_nao_convertidos).
    """
    from dedup import URL_RE, _desembrulhar
    if not text:
        return text, []
    integracoes = get_active_integrations()
    nao_convertidos = []
    for url in dict.fromkeys(URL_RE.findall(text)):
        limpa = url.rstrip('.,;!?')
        loja = loja_da_url(limpa)
        if not loja:
            continue
        # Encurtadores/redirects (inclusive os /sec/ de outros afiliados): resolve até o produto
        resolvida = limpa
        if not re.search(r"MLB-?\d{6,}|/dp/[A-Z0-9]{10}|magazinevoce", limpa, re.IGNORECASE):
            resolvida = _desembrulhar(await resolve_url_async(limpa))
        novo = converter_url(loja, resolvida, integracoes.get(loja))
        if novo:
            text = text.replace(limpa, novo)
        else:
            nao_convertidos.append(limpa)
    return text, nao_convertidos


async def process_text_urls(text: str) -> str:
    """Compatibilidade: só o texto convertido."""
    return (await converter_links(text))[0]


def scrape_product_details(url: str, tag: str, cookie: str = "") -> dict:
    """
    Acessa a URL do produto, segue redirecionamentos, extrai os metadados do HTML
    (título, imagem, preço) e retorna os detalhes estruturados.
    """
    # 1. Resolve redirecionamentos
    resolved_url = resolve_url(url)
    
    # 2. Faz scraping do HTML
    html = ""
    try:
        req = urllib.request.Request(
            resolved_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"
            }
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[Scraper] Erro ao carregar página: {e}")
        
    # 3. Extrai Título (og:title ou <title>)
    title = "Produto Sensacional"
    title_match = re.search(r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if not title_match:
        title_match = re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:title["\']', html, re.IGNORECASE)
    if not title_match:
        title_match = re.search(r'<meta[^>]*name=["\']twitter:title["\'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if title_match:
        title = title_match.group(1).strip()
    else:
        html_title = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        if html_title:
            title = html_title.group(1).strip()
            
    # Limpa título (remove sufixos comuns de lojas)
    title = re.sub(r'\s*\|\s*Amazon\.com\.br.*$', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\s*-\s*Mercado Livre.*$', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\s*no\s*Magazine\s*Luiza.*$', '', title, flags=re.IGNORECASE)
    title = title.replace("&quot;", '"').replace("&amp;", '&')

    # 4. Extrai Imagem (og:image)
    image_url = ""
    img_match = re.search(r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if not img_match:
        img_match = re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']', html, re.IGNORECASE)
    if not img_match:
        img_match = re.search(r'<meta[^>]*name=["\']twitter:image["\'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if img_match:
        image_url = img_match.group(1).strip()
        
    # 5. Tenta extrair Preço
    price = ""
    price_match = re.search(r'<meta[^>]*property=["\']product:price:amount["\'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if not price_match:
        price_match = re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']product:price:amount["\']', html, re.IGNORECASE)
    if price_match:
        price = f"R$ {price_match.group(1).replace('.', ',')}"
    else:
        # Padrões alternativos de preço na página
        price_match = re.search(r'R\$\s*\d+(?:[\.,]\d+)?', html)
        if price_match:
            price = price_match.group(0)
            
    # 6. Gera Link de Afiliado (mesma regra do repasse; sem conversão possível, mantém a URL)
    loja = loja_da_url(resolved_url)
    affiliate_url = (converter_url(loja, resolved_url, {"tag": tag}) if loja else None) or resolved_url

    # 7. Baixa a Imagem localmente se houver url
    local_image_path = None
    if image_url:
        try:
            from pathlib import Path
            img_req = urllib.request.Request(
                image_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            data_dir = Path("data")
            data_dir.mkdir(exist_ok=True)
            temp_path = data_dir / "temp_scraped_image.jpg"
            with urllib.request.urlopen(img_req, timeout=5) as img_res:
                temp_path.write_bytes(img_res.read())
            local_image_path = str(temp_path.resolve())
        except Exception as e:
            print(f"[Scraper] Erro ao baixar imagem: {e}")
            
    return {
        "title": title,
        "image_path": local_image_path,
        "price": price or "Consultar no site",
        "affiliate_url": affiliate_url
    }

async def scrape_product_details_async(url: str, tag: str, cookie: str = "") -> dict:
    """
    Versão assíncrona que executa o scraping em segundo plano.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, scrape_product_details, url, tag, cookie)

