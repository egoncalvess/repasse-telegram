import urllib.request
import urllib.parse
import json
import re
import random
from datetime import datetime, timedelta
import database as db

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0"
]

NICHES = {
    "Som automotivo": ["som automotivo", "alto falante automotivo", "subwoofer carro", "multimidia automotiva"],
    "Peças de computador": ["placa de video rtx", "processador ryzen", "memoria ram ddr4", "ssd nvme 1tb"],
    "Beleza": ["perfume importado", "hidratante cerave", "protetor solar facial", "maquiagem batom"],
    "Tênis": ["tenis nike masculino", "tenis adidas casual", "tenis corrida masculino", "tenis casual"],
    "Moda": ["camiseta masculina algodao", "jaqueta corta vento", "calca jeans", "vestido midi"],
    "Produtos de casa": ["air fryer fritadeira", "robo aspirador", "mop giratorio", "jogo panelas"],
    "Peças de carro": ["amortecedor carro par", "pastilha de freio", "oleo motor 5w30", "farol led carro"]
}

MARKETPLACES = ["Mercado Livre"]

# Logs de saúde do scraper
SCRAPING_LOGS = {
    "status": "idle",
    "last_run": None,
    "errors": [],
    "platform_status": {
        "Mercado Livre": "OK"
    }
}

def scrape_mercadolivre(query: str, limit: int = 15) -> list[dict]:
    """Busca produtos no Mercado Livre usando a API oficial pública com suporte a requests e urllib."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    url = f"https://api.mercadolibre.com/sites/MLB/search?q={urllib.parse.quote(query)}&limit={limit}"
    
    try:
        data = None
        try:
            import requests
            res = requests.get(url, headers=headers, timeout=8)
            if res.status_code == 200:
                data = res.json()
            else:
                raise ValueError(f"HTTP {res.status_code}")
        except Exception:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as response:
                data = json.loads(response.read().decode("utf-8"))
                
        if not data:
            raise ValueError("Sem dados")

        products = []
        for item in data.get("results", []):
            img = item.get("thumbnail", "")
            if "-I.jpg" in img:
                img = img.replace("-I.jpg", "-O.jpg")
            elif img.startswith("http://"):
                img = img.replace("http://", "https://")
            
            products.append({
                "id": f"ML-{item['id']}",
                "nome": item["title"],
                "marketplace": "Mercado Livre",
                "url_original": item["permalink"],
                "url_afiliado": item["permalink"],
                "imagem_url": img,
                "preco_atual": item["price"]
            })
        if products:
            return products
        raise ValueError("Sem produtos")
    except Exception as e:
        error_msg_api = f"[Mercado Livre API] Falha: {e}"
        print(error_msg_api)
        SCRAPING_LOGS["errors"].append(error_msg_api)
        return []

def scrape_shopee(query: str, limit: int = 10) -> list[dict]:
    return []

def scrape_amazon(query: str, limit: int = 10) -> list[dict]:
    return []

def scrape_magalu(query: str, limit: int = 10) -> list[dict]:
    return []

def scrape_aliexpress(query: str, limit: int = 10) -> list[dict]:
    return []

def executar_busca_diaria(progress_callback=None):
    """
    Busca produtos de todos os nichos nos marketplaces ativos e salva no banco.
    Apenas dados obtidos em tempo real são salvos; falhas ficam em SCRAPING_LOGS.
    """
    SCRAPING_LOGS["status"] = "running"
    SCRAPING_LOGS["errors"] = []
    SCRAPING_LOGS["last_run"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    for p in SCRAPING_LOGS["platform_status"]:
        SCRAPING_LOGS["platform_status"][p] = "OK"
        
    total_steps = len(NICHES) * len(MARKETPLACES)
    step = 0
    produtos_inseridos = 0
    
    for nicho, queries in NICHES.items():
        if progress_callback:
            progress_callback(f"Processando nicho: {nicho}...")
            
        for marketplace in MARKETPLACES:
            query = random.choice(queries)
            step += 1
            
            if progress_callback:
                progress_callback(f"[{step}/{total_steps}] Sincronizando {nicho} em {marketplace}...")
                
            # 1. Tenta buscar em tempo real via Mercado Livre
            results = []
            try:
                results = scrape_mercadolivre(query, limit=10)
            except Exception as e:
                print(f"[Mercado Livre] Scraper error: {e}")
                
            # 2. Sem dado real, não há post: falha fica registrada e o nicho é pulado.
            if not results:
                SCRAPING_LOGS["platform_status"][marketplace] = "FALHA"
                if progress_callback:
                    progress_callback(f"⚠️ Sem resultados reais para {nicho} em {marketplace}. Nicho pulado.")

            # Salva todos os produtos gerados/coletados no banco de dados SQLite
            for p in results:
                p["nicho"] = nicho
                try:
                    db.salvar_produto_nicho(p)
                    produtos_inseridos += 1
                except Exception as db_err:
                    print(f"Erro ao salvar produto {p['id']}: {db_err}")
                    
    # Pruna preços históricos maiores que 90 dias
    try:
        db.prunar_precos_historicos_90_dias()
    except Exception as e:
        print(f"Erro ao prunar preços históricos: {e}")
        
    SCRAPING_LOGS["status"] = "warning" if SCRAPING_LOGS["errors"] or not produtos_inseridos else "success"
    if progress_callback:
        progress_callback(f"Rotina de busca concluída. {produtos_inseridos} produtos reais salvos no painel.")
