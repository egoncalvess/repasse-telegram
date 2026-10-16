"""
Card padrão de oferta (HTML do Telegram) e publicação a partir do Radar de Preços.
Único lugar que define como uma oferta aparece no grupo.
"""
import html
import os

import database as db

DIAS_MIN_HISTORICO = 7   # só afirma "menor preço" com pelo menos esse histórico real
JANELA_REPETIDA_H = 24   # não republica o mesmo produto dentro dessa janela


def brl(valor: float) -> str:
    """1234.5 -> 'R$ 1.234,50'"""
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def desconto_loja(p: dict) -> int | None:
    """% de desconto sobre o preço "de" informado pela loja; None sem preço original real maior que o atual."""
    hoje, original = p["preco_hoje"], p.get("preco_original")
    if original and hoje and original > hoje:
        pct = round((1 - hoje / original) * 100)
        return pct if pct > 0 else None
    return None


def selo_historico(p: dict) -> str | None:
    """Destaque honesto, calculado só com preços realmente observados (canais e fontes de busca)."""
    hoje, minimo, media, dias = p["preco_hoje"], p.get("minimo"), p.get("media"), p.get("dias") or 0
    if dias >= DIAS_MIN_HISTORICO and hoje <= minimo:
        return f"🏆 Menor preço em {dias} dias monitorados"
    if dias >= 3 and media and hoje < media * 0.95:
        return f"📉 {round((1 - hoje / media) * 100)}% abaixo da média de {dias} dias"
    return None


def selo(p: dict) -> str | None:
    """Histórico real primeiro; sem ele, o desconto sobre o preço "de" real da loja."""
    destaque = selo_historico(p)
    if destaque:
        return destaque
    pct = desconto_loja(p)
    return f"🏷️ De {brl(p['preco_original'])} por {brl(p['preco_hoje'])} (-{pct}%)" if pct else None


def desconto_pct(p: dict) -> float:
    """Maior desconto comprovado: sobre o preço "de" da loja ou sobre a média do histórico (3+ dias)."""
    hoje, media, dias = p["preco_hoje"], p.get("media"), p.get("dias") or 0
    historico = (1 - hoje / media) * 100 if dias >= 3 and media else 0
    return max(desconto_loja(p) or 0, historico, 0)


def formatar_oferta(p: dict, url: str) -> str:
    pct = desconto_loja(p)
    preco = (f"💰 De <s>{brl(p['preco_original'])}</s> por <b>{brl(p['preco_hoje'])}</b> (-{pct}%)" if pct
             else f"💰 <b>{brl(p['preco_hoje'])}</b>")
    linhas = [f"🔥 <b>{html.escape(p['nome'][:200])}</b>", "", preco]
    destaque = selo_historico(p)
    if destaque:
        linhas.append(destaque)
    linhas.append(f"🏪 {html.escape(p['loja'])}")
    linhas += ["", f'🛒 <a href="{html.escape(url, quote=True)}">Comprar agora</a>']
    return "\n".join(linhas)


def publicar_oferta(chave: str, conta_id, destino: str, timeout: int = 60, origem: str = "manual"):
    """Publica o produto do radar (bot se ativo, senão conta). Bloqueante: chamar fora do loop asyncio."""
    from telegram_manager import telegram_manager

    itens = db.menores_precos_do_dia(chave=chave, limit=1)
    if not itens:
        raise RuntimeError("Produto sem preço registrado hoje.")
    if db.ofertas_recentes({chave}, JANELA_REPETIDA_H):
        raise RuntimeError(f"Produto já publicado nas últimas {JANELA_REPETIDA_H}h.")
    p = itens[0]

    async def _publicar():
        from affiliate_helper import converter_links
        url, nao_convertidos = await converter_links(p["url"])
        if nao_convertidos:
            raise RuntimeError(f"Link de {p['loja']} sem conversão para afiliado: configure em Integrações.")
        url = url.strip()
        foto = p["imagem"] if p.get("imagem") and os.path.exists(p["imagem"]) else None
        await telegram_manager.enviar(conta_id, destino, formatar_oferta(p, url), file=foto, botao_url=url, html=True)

    try:
        telegram_manager._run(_publicar()).result(timeout=timeout)
    except Exception as e:
        db.registrar_publicacao(chave, destino, "falha", str(e))
        raise
    db.registrar_publicacao(chave, destino, "enviado", origem)
    db.marcar_ofertas({chave})
