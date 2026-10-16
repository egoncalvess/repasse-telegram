"""
Mercado Livre pela API oficial (api.mercadolibre.com), com o app do DevCenter.

Fase 0 (out/2026): o token de app (client_credentials) recebe 403 em tudo que traz preço; o token de USUÁRIO
(authorization_code + refresh_token) libera os endpoints de ENDPOINTS. /sites/MLB/search segue 403 e nunca é
chamado. Scraping do site do ML é proibido: só esta API.

Config: ml_client_id, ml_client_secret, ml_redirect_uri (credenciais do app, pela GUI);
ml_token, ml_token_exp, ml_refresh_token, ml_token_origem (gravados pelo login, nunca exibidos).
"""
import re
import threading
import time
from urllib.parse import parse_qs, urlencode, urlparse

import database as db
import fontes
from fontes.base import Busca, ErroRequisicao, Fonte, FonteBloqueada, FonteIndisponivel, ProdutoEncontrado

API = "https://api.mercadolibre.com"
AUTH = "https://auth.mercadolivre.com.br/authorization"
SITE = "MLB"
REDIRECT_PADRAO = "https://www.google.com"
URL_PRODUTO = "https://www.mercadolivre.com.br/p/{id}"
CATEGORIA_TESTE = "MLB1648"   # Informática
TERMO_TESTE = "notebook"

# Únicos endpoints que esta fonte chama (aprovados no teste da Fase 0). Fora daqui é recusado antes da rede.
ENDPOINTS = {
    "/oauth/token",
    f"/highlights/{SITE}/category/{{id}}",
    "/products/search",
    "/products/{id}",
    "/products/{id}/items",
    "/categories/{id}",
    f"/sites/{SITE}/domain_discovery/search",
    "/items",
}
ATRIBUTOS_ITEM = "id,title,price,original_price,permalink,thumbnail,status,shipping,category_id"
ID_RE = re.compile(r"MLB-?(\d{6,})", re.IGNORECASE)


class MercadoLivre(Fonte):
    id = "ml"
    nome = "Mercado Livre"
    loja = "mercadolivre"
    tipo = "api_oficial"
    req_por_minuto = 30
    intervalo_min_padrao = 60

    def __init__(self):
        super().__init__()
        self._lock_token = threading.Lock()

    # ── Login do dono do app (authorization_code) ──────────────────────────────

    @staticmethod
    def redirect_uri() -> str:
        return (db.get_config("ml_redirect_uri") or "").strip() or REDIRECT_PADRAO

    def url_autorizacao(self) -> str:
        cid = (db.get_config("ml_client_id") or "").strip()
        if not cid:
            raise FonteBloqueada("Preencha o Client ID do app do Mercado Livre.")
        return AUTH + "?" + urlencode({"response_type": "code", "client_id": cid, "redirect_uri": self.redirect_uri()})

    def conectar(self, url_ou_codigo: str):
        """Troca o código da URL de retorno (…?code=TG-…) pelos tokens e grava no config."""
        texto = (url_ou_codigo or "").strip()
        codigo = parse_qs(urlparse(texto).query).get("code", [""])[0] if "://" in texto else texto
        if not codigo:
            raise FonteBloqueada("A URL colada não tem o código (?code=…). Autorize de novo e copie a URL inteira.")
        self._pedir_token({"grant_type": "authorization_code", "code": codigo, "redirect_uri": self.redirect_uri()})
        fontes.retomar(self.id)

    def conectado(self) -> bool:
        return bool(db.get_config("ml_refresh_token")) or self._token_valido() is not None

    def desconectar(self):
        for k in ("ml_token", "ml_token_exp", "ml_refresh_token", "ml_token_origem"):
            db.set_config(k, "")

    def _token_valido(self) -> str | None:
        tok = db.get_config("ml_token") or ""
        exp = float(db.get_config("ml_token_exp") or 0)
        # token antigo de client_credentials não tem acesso aos endpoints de preço: ignorado
        if tok and db.get_config("ml_token_origem") == "usuario" and time.time() < exp - 120:
            return tok
        return None

    def _token(self, forcar_renovacao=False) -> str:
        with self._lock_token:
            if not forcar_renovacao:
                tok = self._token_valido()
                if tok:
                    return tok
            refresh = db.get_config("ml_refresh_token") or ""
            if not refresh:
                raise FonteBloqueada("Mercado Livre não conectado: use Conectar em Configurações.")
            try:
                return self._pedir_token({"grant_type": "refresh_token", "refresh_token": refresh})
            except ErroRequisicao as e:  # refresh_token revogado/expirado (invalid_grant)
                self.desconectar()
                fontes.pausar(self.id, f"a conexão expirou ({e}). Conecte de novo em Configurações.")
                raise FonteBloqueada(fontes.pausada(self.id)) from e

    def _pedir_token(self, campos: dict) -> str:
        cid = (db.get_config("ml_client_id") or "").strip()
        sec = (db.get_config("ml_client_secret") or "").strip()
        if not cid or not sec:
            raise FonteBloqueada("Preencha Client ID e Client Secret do app do Mercado Livre.")
        dados = self.http.post(API + "/oauth/token", "/oauth/token",
                               data={"client_id": cid, "client_secret": sec} | campos)
        if not isinstance(dados, dict) or not dados.get("access_token"):
            raise FonteIndisponivel("Resposta do /oauth/token sem access_token.")
        db.set_config("ml_token", dados["access_token"])
        db.set_config("ml_token_exp", str(time.time() + float(dados.get("expires_in") or 21600)))
        db.set_config("ml_token_origem", "usuario")
        if dados.get("refresh_token"):  # o ML devolve um refresh_token novo a cada uso: guarda sempre o último
            db.set_config("ml_refresh_token", dados["refresh_token"])
        return dados["access_token"]

    # ── Requisições ────────────────────────────────────────────────────────────

    def _get(self, endpoint: str, caminho: str, params=None, cache_ttl=0):
        if endpoint not in ENDPOINTS:
            raise ValueError(f"Endpoint não aprovado para o Mercado Livre: {endpoint}")
        return self.http.get(API + caminho, endpoint, params=params, cache_ttl=cache_ttl,
                             headers={"Authorization": "Bearer " + self._token()},
                             renovar_auth=lambda: {"Authorization": "Bearer " + self._token(forcar_renovacao=True)})

    # ── Busca ──────────────────────────────────────────────────────────────────

    def buscar(self, busca: Busca) -> list[ProdutoEncontrado]:
        valor = (busca.valor or "").strip()
        if not valor:
            return []
        if busca.tipo == "termo":
            return self._por_termo(valor, busca.limite)
        if busca.tipo == "categoria":
            return self._por_categoria(valor.upper(), busca.limite)
        if busca.tipo == "produto":
            p = self._por_produto(valor)
            return [p] if p else []
        raise ValueError(f"Tipo de busca desconhecido: {busca.tipo}")

    def _por_termo(self, termo: str, limite: int) -> list[ProdutoEncontrado]:
        dados = self._get("/products/search", "/products/search", cache_ttl=300,
                          params={"status": "active", "site_id": SITE, "q": termo, "limit": max(1, min(limite, 50))})
        alvos = [(r["id"], r.get("name") or "", _primeira_foto(r), r.get("domain_id"))
                 for r in (dados.get("results") or [])[:limite] if r.get("id")]
        return self._com_precos(alvos)

    def _por_categoria(self, categoria: str, limite: int) -> list[ProdutoEncontrado]:
        dados = self._get(f"/highlights/{SITE}/category/{{id}}", f"/highlights/{SITE}/category/{categoria}",
                          cache_ttl=600)
        conteudo = (dados.get("content") or [])[:limite]
        produtos = [c["id"] for c in conteudo if c.get("type") == "PRODUCT"]
        itens = [c["id"] for c in conteudo if c.get("type") == "ITEM"]

        alvos = []
        for pid in produtos:
            try:
                p = self._get("/products/{id}", f"/products/{pid}", cache_ttl=86400)
            except ErroRequisicao:
                continue
            alvos.append((pid, p.get("name") or "", _primeira_foto(p), categoria))
        encontrados = self._com_precos(alvos)
        encontrados += self._itens(itens, categoria)
        return encontrados

    def _por_produto(self, valor: str) -> ProdutoEncontrado | None:
        m = ID_RE.search(valor)
        if not m:
            raise ValueError("Informe o código do produto (MLB…) ou o link dele no Mercado Livre.")
        mlb = "MLB" + m.group(1)
        eh_item = "://" in valor and "/p/" not in valor  # link de anúncio (produto.mercadolivre…/MLB-…)
        if not eh_item:
            try:
                p = self._get("/products/{id}", f"/products/{mlb}", cache_ttl=86400)
                res = self._com_precos([(mlb, p.get("name") or "", _primeira_foto(p), p.get("domain_id"))])
                return res[0] if res else None
            except ErroRequisicao as e:
                if e.status != 404:
                    raise
        res = self._itens([mlb], None)
        return res[0] if res else None

    def _com_precos(self, alvos) -> list[ProdutoEncontrado]:
        """Produtos de catálogo: o preço é o menor entre os anúncios ativos do produto."""
        import dedup
        encontrados, erro = [], None
        for pid, nome, foto, categoria in alvos:
            try:
                dados = self._get("/products/{id}/items", f"/products/{pid}/items", cache_ttl=300)
            except ErroRequisicao:
                continue  # produto sem anúncios ativos (404)
            except FonteIndisponivel as e:
                erro = e
                continue
            ofertas = [i for i in (dados.get("results") or []) if _num(i.get("price"))]
            if not ofertas:
                continue
            melhor = min(ofertas, key=lambda i: _num(i["price"]))
            url = URL_PRODUTO.format(id=pid)
            encontrados.append(ProdutoEncontrado(
                chave=dedup.chave_produto(url), nome=nome, url=url, preco=_num(melhor["price"]),
                preco_original=_original(melhor), imagem_url=foto,
                frete_gratis=bool((melhor.get("shipping") or {}).get("free_shipping")),
                categoria=melhor.get("category_id") or categoria, loja=self.nome))
        if erro and not encontrados:
            raise erro
        return encontrados

    def _itens(self, ids, categoria) -> list[ProdutoEncontrado]:
        """Anúncios avulsos (fora do catálogo), 20 por chamada."""
        import dedup
        encontrados = []
        for i in range(0, len(ids), 20):
            lote = ",".join(ids[i:i + 20])
            for res in self._get("/items", "/items", params={"ids": lote, "attributes": ATRIBUTOS_ITEM}, cache_ttl=300):
                b = res.get("body") or {}
                if res.get("code") != 200 or b.get("status") != "active" or not _num(b.get("price")):
                    continue
                url = b.get("permalink") or ""
                chave = dedup.chave_produto(url) or "ml:" + ID_RE.search(b["id"]).group(1)
                encontrados.append(ProdutoEncontrado(
                    chave=chave, nome=b.get("title") or "", url=url, preco=_num(b["price"]),
                    preco_original=_original(b), imagem_url=_https(b.get("thumbnail")),
                    frete_gratis=bool((b.get("shipping") or {}).get("free_shipping")),
                    categoria=b.get("category_id") or categoria, loja=self.nome))
        return encontrados

    # ── Teste manual ───────────────────────────────────────────────────────────

    def testar(self) -> dict:
        """Libera bloqueios anteriores e faz uma chamada a cada endpoint aprovado."""
        db.liberar_endpoints(self.id)
        fontes.retomar(self.id)
        self.http.limpar_cache()
        r: dict[str, str] = {}

        def passo(endpoint, fn):
            try:
                res = fn()
                r[endpoint] = "ok"
                return res
            except Exception as e:  # o teste mostra o motivo de cada endpoint, sem parar no primeiro
                r[endpoint] = str(e)[:200]
                return None

        if not passo("/oauth/token", lambda: self._token(forcar_renovacao=bool(db.get_config("ml_refresh_token")))):
            return {"ok": False, "endpoints": r, "mensagem": r["/oauth/token"]}

        hl = passo(f"/highlights/{SITE}/category/{{id}}",
                   lambda: self._get(f"/highlights/{SITE}/category/{{id}}", f"/highlights/{SITE}/category/{CATEGORIA_TESTE}"))
        ps = passo("/products/search", lambda: self._get("/products/search", "/products/search",
                                                         params={"status": "active", "site_id": SITE,
                                                                 "q": TERMO_TESTE, "limit": 1}))
        conteudo = (hl or {}).get("content") or []
        pid = next((c["id"] for c in conteudo if c.get("type") == "PRODUCT"), None) or \
            next((x.get("id") for x in (ps or {}).get("results") or []), None)
        item = next((c["id"] for c in conteudo if c.get("type") == "ITEM"), None)
        if pid:
            passo("/products/{id}", lambda: self._get("/products/{id}", f"/products/{pid}"))
            pi = passo("/products/{id}/items", lambda: self._get("/products/{id}/items", f"/products/{pid}/items"))
            item = item or next((x.get("item_id") for x in (pi or {}).get("results") or []), None)
        passo("/categories/{id}", lambda: self._get("/categories/{id}", f"/categories/{CATEGORIA_TESTE}"))
        passo(f"/sites/{SITE}/domain_discovery/search",
              lambda: self._get(f"/sites/{SITE}/domain_discovery/search", f"/sites/{SITE}/domain_discovery/search",
                                params={"q": TERMO_TESTE, "limit": 1}))
        if item:
            passo("/items", lambda: self._get("/items", "/items", params={"ids": item, "attributes": ATRIBUTOS_ITEM}))

        essenciais = ("/products/search", "/products/{id}/items")
        ok = all(r.get(e) == "ok" for e in essenciais)
        falhas = [e for e, s in r.items() if s != "ok"]
        msg = "Conectado: busca e preços funcionando." if ok else "Busca indisponível: " + ", ".join(falhas)
        if ok and falhas:
            msg += f" (sem acesso a {', '.join(falhas)})"
        return {"ok": ok, "endpoints": r, "mensagem": msg}


def _num(v) -> float | None:
    try:
        return float(v) if v not in (None, "") and float(v) > 0 else None
    except (TypeError, ValueError):
        return None


def _original(i: dict) -> float | None:
    preco, original = _num(i.get("price")), _num(i.get("original_price"))
    return original if original and preco and original > preco else None


def _https(url):
    return url.replace("http://", "https://") if url else None


def _primeira_foto(p: dict):
    fotos = p.get("pictures") or []
    return _https((fotos[0] or {}).get("url") or (fotos[0] or {}).get("secure_url")) if fotos else None
