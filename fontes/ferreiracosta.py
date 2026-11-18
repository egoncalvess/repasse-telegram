"""
Ferreira Costa (www.ferreiracosta.com): scraping de páginas públicas, sem API de afiliados conhecida.

robots.txt (nov/2026) permite /produto/ e /Categoria/, mas proíbe /pesquisa, /busca e /search?_query: por isso
esta fonte NÃO busca por termo, só por categoria (slug ou link) e por produto (código ou link).

Os dados vêm do JSON que o próprio site embute na página (__NEXT_DATA__, Next.js) e, como reserva na página de
produto, do JSON-LD schema.org/Product. Nenhum seletor de CSS: mudança de layout não quebra a extração.

Preço: salePrice (preço para qualquer forma de pagamento). O preço Pix (spotPrice) é condicional e não é usado.
Preço "de": priceList, só quando maior que o atual. Os preços variam por filial; vale a filial padrão do site.
"""
import json
import re

import database as db
import fontes
from fontes.base import Busca, ErroRequisicao, Fonte, ProdutoEncontrado

SITE = "https://www.ferreiracosta.com"
URL_PRODUTO = SITE + "/produto/{id}"
URL_CATEGORIA = SITE + "/Categoria/{slug}"
CATEGORIA_TESTE = "refrigeradores-conservadores-e-freezers"
HEADERS_HTML = {"Accept": "text/html,application/xhtml+xml"}

NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
LD_JSON_RE = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
PRODUTO_RE = re.compile(r"(?:/produto/)?(\d{4,})(?:[/?#]|$)", re.IGNORECASE)
CATEGORIA_RE = re.compile(r"/Categoria/([\w-]+)", re.IGNORECASE)
SLUG_RE = re.compile(r"^[\w-]+$")


class FerreiraCosta(Fonte):
    id = "fc"
    nome = "Ferreira Costa"
    loja = "ferreiracosta"
    tipo = "scraping"
    tipos_busca = ("categoria", "produto")   # termo: /pesquisa e /busca proibidos no robots.txt
    req_por_minuto = 6
    intervalo_min_padrao = 120

    # ── Busca ──────────────────────────────────────────────────────────────────

    def buscar(self, busca: Busca) -> list[ProdutoEncontrado]:
        valor = (busca.valor or "").strip()
        if not valor:
            return []
        if busca.tipo == "categoria":
            return self._por_categoria(_slug_categoria(valor), busca.limite)
        if busca.tipo == "produto":
            p = self._por_produto(_id_produto(valor))
            return [p] if p else []
        if busca.tipo == "termo":
            raise ValueError("A Ferreira Costa não permite busca automática por termo (robots.txt). "
                             "Use uma categoria (link /Categoria/…) ou o link do produto.")
        raise ValueError(f"Tipo de busca desconhecido: {busca.tipo}")

    def _pagina(self, url: str, endpoint: str, cache_ttl: int) -> str:
        html = self.http.get(url, endpoint, headers=HEADERS_HTML, cache_ttl=cache_ttl)
        if not isinstance(html, str):
            raise ErroRequisicao(200, f"{endpoint} não devolveu HTML.")
        return html

    def _por_categoria(self, slug: str, limite: int) -> list[ProdutoEncontrado]:
        html = self._pagina(URL_CATEGORIA.format(slug=slug), "/Categoria/{slug}", cache_ttl=600)
        props = _next_props(html)
        itens = (((props.get("filterProducts") or {}).get("data") or {}).get("products")) or []
        encontrados = []
        for item in itens:
            p = self._montar(item, categoria=slug)
            if p:
                encontrados.append(p)
            if len(encontrados) >= limite:
                break
        return encontrados

    def _por_produto(self, pid: str) -> ProdutoEncontrado | None:
        html = self._pagina(URL_PRODUTO.format(id=pid), "/produto/{id}", cache_ttl=300)
        props = _next_props(html)
        dados = props.get("productData") or {}
        if dados.get("id"):
            if dados.get("available") is False:
                return None
            item = dados | {"prices": props.get("productPrices") or dados.get("prices") or []}
            p = self._montar(item, categoria=_categoria_do_produto(dados))
            if p:
                return p
        return self._de_json_ld(html, pid)

    def _montar(self, item: dict, categoria: str | None) -> ProdutoEncontrado | None:
        import dedup
        pid = str(item.get("id") or "").strip()
        preco, original = _precos(item.get("prices") or [])
        if not pid or not preco:
            return None
        url = URL_PRODUTO.format(id=pid)
        return ProdutoEncontrado(chave=dedup.chave_produto(url), nome=(item.get("description") or "").strip(),
                                 url=url, preco=preco, preco_original=original,
                                 imagem_url=_imagem(item.get("mediaLinks") or []), categoria=categoria,
                                 loja=self.nome)

    def _de_json_ld(self, html: str, pid: str) -> ProdutoEncontrado | None:
        """Reserva: schema.org/Product (o mesmo que o Google lê). Aqui o preço é o da oferta publicada."""
        import dedup
        for bloco in LD_JSON_RE.findall(html):
            try:
                ld = json.loads(bloco)
            except ValueError:
                continue
            if not isinstance(ld, dict) or ld.get("@type") != "Product":
                continue
            oferta = ld.get("offers") or {}
            if isinstance(oferta, list):
                oferta = oferta[0] if oferta else {}
            if "OutOfStock" in str(oferta.get("availability") or ""):
                return None
            preco = _num(oferta.get("price"))
            if not preco:
                return None
            spec = oferta.get("priceSpecification") or {}
            riscado = _num(spec.get("price")) if "Strikethrough" in str(spec.get("priceType") or "") else None
            imagem = ld.get("image")
            url = URL_PRODUTO.format(id=pid)
            return ProdutoEncontrado(chave=dedup.chave_produto(url), nome=(ld.get("name") or "").strip(), url=url,
                                     preco=preco, preco_original=riscado if riscado and riscado > preco else None,
                                     imagem_url=imagem[0] if isinstance(imagem, list) and imagem else imagem or None,
                                     loja=self.nome)
        return None

    # ── Teste manual ───────────────────────────────────────────────────────────

    def testar(self) -> dict:
        db.liberar_endpoints(self.id)
        fontes.retomar(self.id)
        self.http.limpar_cache()
        r: dict[str, str] = {}
        lista = []
        try:
            lista = self._por_categoria(CATEGORIA_TESTE, 1)
            r["/Categoria/{slug}"] = "ok" if lista else "página sem produtos (o formato do site mudou?)"
        except Exception as e:
            r["/Categoria/{slug}"] = str(e)[:200]
        if lista:
            try:
                p = self._por_produto(lista[0].chave.split(":")[1])
                r["/produto/{id}"] = "ok" if p else "produto sem preço (o formato do site mudou?)"
            except Exception as e:
                r["/produto/{id}"] = str(e)[:200]
        ok = bool(r) and all(v == "ok" for v in r.values())
        msg = "Ferreira Costa respondendo: categorias e produtos." if ok else \
            "Falha: " + "; ".join(f"{k}: {v}" for k, v in r.items() if v != "ok")
        return {"ok": ok, "endpoints": r, "mensagem": msg}


# ── Extração ───────────────────────────────────────────────────────────────────

def _id_produto(valor: str) -> str:
    m = PRODUTO_RE.search(valor.strip())
    if not m:
        raise ValueError("Informe o código do produto ou o link dele (ferreiracosta.com/produto/…).")
    return m.group(1)


def _slug_categoria(valor: str) -> str:
    m = CATEGORIA_RE.search(valor)
    if m:
        return m.group(1)
    if SLUG_RE.match(valor):
        return valor
    raise ValueError("Informe o link da categoria (ferreiracosta.com/Categoria/…) ou só o final dele.")


def _next_props(html: str) -> dict:
    m = NEXT_DATA_RE.search(html or "")
    if not m:
        return {}
    try:
        return (json.loads(m.group(1)).get("props") or {}).get("pageProps") or {}
    except (ValueError, AttributeError):
        return {}


def _num(v) -> float | None:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _precos(precos: list) -> tuple[float | None, float | None]:
    """(preço atual, preço "de" real ou None) da primeira oferta com preço de venda."""
    for p in precos:
        venda = _num(p.get("salePrice"))
        if venda:
            lista = _num(p.get("priceList"))
            return venda, lista if lista and lista > venda else None
    return None, None


def _imagem(midias: list) -> str | None:
    """Imagem grande padrão; sem ela, a miniatura; sem ela, a primeira imagem qualquer."""
    fotos = [m for m in midias if m.get("imageUrl")]
    for tipo in ("IMAGEM", "THUMB"):
        for m in fotos:
            if m.get("linkType") == tipo and m.get("isDefault"):
                return m["imageUrl"]
    return fotos[0]["imageUrl"] if fotos else None


def _categoria_do_produto(dados: dict) -> str | None:
    """Slug da categoria do produto (o mesmo valor aceito numa busca por categoria)."""
    cat = (dados.get("breadCrumbs") or {}).get("category") if isinstance(dados.get("breadCrumbs"), dict) else None
    m = CATEGORIA_RE.search("/" + (cat.get("link") or "")) if isinstance(cat, dict) else None
    return m.group(1) if m else None
