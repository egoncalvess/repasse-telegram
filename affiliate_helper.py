import re
import urllib.request
import asyncio
import json
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import database as db

def get_active_integrations() -> dict:
    """Retorna as integrações ativas indexadas pelo tipo (ex: 'amazon': {'tag': 'tag', 'cookie': 'cookie'})."""
    try:
        return {i["tipo"]: {"tag": i.get("tag", ""), "cookie": i.get("cookie", "")} for i in db.listar_integracoes() if i.get("ativo", 1)}
    except Exception:
        return {}

def parse_cookie_data(cookie_data: str):
    """
    Parses cookie data which can be a raw cookie string, a JSON list of cookies,
    or a JSON object containing a user_agent and session_data list.
    Returns (cookie_header_string, user_agent_string).
    """
    cookie_str = ""
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    if not cookie_data:
        return "", user_agent
        
    cookie_data_stripped = cookie_data.strip()
    if not cookie_data_stripped:
        return "", user_agent

    # Check if it looks like JSON
    if (cookie_data_stripped.startswith("[") and cookie_data_stripped.endswith("]")) or \
       (cookie_data_stripped.startswith("{") and cookie_data_stripped.endswith("}")):
        try:
            parsed = json.loads(cookie_data_stripped)
            if isinstance(parsed, dict):
                # Format: {"user_agent": "...", "session_data": [...]} or similar
                if "user_agent" in parsed:
                    user_agent = parsed["user_agent"]
                
                cookie_list = None
                if "session_data" in parsed and isinstance(parsed["session_data"], list):
                    cookie_list = parsed["session_data"]
                elif "cookies" in parsed and isinstance(parsed["cookies"], list):
                    cookie_list = parsed["cookies"]
                elif isinstance(parsed, list):
                    cookie_list = parsed
                
                if cookie_list:
                    cookies = []
                    for c in cookie_list:
                        if isinstance(c, dict) and "name" in c and "value" in c:
                            cookies.append(f"{c['name']}={c['value']}")
                    cookie_str = "; ".join(cookies)
            elif isinstance(parsed, list):
                # Plain list of cookies: [{"name": "...", "value": "..."}, ...]
                cookies = []
                for c in parsed:
                    if isinstance(c, dict) and "name" in c and "value" in c:
                        cookies.append(f"{c['name']}={c['value']}")
                cookie_str = "; ".join(cookies)
        except Exception:
            pass

    # If not parsed as JSON successfully (cookie_str still empty), treat as raw Cookie header
    if not cookie_str:
        raw_lines = []
        for line in cookie_data_stripped.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.lower().startswith("cookie:"):
                line = line[len("cookie:"):].strip()
            # Support Netscape tab-separated format
            if not line.startswith("#") and "\t" in line:
                parts = line.split("\t")
                if len(parts) >= 7:
                    name = parts[5]
                    value = parts[6]
                    raw_lines.append(f"{name}={value}")
                elif len(parts) >= 2:
                    raw_lines.append(f"{parts[0]}={parts[1]}")
            else:
                raw_lines.append(line)
        cookie_str = "; ".join(raw_lines)
        
    return cookie_str, user_agent

def generate_mercadolivre_affiliate_with_cookie(url: str, cookie_data: str) -> str:
    """
    Usa os cookies de sessão fornecidos para gerar o link de afiliado do Mercado Livre
    fazendo uma requisição HTTP POST para a API de afiliados.
    """
    cookie_str, user_agent = parse_cookie_data(cookie_data)
    if not cookie_str:
        return url
        
    try:
        api_url = "https://afiliados.mercadolivre.com.br/api/links"
        payload = json.dumps({"url": url}).encode("utf-8")
        
        req = urllib.request.Request(
            api_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": user_agent,
                "Cookie": cookie_str,
                "Accept": "application/json",
            },
            method="POST"
        )
        
        with urllib.request.urlopen(req, timeout=8) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
            if isinstance(resp_data, dict):
                if "shortLink" in resp_data:
                    return resp_data["shortLink"]
                elif "link" in resp_data:
                    return resp_data["link"]
                elif "url" in resp_data:
                    return resp_data["url"]
                elif "data" in resp_data and isinstance(resp_data["data"], dict):
                    data = resp_data["data"]
                    if "shortLink" in data:
                        return data["shortLink"]
                    elif "link" in data:
                        return data["link"]
            return url
    except Exception as e:
        print(f"[Cookie ML] Erro ao gerar link de afiliado via Cookie: {e}")
        return url


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
    """Insere ou substitui a tag de afiliado da Amazon na URL."""
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        query['tag'] = [tag]
        new_query = urlencode(query, doseq=True)
        return urlunparse(parsed._replace(query=new_query))
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

def update_shopee_url(url: str, tag: str) -> str:
    """Insere a tag de afiliado do Shopee na URL."""
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        # Define os parâmetros de rastreamento comuns do Shopee
        query['sub_id'] = [tag]
        query['utm_content'] = [tag]
        new_query = urlencode(query, doseq=True)
        return urlunparse(parsed._replace(query=new_query))
    except Exception:
        return url

def update_mercadolivre_url(url: str, tag: str, cookie: str = "") -> str:
    """Insere ou substitui o parâmetro affiliate do Mercado Livre na URL. Caso haja cookies, usa a API."""
    if cookie:
        cookie_link = generate_mercadolivre_affiliate_with_cookie(url, cookie)
        if cookie_link and cookie_link != url:
            return cookie_link
            
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        query['affiliate'] = [tag]
        new_query = urlencode(query, doseq=True)
        return urlunparse(parsed._replace(query=new_query))
    except Exception:
        return url

async def process_text_urls(text: str) -> str:
    """
    Analisa um texto procurando por links de plataformas parceiras.
    Se encontrar e a integração correspondente estiver ativa, atualiza com a tag do afiliado.
    """
    if not text:
        return text

    # Regex simples para capturar URLs
    url_pattern = r'(https?://[^\s]+)'
    urls = re.findall(url_pattern, text)
    if not urls:
        return text

    integrations = get_active_integrations()
    if not integrations:
        return text

    for url in urls:
        # Remove pontuações comuns do final da URL capturada pelo regex
        clean_url = url.rstrip('.,;()[]{}!?"\'')
        resolved_url = clean_url

        # Detectar plataforma — cobertura ampla de domínios e encurtadores
        platform = None
        url_lower = clean_url.lower()
        if any(d in url_lower for d in ["amazon.com", "amzn.to", "amzn.com", "a.co"]):
            platform = "amazon"
        elif "magazinevoce" in url_lower:
            platform = "magalu"
        elif any(d in url_lower for d in [
            "shopee.com.br", "shopee.co", "shopee.sg", "shopee.ph",
            "shope.ee", "s.shopee.com.br", "shopee.tw",
            "shopee.com.my", "shopee.vn", "shopee.co.id",
            "shopee.co.th",
        ]):
            platform = "shopee"
        elif any(d in url_lower for d in [
            "mercadolivre.com.br", "produto.mercadolivre",
            "lista.mercadolivre", "mercadolibre.com",
            "mlb.link", "ml.link", "mpago.la", "mpago.li",
            "mercadolivre.com", "mercadopago.com.br",
            "meli.to",
        ]):
            platform = "mercadolivre"

        if not platform or platform not in integrations:
            continue

        # Se for link encurtador, resolve antes
        is_short = any(domain in url_lower for domain in [
            "amzn.to", "amzn.com", "a.co",
            "shope.ee", "s.shopee.com.br",
            "mlb.link", "ml.link", "mpago.la", "mpago.li", "meli.to",
        ])

        if is_short:
            resolved_url = await resolve_url_async(clean_url)

        # Atualiza a URL com a tag
        integration = integrations[platform]
        if isinstance(integration, dict):
            tag = integration.get("tag", "")
            cookie = integration.get("cookie", "")
        else:
            tag = integration
            cookie = ""
        new_url = resolved_url
        if platform == "amazon":
            new_url = update_amazon_url(resolved_url, tag)
        elif platform == "magalu":
            new_url = update_magalu_url(resolved_url, tag)
        elif platform == "shopee":
            new_url = update_shopee_url(resolved_url, tag)
        elif platform == "mercadolivre":
            new_url = update_mercadolivre_url(resolved_url, tag, cookie)

        # Substitui a URL original no texto pela URL atualizada
        text = text.replace(clean_url, new_url)

    return text


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
            
    # 6. Gera Link de Afiliado
    # Detecta a plataforma
    platform = None
    if "amazon" in resolved_url or "amzn.to" in resolved_url:
        platform = "amazon"
    elif "magazinevoce" in resolved_url:
        platform = "magalu"
    elif "shopee" in resolved_url or "shope.ee" in resolved_url:
        platform = "shopee"
    elif "mercadolivre" in resolved_url or "mlb.link" in resolved_url or "mpago.la" in resolved_url or "mpago.li" in resolved_url:
        platform = "mercadolivre"
        
    affiliate_url = resolved_url
    if platform == "amazon":
        affiliate_url = update_amazon_url(resolved_url, tag)
    elif platform == "magalu":
        affiliate_url = update_magalu_url(resolved_url, tag)
    elif platform == "shopee":
        affiliate_url = update_shopee_url(resolved_url, tag)
    elif platform == "mercadolivre":
        affiliate_url = update_mercadolivre_url(resolved_url, tag, cookie)

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

