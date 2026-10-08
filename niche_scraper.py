"""
Busca de ofertas por nicho no Mercado Livre via API oficial (token de app do DevCenter).
Busca pública (/sites/MLB/search) e páginas do site estão bloqueadas para robôs desde 2026;
o que funciona com token: destaques (mais vendidos) por categoria + detalhes dos itens.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

import database as db

ML_API = "https://api.mercadolibre.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# Nicho -> categoria raiz do ML (destaques = mais vendidos da categoria)
NICHES = {
    "Som automotivo": "MLB1747",       # Acessórios para Veículos
    "Peças de computador": "MLB1648",  # Informática
    "Beleza": "MLB1246",               # Beleza e Cuidado Pessoal
    "Tênis": "MLB1430",                # Calçados, Roupas e Bolsas
    "Moda": "MLB1430",
    "Produtos de casa": "MLB1574",     # Casa, Móveis e Decoração
    "Peças de carro": "MLB1747",
}

MARKETPLACES = ["Mercado Livre"]

# Logs de saúde do scraper (lidos pelo dashboard)
SCRAPING_LOGS = {
    "status": "idle",
    "last_run": None,
    "errors": [],
    "platform_status": {"Mercado Livre": "OK"},
}


class FonteBloqueada(Exception):
    """A fonte recusou acesso (sem credencial, token inválido ou bloqueio): não adianta insistir nesta rodada."""


# ── API Mercado Livre ─────────────────────────────────────────────────────────

def _ml_req(path: str, data: bytes = None, auth: bool = True, tentativas: int = 3):
    headers = {"Accept": "application/json", "User-Agent": UA}
    if auth:
        headers["Authorization"] = "Bearer " + _ml_token()
    for i in range(tentativas):
        try:
            req = urllib.request.Request(ML_API + path, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < tentativas - 1:
                time.sleep(2 ** (i + 1))  # backoff: 2s, 4s
                continue
            corpo = e.read().decode("utf-8", errors="ignore")[:200]
            if e.code in (400, 401, 403):
                raise FonteBloqueada(f"HTTP {e.code} em {path.split('?')[0]}: {corpo}")
            raise


def _ml_token() -> str:
    cid = (db.get_config("ml_client_id") or "").strip()
    sec = (db.get_config("ml_client_secret") or "").strip()
    if not cid or not sec:
        raise FonteBloqueada("API do Mercado Livre não configurada (Configurações → Mercado Livre).")
    tok = db.get_config("ml_token") or ""
    if tok and time.time() < float(db.get_config("ml_token_exp") or 0) - 60:
        return tok
    body = urllib.parse.urlencode({"grant_type": "client_credentials",
                                   "client_id": cid, "client_secret": sec}).encode()
    dados = _ml_req("/oauth/token", data=body, auth=False)
    db.set_config("ml_token", dados["access_token"])
    db.set_config("ml_token_exp", str(time.time() + dados.get("expires_in", 21600)))
    return dados["access_token"]


def _oferta_ml(id_, nome, preco, original, link, img) -> dict:
    return {
        "id": f"ML-{id_}", "nome": nome, "marketplace": "Mercado Livre",
        "url_original": link, "url_afiliado": link, "imagem_url": (img or "").replace("http://", "https://"),
        "preco_atual": preco, "preco_original": original if original and preco and original > preco else None,
    }


def buscar_destaques_ml(categoria: str, limite: int = 20) -> list[dict]:
    """Mais vendidos da categoria, com preço real (e preço riscado quando houver)."""
    conteudo = _ml_req(f"/highlights/MLB/category/{categoria}").get("content", [])[:limite]
    itens = [c["id"] for c in conteudo if c.get("type") == "ITEM"]
    produtos = [c["id"] for c in conteudo if c.get("type") == "PRODUCT"]

    ofertas = []
    for i in range(0, len(itens), 20):  # /items aceita até 20 ids por chamada
        lote = ",".join(itens[i:i + 20])
        attrs = "id,title,price,original_price,permalink,thumbnail,status"
        for res in _ml_req(f"/items?ids={lote}&attributes={attrs}"):
            b = res.get("body") or {}
            if res.get("code") == 200 and b.get("status") == "active" and b.get("price"):
                ofertas.append(_oferta_ml(b["id"], b["title"], b["price"], b.get("original_price"),
                                          b["permalink"], b.get("thumbnail")))
    for pid in produtos:  # produtos de catálogo: preço vem do vencedor da buy box
        p = _ml_req(f"/products/{pid}")
        bb = p.get("buy_box_winner") or {}
        if bb.get("price"):
            img = (p.get("pictures") or [{}])[0].get("url")
            ofertas.append(_oferta_ml(pid, p.get("name", ""), bb["price"], bb.get("original_price"),
                                      p.get("permalink") or f"https://www.mercadolivre.com.br/p/{pid}", img))
    return ofertas


def testar_conexao_ml() -> str:
    """Usado pelo botão 'Testar conexão': token + uma categoria."""
    db.set_config("ml_token", "")  # força token novo com as credenciais atuais
    ofertas = buscar_destaques_ml("MLB1648", limite=5)
    return f"Conectado! {len(ofertas)} ofertas lidas de Informática (ex.: {ofertas[0]['nome'][:40]})" if ofertas \
        else "Conectado, mas a categoria de teste veio vazia."


# ── Rotina ────────────────────────────────────────────────────────────────────

def executar_busca_diaria(progress_callback=None):
    """Busca os destaques de cada nicho e salva no banco. Só dados reais; falhas ficam em SCRAPING_LOGS."""
    def log(msg):
        if progress_callback:
            progress_callback(msg)

    SCRAPING_LOGS.update(status="running", errors=[], last_run=datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
    SCRAPING_LOGS["platform_status"]["Mercado Livre"] = "OK"

    produtos_inseridos = 0
    cache = {}  # categoria -> ofertas (nichos que compartilham categoria não repetem chamada)
    for idx, (nicho, categoria) in enumerate(NICHES.items(), 1):
        log(f"[{idx}/{len(NICHES)}] Buscando destaques de {nicho} no Mercado Livre...")
        try:
            if categoria not in cache:
                cache[categoria] = buscar_destaques_ml(categoria)
        except FonteBloqueada as e:
            # Circuit breaker: sem acesso, os outros nichos falhariam igual
            SCRAPING_LOGS["platform_status"]["Mercado Livre"] = "BLOQUEADO"
            SCRAPING_LOGS["errors"].append(f"[Mercado Livre] {e}")
            log(f"⛔ Mercado Livre indisponível: {e}")
            break
        except Exception as e:
            SCRAPING_LOGS["errors"].append(f"[Mercado Livre] {nicho}: {e}")
            log(f"⚠️ Falha em {nicho}: {e}")
            continue

        for p in cache[categoria]:
            try:
                db.salvar_produto_nicho({**p, "nicho": nicho})
                produtos_inseridos += 1
            except Exception as db_err:
                print(f"Erro ao salvar produto {p['id']}: {db_err}")

    try:
        db.prunar_precos_historicos_90_dias()
    except Exception as e:
        print(f"Erro ao prunar preços históricos: {e}")

    SCRAPING_LOGS["status"] = "warning" if SCRAPING_LOGS["errors"] or not produtos_inseridos else "success"
    log(f"Rotina de busca concluída. {produtos_inseridos} produtos reais salvos no painel.")
