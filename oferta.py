"""
Card padrão de oferta (HTML do Telegram) e envio.
Único lugar que define como uma oferta aparece no grupo.
"""
import html
import io
import urllib.request
from datetime import datetime

import database as db

DIAS_MIN_HISTORICO = 7   # só afirma "menor preço" com pelo menos esse histórico real


def brl(valor: float) -> str:
    """1234.5 -> 'R$ 1.234,50'"""
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def formatar_oferta(p: dict, url: str, dias_monitorados: int = 0) -> str:
    preco, menor = p.get("preco_atual"), p.get("menor_preco")
    linhas = [f"🔥 <b>{html.escape(p['nome'][:200])}</b>", ""]
    linhas.append(f"💰 <b>{brl(preco)}</b>" if preco else "💰 Consulte o preço no site")
    if preco and menor and preco <= menor and dias_monitorados >= DIAS_MIN_HISTORICO:
        linhas.append(f"📉 Menor preço em {dias_monitorados} dias de monitoramento")
    linhas.append(f"🏪 {html.escape(p['marketplace'])}")
    linhas += ["", f'🛒 <a href="{html.escape(url, quote=True)}">Comprar agora</a>']
    return "\n".join(linhas)


def baixar_imagem(url: str):
    """Imagem em memória (sem arquivo temporário) ou None."""
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as res:
            buf = io.BytesIO(res.read())
        buf.name = "oferta.jpg"
        return buf
    except Exception as e:
        print(f"[Oferta] Erro ao baixar imagem {url}: {e}")
        return None


def publicar_oferta(p: dict, conta_id: int, destino: str, timeout: int = 30):
    """Monta o card e publica (bot se ativo, senão conta). Bloqueante: chamar fora do loop asyncio."""
    from telegram_manager import telegram_manager

    url = p.get("url_afiliado") or p["url_original"]
    texto = formatar_oferta(p, url, db.contar_dias_historico(p["id"]))
    img = baixar_imagem(p.get("imagem_url"))
    fut = telegram_manager._run(
        telegram_manager.enviar(conta_id, destino, texto, file=img, botao_url=url, html=True))
    return fut.result(timeout=timeout)
