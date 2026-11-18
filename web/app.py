"""
Camada Web do Promo do Baiano — Buscador & Comparador Histórico de Preços (90 dias) + Operação do Radar.
Roda no mesmo processo Python do motor (workers=1), reutilizando o loop do TelegramManager sem duplicar sessões.
"""
import asyncio
import html
import re
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import buscador
import comparador
import database as db
import fontes
import oferta
from web import auth

PASTA_WEB = Path(__file__).resolve().parent
PASTA_RAIZ = PASTA_WEB.parent
PASTA_STATIC = PASTA_WEB / "static"
PASTA_TEMPLATES = PASTA_WEB / "templates"
PASTA_STATIC.mkdir(parents=True, exist_ok=True)
PASTA_TEMPLATES.mkdir(parents=True, exist_ok=True)

EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
DOMINIOS_LOJA = (
    "mercadolivre.com", "produto.mercadolivre", "meli.la",
    "amazon.com.br", "amzn.to", "a.co",
    "shopee.com.br", "s.shopee.com.br", "shope.ee",
    "aliexpress.com", "s.click.aliexpress.com",
    "magazineluiza.com.br", "magalu.com", "magazinevoce.com.br",
    "casasbahia.com.br", "ferreiracosta.com",
)

app = FastAPI(title="Promo do Baiano — Buscador de Preços", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(PASTA_STATIC)), name="static")
templates = Jinja2Templates(directory=str(PASTA_TEMPLATES))


def _brl(valor: float | None) -> str:
    if valor is None:
        return "—"
    return oferta.brl(float(valor))


def _nome_imagem(caminho: str | None) -> str | None:
    if not caminho:
        return None
    nome = Path(caminho).name
    if not nome or Path(nome).suffix.lower() not in EXTENSOES_IMAGEM:
        return None
    arq = db.DATA_DIR / "imagens" / nome
    return f"/imagens/{quote(nome)}" if arq.exists() else None


templates.env.filters["brl"] = _brl
templates.env.filters["img_url"] = _nome_imagem


def _parece_url(texto: str) -> bool:
    t = (texto or "").strip()
    if not t or " " in t:
        return False
    tl = t.lower()
    if tl.startswith(("http://", "https://")):
        return True
    return "/" in tl and any(d in tl for d in DOMINIOS_LOJA)


def _normalizar_url(texto: str) -> str:
    t = texto.strip()
    if not t.lower().startswith(("http://", "https://")):
        return "https://" + t
    return t


def _tema_atual() -> str:
    t = (db.get_config("theme", "dark") or "dark").lower()
    return "light" if t == "light" else "dark"


def _status_motor() -> dict:
    from telegram_manager import telegram_manager as tm
    porta = int(db.get_config("web_port", "8080") or 8080)
    return {
        "bot_online": bool(tm.bot),
        "contas_conectadas": len(tm.clients),
        "pausado": db.get_config("pausado", "0") == "1",
        "fila_pendente": db.contar_fila_pendente(),
        "ip_local": f"http://{auth.obter_ip_rede_local()}:{porta}",
    }


def _sessao_ou_redirect(request: Request):
    """Retorna (payload_sessao, None) se autenticado, ou (None, Response) para redirecionar/bloquear."""
    if not auth.tem_senha_web():
        if auth.eh_acesso_local(request):
            return None, RedirectResponse("/setup-senha", status_code=303)
        return None, templates.TemplateResponse(
            request,
            "bloqueado_remoto.html",
            {"tema": _tema_atual(), "pagina": "auth"},
            status_code=403,
        )
    payload = auth.validar_cookie_sessao(request.cookies.get(auth.COOKIE_NOME))
    if not payload:
        destino = request.url.path
        if request.url.query:
            destino += f"?{request.url.query}"
        return None, RedirectResponse(f"/login?{urlencode({'next': destino})}", status_code=303)
    return payload, None


def _contexto_base(request: Request, payload: str, pagina: str, **extra) -> dict:
    ctx = {
        "request": request,
        "tema": _tema_atual(),
        "pagina": pagina,
        "csrf_token": auth.gerar_csrf(payload),
        "motor": _status_motor(),
    }
    ctx.update(extra)
    return ctx


def _exigir_csrf(request: Request, payload: str, csrf_token: str | None) -> None:
    if not auth.validar_csrf(payload, csrf_token, request=request):
        raise HTTPException(status_code=403, detail="Sessão expirada ou token CSRF inválido.")


def gerar_svg_historico(pontos: list[tuple[str, float]], media: float | None = None) -> str:
    """Gera SVG limpo e responsivo da curva de 90 dias sem bibliotecas externas."""
    if not pontos:
        return ""
    largura, altura = 680, 190
    pad_x, pad_top, pad_bot = 16, 22, 28
    valores = [float(v) for _, v in pontos]
    vmin, vmax = min(valores), max(valores)
    if media is not None:
        vmin = min(vmin, float(media))
        vmax = max(vmax, float(media))
    span = (vmax - vmin) if vmax > vmin else max(vmax * 0.1, 1.0)
    w_util = largura - 2 * pad_x
    h_util = altura - pad_top - pad_bot

    def xy(idx: int, val: float) -> tuple[float, float]:
        x = pad_x + (w_util * idx / (len(pontos) - 1) if len(pontos) > 1 else w_util / 2)
        y = pad_top + h_util * (1.0 - (val - vmin) / span)
        return round(x, 1), round(y, 1)

    coords = [xy(i, float(v)) for i, (_, v) in enumerate(pontos)]
    linha_pts = " ".join(f"{x},{y}" for x, y in coords)
    base_y = pad_top + h_util
    area_pts = f"{coords[0][0]},{base_y} {linha_pts} {coords[-1][0]},{base_y}"

    idx_min = min(range(len(valores)), key=lambda i: valores[i])
    min_x, min_y = coords[idx_min]
    ult_x, ult_y = coords[-1]

    partes = [
        f'<svg class="price-chart" viewBox="0 0 {largura} {altura}" role="img" '
        f'aria-label="Histórico de preços em {len(pontos)} dia(s)">',
        f'<line x1="{pad_x}" y1="{base_y}" x2="{largura - pad_x}" y2="{base_y}" '
        f'stroke="var(--border)" stroke-width="1" />',
    ]
    if media is not None and len(pontos) >= 2:
        _, my = xy(0, float(media))
        partes.append(
            f'<line x1="{pad_x}" y1="{my}" x2="{largura - pad_x}" y2="{my}" '
            f'stroke="var(--ink-2)" stroke-width="1" stroke-dasharray="4 4" opacity="0.65" />'
            f'<text x="{largura - pad_x}" y="{max(12, my - 5)}" text-anchor="end" '
            f'fill="var(--ink-2)" font-size="11">média {_brl(media)}</text>'
        )
    if len(coords) > 1:
        partes.append(f'<polygon points="{area_pts}" fill="var(--accent)" opacity="0.09" />')
        partes.append(
            f'<polyline points="{linha_pts}" fill="none" stroke="var(--accent)" '
            f'stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round" />'
        )
    partes.append(f'<circle cx="{min_x}" cy="{min_y}" r="4.5" fill="var(--drop)" />')
    partes.append(f'<circle cx="{ult_x}" cy="{ult_y}" r="4" fill="var(--accent)" />')
    dia_ini = html.escape(pontos[0][0][5:].replace("-", "/"))
    dia_fim = html.escape(pontos[-1][0][5:].replace("-", "/"))
    partes.append(
        f'<text x="{pad_x}" y="{altura - 7}" fill="var(--ink-2)" font-size="11">{dia_ini}</text>'
        f'<text x="{largura - pad_x}" y="{altura - 7}" text-anchor="end" fill="var(--ink-2)" font-size="11">{dia_fim}</text>'
        f'<text x="{pad_x}" y="14" fill="var(--drop)" font-size="11">mín {_brl(min(valores))}</text>'
    )
    partes.append("</svg>")
    return "".join(partes)


def _enriquecer_quedas(itens: list[dict]) -> list[dict]:
    descartados = db.descartados()
    out = []
    for p in itens:
        if p["chave"] in descartados:
            continue
        antes, pct = oferta.queda(p)
        item = dict(p)
        item["antes_ref"] = antes
        item["queda_pct"] = pct
        item["selo"] = oferta.selo(p)
        item["publicavel"] = oferta.publicavel(p["chave"])
        out.append(item)
    return out


# ── Rotas Públicas e Estáticas ────────────────────────────────────────────────

@app.get("/health")
def health():
    return JSONResponse({"ok": True})


@app.get("/fonts/{nome}")
def servir_fonte(nome: str):
    seguro = Path(nome).name
    if seguro != nome or not seguro.lower().endswith(".ttf"):
        raise HTTPException(status_code=404)
    arq = PASTA_RAIZ / "assets" / "fonts" / seguro
    if not arq.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(arq, media_type="font/ttf", headers={"Cache-Control": "public, max-age=604800"})


@app.get("/assets/{nome}")
def servir_asset(nome: str):
    seguro = Path(nome).name
    if seguro != nome or seguro not in ("logo.png", "logo.ico"):
        raise HTTPException(status_code=404)
    arq = PASTA_RAIZ / "assets" / seguro
    if not arq.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(arq, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/imagens/{nome}")
def servir_imagem(nome: str, request: Request):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        raise HTTPException(status_code=401)
    seguro = Path(nome).name
    if seguro != nome or ".." in nome or Path(seguro).suffix.lower() not in EXTENSOES_IMAGEM:
        raise HTTPException(status_code=404)
    arq = (db.DATA_DIR / "imagens" / seguro).resolve()
    pasta_imgs = (db.DATA_DIR / "imagens").resolve()
    if not str(arq).startswith(str(pasta_imgs)) or not arq.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(arq, headers={"Cache-Control": "private, max-age=86400"})


# ── Autenticação e Setup Inicial ──────────────────────────────────────────────

@app.get("/setup-senha", response_class=HTMLResponse)
def setup_senha_form(request: Request):
    if auth.tem_senha_web():
        return RedirectResponse("/", status_code=303)
    if not auth.eh_acesso_local(request):
        return templates.TemplateResponse(
            request, "bloqueado_remoto.html", {"tema": _tema_atual(), "pagina": "auth"}, status_code=403
        )
    return templates.TemplateResponse(
        request, "setup_senha.html", {"tema": _tema_atual(), "pagina": "auth", "erro": None}
    )


@app.post("/setup-senha", response_class=HTMLResponse)
def setup_senha_salvar(
    request: Request,
    senha: str = Form(""),
    confirmar: str = Form(""),
):
    if auth.tem_senha_web():
        return RedirectResponse("/login", status_code=303)
    if not auth.eh_acesso_local(request):
        raise HTTPException(status_code=403)
    if len(senha.strip()) < 6:
        return templates.TemplateResponse(
            request,
            "setup_senha.html",
            {"tema": _tema_atual(), "pagina": "auth", "erro": "Use pelo menos 6 caracteres."},
            status_code=400,
        )
    if senha.strip() != confirmar.strip():
        return templates.TemplateResponse(
            request,
            "setup_senha.html",
            {"tema": _tema_atual(), "pagina": "auth", "erro": "As senhas não conferem."},
            status_code=400,
        )
    auth.definir_senha_web(senha)
    resp = RedirectResponse("/", status_code=303)
    cookie = auth.criar_cookie_sessao()
    resp.set_cookie(
        auth.COOKIE_NOME,
        cookie,
        max_age=auth.SESSAO_TTL_S,
        httponly=True,
        samesite="lax",
        secure=(request.headers.get("x-forwarded-proto") == "https"),
    )
    return resp


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/"):
    if not auth.tem_senha_web():
        if auth.eh_acesso_local(request):
            return RedirectResponse("/setup-senha", status_code=303)
        return templates.TemplateResponse(
            request, "bloqueado_remoto.html", {"tema": _tema_atual(), "pagina": "auth"}, status_code=403
        )
    if auth.validar_cookie_sessao(request.cookies.get(auth.COOKIE_NOME)):
        return RedirectResponse("/", status_code=303)
    destino = next if next.startswith("/") and not next.startswith("//") else "/"
    return templates.TemplateResponse(
        request, "login.html", {"tema": _tema_atual(), "pagina": "auth", "erro": None, "next": destino}
    )


@app.post("/login", response_class=HTMLResponse)
def login_entrar(request: Request, senha: str = Form(""), next: str = Form("/")):
    ip = auth.ip_cliente(request)
    destino = next if next.startswith("/") and not next.startswith("//") else "/"
    if auth.bloqueado_login(ip):
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "tema": _tema_atual(),
                "pagina": "auth",
                "erro": "Muitas tentativas incorretas. Aguarde 15 minutos.",
                "next": destino,
            },
            status_code=429,
        )
    if not auth.verificar_senha_web(senha):
        auth.registrar_falha_login(ip)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"tema": _tema_atual(), "pagina": "auth", "erro": "Senha incorreta.", "next": destino},
            status_code=401,
        )
    auth.limpar_falhas_login(ip)
    resp = RedirectResponse(destino, status_code=303)
    resp.set_cookie(
        auth.COOKIE_NOME,
        auth.criar_cookie_sessao(),
        max_age=auth.SESSAO_TTL_S,
        httponly=True,
        samesite="lax",
        secure=(request.headers.get("x-forwarded-proto") == "https"),
    )
    return resp


@app.post("/logout")
def logout(request: Request, csrf_token: str = Form("")):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    out = RedirectResponse("/login", status_code=303)
    out.delete_cookie(auth.COOKIE_NOME)
    return out


@app.post("/tema")
def alternar_tema(request: Request, csrf_token: str = Form(""), retorno: str = Form("/")):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    novo = "light" if _tema_atual() == "dark" else "dark"
    db.set_config("theme", novo)
    dest = retorno if retorno.startswith("/") and not retorno.startswith("//") else "/"
    return RedirectResponse(dest, status_code=303)


# ── Home: Buscador & Comparador Histórico de Preços (90 dias) ─────────────────

@app.get("/", response_class=HTMLResponse)
async def home_comparador(
    request: Request,
    q: str = Query(""),
    msg: str = Query(""),
    erro: str = Query(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp

    consulta = (q or "").strip()
    modo = "inicio"
    resultado_termo = None
    resultado_link = None
    aviso_link = None
    svg_link = ""
    quedas_hoje = []
    buscas_ativas = []
    resumo = {}

    if consulta and _parece_url(consulta):
        modo = "link"
        url_norm = _normalizar_url(consulta)
        resultado_link, aviso_link = await asyncio.to_thread(comparador.consultar_link, url_norm)
        if resultado_link:
            pontos = await asyncio.to_thread(db.historico_precos, resultado_link["chave"], 90)
            svg_link = gerar_svg_historico(pontos, resultado_link.get("media"))
            resultado_link["publicavel"] = oferta.publicavel(resultado_link["chave"])
    elif consulta:
        modo = "termo"
        resultado_termo = await asyncio.to_thread(comparador.comparar, consulta, 30)
    else:
        resumo = await asyncio.to_thread(db.resumo_radar)
        brutas = await asyncio.to_thread(db.menores_precos_do_dia, 12)
        quedas_hoje = _enriquecer_quedas(brutas)
        todas_buscas = await asyncio.to_thread(db.listar_buscas)
        buscas_ativas = [b for b in todas_buscas if b.get("ativo") and b.get("tipo") == "termo"][:8]

    return templates.TemplateResponse(
        request,
        "comparador.html",
        _contexto_base(
            request,
            payload,
            "comparador",
            q=consulta,
            modo=modo,
            resultado_termo=resultado_termo,
            resultado_link=resultado_link,
            aviso_link=aviso_link,
            svg_link=svg_link,
            quedas_hoje=quedas_hoje,
            buscas_ativas=buscas_ativas,
            resumo=resumo,
            msg=msg,
            erro=erro,
        ),
    )


@app.post("/comparar/ao-vivo")
async def comparar_ao_vivo(
    request: Request,
    termo: str = Form(""),
    csrf_token: str = Form(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    limpo = (termo or "").strip()
    if not limpo:
        return RedirectResponse("/", status_code=303)
    achados, erros = await asyncio.to_thread(buscador.buscar_agora, limpo, 12)
    params = {"q": limpo}
    if achados:
        params["msg"] = f"Busca ao vivo concluída: {len(achados)} oferta(s) lida(s) agora e salvas no histórico."
    elif erros:
        params["erro"] = " · ".join(erros)[:220]
    else:
        params["msg"] = "Nenhuma fonte ativa com busca por termo retornou resultados novos agora."
    return RedirectResponse(f"/?{urlencode(params)}", status_code=303)


# ── Detalhe do Produto e Ações (Gráfico 90d, Monitorar, Publicar) ─────────────

@app.get("/produto", response_class=HTMLResponse)
async def detalhe_produto(
    request: Request,
    chave: str = Query(""),
    msg: str = Query(""),
    erro: str = Query(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    prod = await asyncio.to_thread(db.get_produto, chave)
    if not prod:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")
    stats_lista = await asyncio.to_thread(db.estatisticas_precos, 90, [chave])
    stats = comparador._com_tendencia(stats_lista[0]) if stats_lista else None
    pontos = await asyncio.to_thread(db.historico_precos, chave, 90)
    svg = gerar_svg_historico(pontos, stats["media"] if stats else None)
    destino_radar = (db.get_config("radar_destino") or "").strip()

    return templates.TemplateResponse(
        request,
        "produto.html",
        _contexto_base(
            request,
            payload,
            "comparador",
            produto=prod,
            stats=stats,
            pontos=list(reversed(pontos[-30:])),
            svg_historico=svg,
            publicavel=oferta.publicavel(chave),
            destino_radar=destino_radar,
            msg=msg,
            erro=erro,
        ),
    )


@app.post("/produto/monitorar")
async def monitorar_produto(
    request: Request,
    chave: str = Form(""),
    csrf_token: str = Form(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    bid, texto = await asyncio.to_thread(buscador.monitorar, chave)
    param = "msg" if bid else "erro"
    return RedirectResponse(f"/produto?{urlencode({'chave': chave, param: texto})}", status_code=303)


@app.post("/produto/publicar")
async def publicar_produto_web(
    request: Request,
    chave: str = Form(""),
    csrf_token: str = Form(""),
    retorno: str = Form(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    destino = (db.get_config("radar_destino") or "").strip()
    base_ret = retorno if retorno.startswith("/") and not retorno.startswith("//") else f"/produto?{urlencode({'chave': chave})}"
    sep = "&" if "?" in base_ret else "?"
    if not destino:
        return RedirectResponse(f"{base_ret}{sep}{urlencode({'erro': 'Configure o canal de destino do Radar nas configurações.'})}", status_code=303)

    from telegram_manager import telegram_manager as tm
    conta_id = next(iter(tm.clients), None)
    try:
        await asyncio.to_thread(oferta.publicar_oferta, chave, conta_id, destino, 60, "web")
    except Exception as e:
        return RedirectResponse(f"{base_ret}{sep}{urlencode({'erro': str(e)[:200]})}", status_code=303)
    return RedirectResponse(f"{base_ret}{sep}{urlencode({'msg': 'Oferta publicada com sucesso no Telegram.'})}", status_code=303)


# ── Ofertas do Dia & Fila do Piloto Automático ────────────────────────────────

@app.get("/ofertas", response_class=HTMLResponse)
async def pagina_ofertas(
    request: Request,
    aba: str = Query("quedas"),
    msg: str = Query(""),
    erro: str = Query(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    aba_ativa = "fila" if aba == "fila" else "quedas"
    quedas = []
    fila = []
    if aba_ativa == "fila":
        bruta_fila = await asyncio.to_thread(db.listar_fila, "pendente", 40)
        for item in bruta_fila:
            hoje = await asyncio.to_thread(db.menores_precos_do_dia, 1, item["chave"])
            info = dict(item)
            if hoje:
                info["preco_hoje"] = hoje[0]["preco_hoje"]
                info["selo"] = oferta.selo(hoje[0])
            fila.append(info)
    else:
        brutas = await asyncio.to_thread(db.menores_precos_do_dia, 40)
        quedas = _enriquecer_quedas(brutas)

    return templates.TemplateResponse(
        request,
        "ofertas.html",
        _contexto_base(
            request,
            payload,
            "ofertas",
            aba=aba_ativa,
            quedas=quedas,
            fila=fila,
            msg=msg,
            erro=erro,
        ),
    )


@app.post("/ofertas/descartar")
async def descartar_oferta_web(
    request: Request,
    chave: str = Form(""),
    csrf_token: str = Form(""),
    aba: str = Form("quedas"),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    if chave:
        await asyncio.to_thread(db.descartar, chave)
    return RedirectResponse(f"/ofertas?{urlencode({'aba': aba, 'msg': 'Oferta ocultada por 24 horas.'})}", status_code=303)


@app.post("/ofertas/fila/{fila_id}/aprovar")
async def aprovar_item_fila(
    fila_id: int,
    request: Request,
    csrf_token: str = Form(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    item = await asyncio.to_thread(db.get_fila, fila_id)
    if not item or item.get("status") != "pendente":
        return RedirectResponse("/ofertas?aba=fila&erro=Item+n%C3%A3o+est%C3%A1+mais+pendente.", status_code=303)
    destino = (db.get_config("radar_destino") or "").strip()
    if not destino:
        return RedirectResponse("/ofertas?aba=fila&erro=Configure+o+destino+do+Radar+antes+de+aprovar.", status_code=303)

    from telegram_manager import telegram_manager as tm
    conta_id = next(iter(tm.clients), None)
    try:
        await asyncio.to_thread(oferta.publicar_oferta, item["chave"], conta_id, destino, 60, "fila_web")
        await asyncio.to_thread(db.decidir_fila, fila_id, "aprovada")
    except Exception as e:
        return RedirectResponse(f"/ofertas?{urlencode({'aba': 'fila', 'erro': str(e)[:200]})}", status_code=303)
    return RedirectResponse("/ofertas?aba=fila&msg=Oferta+aprovada+e+publicada.", status_code=303)


@app.post("/ofertas/fila/{fila_id}/descartar")
async def descartar_item_fila(
    fila_id: int,
    request: Request,
    csrf_token: str = Form(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    item = await asyncio.to_thread(db.get_fila, fila_id)
    if item:
        await asyncio.to_thread(db.descartar, item["chave"])
        await asyncio.to_thread(db.decidir_fila, fila_id, "descartada")
    return RedirectResponse("/ofertas?aba=fila&msg=Item+descartado+por+24h.", status_code=303)


# ── Buscas Automáticas e Saúde das Fontes ─────────────────────────────────────

def _listar_saude_fontes() -> list[dict]:
    out = []
    for fid, f in fontes.registro().items():
        ligada = fontes.ativa(fid)
        pausa = fontes.pausada(fid)
        eps = db.endpoints_da_fonte(fid)
        bloqueados = [ep for ep, s in eps.items() if s["status"] == "bloqueado"]
        chamadas_60m = db.contar_chamadas_api(fid, 60)
        conectado = f.conectado() if hasattr(f, "conectado") else True
        if pausa or bloqueados or not conectado:
            estado = "err" if (pausa or bloqueados) else "warn"
        elif ligada:
            estado = "ok"
        else:
            estado = "warn"
        out.append({
            "id": fid,
            "nome": f.nome,
            "ativa": ligada,
            "pausada": pausa,
            "conectado": conectado,
            "bloqueados": bloqueados,
            "chamadas_60m": chamadas_60m,
            "limite_min": fontes.req_por_minuto(f),
            "tipos_busca": list(f.tipos_busca),
            "estado": estado,
        })
    return out


@app.get("/buscas", response_class=HTMLResponse)
async def pagina_buscas(
    request: Request,
    msg: str = Query(""),
    erro: str = Query(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    lista = await asyncio.to_thread(db.listar_buscas)
    saude = await asyncio.to_thread(_listar_saude_fontes)
    return templates.TemplateResponse(
        request,
        "buscas.html",
        _contexto_base(
            request,
            payload,
            "buscas",
            buscas=lista,
            fontes_saude=saude,
            msg=msg,
            erro=erro,
        ),
    )


@app.post("/buscas/nova")
async def criar_busca_web(
    request: Request,
    fonte_id: str = Form("fc"),
    tipo: str = Form("termo"),
    nome: str = Form(""),
    valor: str = Form(""),
    intervalo_min: int = Form(60),
    preco_max: float = Form(0),
    desconto_min_pct: float = Form(0),
    so_frete_gratis: str = Form(""),
    csrf_token: str = Form(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    f = fontes.get(fonte_id)
    val = (valor or "").strip()
    rotulo = (nome or val).strip()[:80]
    if not f or not val:
        return RedirectResponse("/buscas?erro=Preencha+a+fonte+e+o+termo+ou+URL.", status_code=303)
    if tipo not in f.tipos_busca:
        return RedirectResponse(f"/buscas?{urlencode({'erro': f'{f.nome} não aceita busca por {tipo}.'})}", status_code=303)
    await asyncio.to_thread(
        db.adicionar_busca,
        {
            "fonte_id": fonte_id,
            "nome": rotulo,
            "tipo": tipo,
            "valor": val,
            "intervalo_min": max(5, int(intervalo_min or 60)),
            "preco_max": max(0.0, float(preco_max or 0)),
            "desconto_min_pct": max(0.0, float(desconto_min_pct or 0)),
            "so_frete_gratis": 1 if so_frete_gratis else 0,
            "ativo": 1,
        },
    )
    return RedirectResponse("/buscas?msg=Busca+cadastrada.", status_code=303)


@app.post("/buscas/{busca_id}/toggle")
async def alternar_busca_web(busca_id: int, request: Request, csrf_token: str = Form("")):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    b = await asyncio.to_thread(db.get_busca, busca_id)
    if b:
        await asyncio.to_thread(db.atualizar_busca, busca_id, {"ativo": 0 if b.get("ativo") else 1})
    return RedirectResponse("/buscas", status_code=303)


@app.post("/buscas/{busca_id}/executar")
async def executar_busca_web(busca_id: int, request: Request, csrf_token: str = Form("")):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    b = await asyncio.to_thread(db.get_busca, busca_id)
    if not b:
        return RedirectResponse("/buscas?erro=Busca+n%C3%A3o+encontrada.", status_code=303)
    status = await asyncio.to_thread(buscador.executar, b)
    chave_q = "erro" if status.startswith(("erro", "falha", "bloqueado")) else "msg"
    return RedirectResponse(f"/buscas?{urlencode({chave_q: f'{b["nome"]}: {status}'})}", status_code=303)


@app.post("/buscas/{busca_id}/remover")
async def remover_busca_web(busca_id: int, request: Request, csrf_token: str = Form("")):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    await asyncio.to_thread(db.remover_busca, busca_id)
    return RedirectResponse("/buscas?msg=Busca+removida.", status_code=303)


@app.post("/fontes/{fonte_id}/toggle")
async def alternar_fonte_web(fonte_id: str, request: Request, csrf_token: str = Form("")):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    if fontes.get(fonte_id):
        fontes.definir_ativa(fonte_id, not fontes.ativa(fonte_id))
    return RedirectResponse("/buscas", status_code=303)


@app.post("/fontes/{fonte_id}/retomar")
async def retomar_fonte_web(fonte_id: str, request: Request, csrf_token: str = Form("")):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    if fontes.get(fonte_id):
        fontes.retomar(fonte_id)
        await asyncio.to_thread(db.liberar_endpoints, fonte_id)
    return RedirectResponse("/buscas?msg=Fonte+retomada.", status_code=303)


# ── Fase 3: Administração Web (Repasses, Configurações, Contas, Afiliados) ────

@app.get("/repasses", response_class=HTMLResponse)
async def pagina_repasses(
    request: Request,
    msg: str = Query(""),
    erro: str = Query(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    brutos = await asyncio.to_thread(db.listar_repasses)
    repasses = []
    for r in brutos:
        rid = r["id"]
        origens = await asyncio.to_thread(db.listar_origens, rid)
        destinos = await asyncio.to_thread(db.listar_destinos, rid)
        enviadas = await asyncio.to_thread(db.enviadas_hoje, rid)
        item = dict(r)
        item["nome"] = r.get("descricao") or r.get("nome") or f"Repasse #{rid}"
        item["total_enviadas"] = r.get("total", 0)
        item["origens"] = [o.get("origem_nome") or o.get("origem_id") for o in origens]
        item["destinos"] = [d.get("grupo_nome") or d.get("grupo_id") for d in destinos]
        item["enviadas_hoje"] = enviadas
        repasses.append(item)
    historico = await asyncio.to_thread(db.listar_historico, limit=40)
    return templates.TemplateResponse(
        request,
        "repasses.html",
        _contexto_base(
            request,
            payload,
            "repasses",
            repasses=repasses,
            historico=historico,
            msg=msg,
            erro=erro,
        ),
    )


@app.post("/repasses")
async def criar_repasse_web(
    request: Request,
    nome: str = Form(""),
    origens: str = Form(""),
    destinos: str = Form(""),
    substituir_afiliados: str = Form(""),
    exigir_afiliado: str = Form(""),
    proibidas: str = Form(""),
    csrf_token: str = Form(""),
):
    import json
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    limpo_nome = (nome or "").strip()
    if not limpo_nome:
        return RedirectResponse("/repasses?erro=Informe+o+nome+do+repasse.", status_code=303)

    from telegram_manager import telegram_manager as tm
    conta_id = next(iter(tm.clients), None)
    if not conta_id:
        contas = await asyncio.to_thread(db.listar_contas)
        if contas:
            conta_id = contas[0]["id"]

    lista_origens = [x.strip() for x in (origens or "").splitlines() if x.strip()]
    lista_destinos = [x.strip() for x in (destinos or "").splitlines() if x.strip()]
    primeira_origem = lista_origens[0] if lista_origens else ""

    filtros = {
        "substituir_afiliados": bool(substituir_afiliados),
        "exigir_afiliado": bool(exigir_afiliado),
        "links": True,
        "imagens": True,
        "videos": True,
        "audios": True,
    }
    dados = {
        "descricao": limpo_nome,
        "conta_id": conta_id,
        "origem_id": primeira_origem,
        "origem_nome": primeira_origem,
        "filtros": json.dumps(filtros),
        "substituicoes": "[]",
        "delay": 1,
        "limite_diario": 0,
        "horario_inicio": "00:00",
        "horario_fim": "00:00",
        "termos_bloquear": (proibidas or "").strip(),
        "termos_permitir": "",
    }
    rid = await asyncio.to_thread(db.adicionar_repasse, dados)
    if lista_origens:
        await asyncio.to_thread(
            db.set_origens, rid, [{"origem_id": o, "origem_nome": o} for o in lista_origens]
        )
    if lista_destinos:
        await asyncio.to_thread(
            db.set_destinos, rid, [{"grupo_id": d, "grupo_nome": d} for d in lista_destinos]
        )
    return RedirectResponse("/repasses?msg=Repasse+adicionado+com+sucesso.", status_code=303)


@app.post("/repasses/{repasse_id}/toggle")
async def toggle_repasse_web(repasse_id: int, request: Request, csrf_token: str = Form("")):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    r = await asyncio.to_thread(db.get_repasse, repasse_id)
    if r:
        novo = 0 if r.get("ativo") else 1
        await asyncio.to_thread(db.toggle_repasse, repasse_id, novo)
    return RedirectResponse("/repasses", status_code=303)


@app.post("/repasses/{repasse_id}/remover")
async def remover_repasse_web(repasse_id: int, request: Request, csrf_token: str = Form("")):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    await asyncio.to_thread(db.remover_repasse, repasse_id)
    return RedirectResponse("/repasses?msg=Repasse+removido.", status_code=303)


@app.get("/config", response_class=HTMLResponse)
async def pagina_config(
    request: Request,
    msg: str = Query(""),
    erro: str = Query(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    cfg = {
        "piloto_ativo": db.get_config("piloto_ativo", "0"),
        "piloto_desconto_minimo": db.get_config("piloto_desconto_minimo", "15"),
        "piloto_intervalo_minutos": db.get_config("piloto_intervalo_minutos", "30"),
        "piloto_auto_aprovar": db.get_config("piloto_auto_aprovar", "0"),
    }
    api_id = str(db.get_config("telegram_api_id") or "").strip()
    api_hash = str(db.get_config("telegram_api_hash") or "").strip()
    bot_token = str(db.get_config("telegram_bot_token") or "").strip()
    creds_mascaradas = {
        "api_id": f"••••{api_id[-4:]}" if len(api_id) > 4 else ("••••" if api_id else "Não configurado"),
        "api_hash": f"••••••••{api_hash[-4:]}" if len(api_hash) > 4 else ("••••" if api_hash else "Não configurado"),
        "bot_token": f"••••••••{bot_token[-6:]}" if len(bot_token) > 6 else ("••••" if bot_token else "Não configurado"),
    }
    return templates.TemplateResponse(
        request,
        "config.html",
        _contexto_base(
            request,
            payload,
            "config",
            subpagina="geral",
            cfg=cfg,
            creds_mascaradas=creds_mascaradas,
            msg=msg,
            erro=erro,
        ),
    )


@app.post("/config/pausa")
async def toggle_pausa_global(request: Request, csrf_token: str = Form("")):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    atual = db.get_config("pausado", "0")
    novo = "0" if atual == "1" else "1"
    await asyncio.to_thread(db.set_config, "pausado", novo)
    msg = "Pausa global ativada." if novo == "1" else "Operações retomadas."
    return RedirectResponse(f"/config?{urlencode({'msg': msg})}", status_code=303)


@app.post("/config/piloto")
async def salvar_config_piloto(
    request: Request,
    piloto_ativo: str = Form(""),
    piloto_auto_aprovar: str = Form(""),
    piloto_desconto_minimo: int = Form(15),
    piloto_intervalo_minutos: int = Form(30),
    csrf_token: str = Form(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    await asyncio.to_thread(db.set_config, "piloto_ativo", "1" if piloto_ativo else "0")
    await asyncio.to_thread(db.set_config, "piloto_auto_aprovar", "1" if piloto_auto_aprovar else "0")
    await asyncio.to_thread(db.set_config, "piloto_desconto_minimo", str(max(5, int(piloto_desconto_minimo or 15))))
    await asyncio.to_thread(db.set_config, "piloto_intervalo_minutos", str(max(5, int(piloto_intervalo_minutos or 30))))
    return RedirectResponse("/config?msg=Configurações+do+Piloto+salvas.", status_code=303)


@app.post("/config/senha")
async def alterar_senha_web(
    request: Request,
    senha_atual: str = Form(""),
    nova_senha: str = Form(""),
    confirma_senha: str = Form(""),
    csrf_token: str = Form(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    if not auth.verificar_senha_web(senha_atual):
        return RedirectResponse("/config?erro=Senha+atual+incorreta.", status_code=303)
    if (nova_senha or "").strip() != (confirma_senha or "").strip():
        return RedirectResponse("/config?erro=A+nova+senha+e+a+confirma%C3%A7%C3%A3o+n%C3%A3o+conferem.", status_code=303)
    if len((nova_senha or "").strip()) < 6:
        return RedirectResponse("/config?erro=A+nova+senha+precisa+ter+pelo+menos+6+caracteres.", status_code=303)
    auth.definir_senha_web(nova_senha.strip())
    return RedirectResponse("/config?msg=Senha+Web+atualizada+com+sucesso.", status_code=303)


@app.get("/contas", response_class=HTMLResponse)
async def pagina_contas(
    request: Request,
    msg: str = Query(""),
    erro: str = Query(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    contas = await asyncio.to_thread(db.listar_contas)
    from telegram_manager import telegram_manager as tm
    pendente = None
    for cid, (cl, ph) in list(tm._pending.items()):
        pendente = {"conta_id": cid, "telefone": ph}
        break
    canais_radar = []
    for c in contas:
        if c.get("status") == "conectada":
            try:
                chats = await asyncio.to_thread(db.chats_do_radar, c["id"])
                for cid, titulo in chats.items():
                    canais_radar.append({"id": cid, "name": titulo})
            except Exception:
                pass
    return templates.TemplateResponse(
        request,
        "contas.html",
        _contexto_base(
            request,
            payload,
            "contas",
            subpagina="contas",
            contas=contas,
            pendente=pendente,
            canais_radar=canais_radar,
            msg=msg,
            erro=erro,
        ),
    )


@app.post("/contas/solicitar")
async def solicitar_codigo_conta(
    request: Request,
    telefone: str = Form(""),
    apelido: str = Form(""),
    csrf_token: str = Form(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    tel = (telefone or "").strip()
    ap = (apelido or tel).strip()
    if not tel:
        return RedirectResponse("/contas?erro=Informe+o+n%C3%BAmero+de+telefone.", status_code=303)

    from telegram_manager import telegram_manager as tm
    creds = tm.get_creds()
    if not creds.get("api_id") or not creds.get("api_hash"):
        return RedirectResponse("/contas?erro=Configure+telegram_api_id+e+telegram_api_hash+antes+de+conectar.", status_code=303)

    conta_id = await asyncio.to_thread(db.adicionar_conta, tel, ap, "telegram")
    try:
        res = await tm._connect(conta_id, int(creds["api_id"]), creds["api_hash"], "", tel)
        if res == "needs_code":
            return RedirectResponse("/contas?msg=C%C3%B3digo+enviado+ao+Telegram.+Digite-o+abaixo.", status_code=303)
        return RedirectResponse("/contas?msg=Conta+conectada+com+sucesso.", status_code=303)
    except Exception as e:
        return RedirectResponse(f"/contas?{urlencode({'erro': str(e)[:200]})}", status_code=303)


@app.post("/contas/confirmar")
async def confirmar_codigo_conta(
    request: Request,
    conta_id: int = Form(...),
    codigo: str = Form(""),
    senha_2fa: str = Form(""),
    csrf_token: str = Form(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    cod = (codigo or "").strip()
    if not cod:
        return RedirectResponse("/contas?erro=Informe+o+c%C3%B3digo+de+verifica%C3%A7%C3%A3o.", status_code=303)

    from telegram_manager import telegram_manager as tm
    try:
        await tm._sign_in(conta_id, cod, senha_2fa.strip() or None)
        return RedirectResponse("/contas?msg=Conta+autenticada+e+conectada+com+sucesso.", status_code=303)
    except Exception as e:
        return RedirectResponse(f"/contas?{urlencode({'erro': str(e)[:200]})}", status_code=303)


@app.post("/contas/{conta_id}/desconectar")
async def desconectar_conta_web(conta_id: int, request: Request, csrf_token: str = Form("")):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    from telegram_manager import telegram_manager as tm
    await tm._disconnect(conta_id)
    return RedirectResponse("/contas?msg=Conta+desconectada.", status_code=303)


@app.post("/contas/{conta_id}/remover")
async def remover_conta_web(conta_id: int, request: Request, csrf_token: str = Form("")):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    from telegram_manager import telegram_manager as tm
    await tm._disconnect(conta_id)
    await asyncio.to_thread(db.remover_conta, conta_id)
    return RedirectResponse("/contas?msg=Conta+removida.", status_code=303)


@app.get("/afiliados", response_class=HTMLResponse)
async def pagina_afiliados(
    request: Request,
    msg: str = Query(""),
    erro: str = Query(""),
    url_teste: str = Query(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    integracoes = await asyncio.to_thread(db.listar_integracoes)
    tags = {i["tipo"]: i.get("tag", "") for i in integracoes}
    resultado_teste = None
    if url_teste:
        import affiliate_helper
        try:
            url_conv, nao_conv = await affiliate_helper.converter_links(url_teste)
            loja = affiliate_helper.loja_da_url(url_teste)
            sucesso = bool(url_conv and not nao_conv)
            resultado_teste = {
                "loja": (loja or "Não identificada").capitalize(),
                "sucesso": sucesso,
                "url_convertida": url_conv,
                "msg": "Sem conversão oficial para esta URL/loja." if not sucesso else "",
            }
        except Exception as e:
            resultado_teste = {"loja": "Erro", "sucesso": False, "msg": str(e)[:160]}

    return templates.TemplateResponse(
        request,
        "afiliados.html",
        _contexto_base(
            request,
            payload,
            "afiliados",
            subpagina="afiliados",
            tags=tags,
            url_teste=url_teste,
            resultado_teste=resultado_teste,
            msg=msg,
            erro=erro,
        ),
    )


@app.post("/afiliados/salvar")
async def salvar_afiliados_web(
    request: Request,
    tag_amazon: str = Form(""),
    tag_mercadolivre: str = Form(""),
    tag_shopee: str = Form(""),
    tag_magalu: str = Form(""),
    tag_aliexpress: str = Form(""),
    csrf_token: str = Form(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    lojas = {
        "amazon": ("Amazon", tag_amazon),
        "mercadolivre": ("Mercado Livre", tag_mercadolivre),
        "shopee": ("Shopee", tag_shopee),
        "magalu": ("Magalu", tag_magalu),
        "aliexpress": ("AliExpress", tag_aliexpress),
    }
    atuais = {i["tipo"]: i for i in await asyncio.to_thread(db.listar_integracoes)}
    for tipo, (nome, tag_val) in lojas.items():
        v = (tag_val or "").strip()
        if tipo in atuais:
            await asyncio.to_thread(db.atualizar_integracao, atuais[tipo]["id"], nome, tipo, v, "")
        elif v:
            await asyncio.to_thread(db.adicionar_integracao, nome, tipo, v, "")
    return RedirectResponse("/afiliados?msg=Tags+de+afiliado+salvas+com+sucesso.", status_code=303)


@app.post("/afiliados/testar")
async def testar_afiliado_web(
    request: Request,
    url_teste: str = Form(""),
    csrf_token: str = Form(""),
):
    payload, resp = _sessao_ou_redirect(request)
    if resp is not None:
        return resp
    _exigir_csrf(request, payload, csrf_token)
    u = (url_teste or "").strip()
    return RedirectResponse(f"/afiliados?{urlencode({'url_teste': u})}", status_code=303)
