"""
Painel de controle inline no Telegram: chat privado com o bot, restrito ao admin (Configurações → Bot).
Uma única mensagem é editada a cada toque, como um app.

Comandos (só admin): /status (ou /start, /painel), /buscar <termo>, /buscas, /fila.
"""
import asyncio
import html
from datetime import datetime

from telethon import events, Button
from telethon.errors import MessageNotModifiedError

import database as db
from oferta import brl, selo


def _admin_id():
    v = (db.get_config("bot_admin_id") or "").strip()
    return int(v) if v.isdigit() else None


def _piloto() -> bool:
    return db.get_config("piloto_ativo", "0") == "1"


def _pausado() -> bool:
    return db.get_config("pausado", "0") == "1"


def _modo() -> str:
    return db.get_config("piloto_modo", "automatico") or "automatico"


def _tela_status(tm):
    repasses = db.listar_repasses()
    ativos = sum(1 for r in repasses if r["ativo"])
    radar = db.resumo_radar()
    texto = (
        f"🤖 <b>Repasse Telegram</b> — {'⏸ PAUSADO' if _pausado() else '🟢 Rodando'}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👤 Contas conectadas: {len(tm.clients)}\n"
        f"🔁 Repasses ativos: {ativos}/{len(repasses)}\n"
        f"📨 Envios hoje: {db.contar_envios_hoje()}\n"
        f"📉 Radar: {radar['produtos']} produtos · {radar['precos_hoje']} preços hoje\n"
        f"🤖 Piloto: {'ligado' if _piloto() else 'desligado'} ({'aprovação' if _modo() == 'aprovacao' else 'automático'})"
        f" · {db.get_config('piloto_status') or '-'}\n"
        f"🔎 Buscas ativas: {sum(1 for b in db.listar_buscas() if b['ativo'])} · "
        f"📥 Aguardando aprovação: {db.contar_fila_pendente()}\n"
        f"🕒 {datetime.now().strftime('%d/%m %H:%M:%S')}"
    )
    botoes = [
        [Button.inline("▶️ Retomar" if _pausado() else "⏸ Pausar tudo", b"p:pausa"),
         Button.inline("🔄 Atualizar", b"p:status")],
        [Button.inline("🔁 Repasses", b"p:repasses"),
         Button.inline("📉 Menores preços hoje", b"p:radar")],
        [Button.inline("🔎 Buscas", b"p:buscas"),
         Button.inline(f"📥 Fila ({db.contar_fila_pendente()})", b"p:fila")],
        [Button.inline("🤖 Desligar piloto" if _piloto() else "🤖 Ligar piloto", b"p:piloto"),
         Button.inline("✋ Modo aprovação" if _modo() != "aprovacao" else "⚡ Modo automático", b"p:modo")],
    ]
    return texto, botoes


def _tela_repasses():
    botoes = [[Button.inline(f"{'✅' if r['ativo'] else '⛔'} {r['descricao'][:40]}", f"p:tog:{r['id']}".encode())]
              for r in db.listar_repasses()]
    botoes.append([Button.inline("⬅️ Voltar", b"p:status")])
    return "🔁 <b>Repasses</b> — toque para ativar/desativar", botoes


def _tela_radar():
    itens = db.menores_precos_do_dia(limit=5)
    if not itens:
        texto = "📉 <b>Menores preços hoje</b>\n\nNenhuma oferta com preço registrada hoje."
    else:
        linhas = [f"{i}. {p['nome'][:45]}\n    <b>{brl(p['preco_hoje'])}</b> · {p['loja']}"
                  + (f"\n    {selo(p)}" if selo(p) else "") for i, p in enumerate(itens, 1)]
        destino = db.get_config("radar_destino") or "(defina no app: Radar de Preços)"
        texto = "📉 <b>Menores preços hoje</b>\n\n" + "\n\n".join(linhas) + f"\n\n📤 publica em: <code>{destino}</code>"
    botoes = [[Button.inline(f"📤 Publicar {i}", f"p:pub:{p['chave']}".encode()) for i, p in enumerate(itens, 1)]]
    botoes.append([Button.inline("⬅️ Voltar", b"p:status")])
    return texto, [b for b in botoes if b]


def _tela_buscas():
    buscas = db.listar_buscas()
    if not buscas:
        texto = "🔎 <b>Buscas</b>\n\nNenhuma busca cadastrada. Use /buscar &lt;termo&gt; e toque em Monitorar."
    else:
        linhas = [f"{'✅' if b['ativo'] else '⛔'} <b>{html.escape(b['nome'][:40])}</b> · {b['fonte_id']} · "
                  f"{b['tipo']}: {html.escape(b['valor'][:30])}\n"
                  f"    a cada {b['intervalo_min']} min · última: {b['ultima_execucao'] or '—'} · "
                  f"{html.escape((b['ultimo_status'] or '—')[:60])}" for b in buscas[:15]]
        texto = "🔎 <b>Buscas</b> — toque para ativar/desativar\n\n" + "\n".join(linhas)
    botoes = [[Button.inline(f"{'✅' if b['ativo'] else '⛔'} {b['nome'][:28]}", f"p:btog:{b['id']}".encode()),
               Button.inline("▶️ Executar agora", f"p:bexe:{b['id']}".encode())] for b in buscas[:15]]
    botoes.append([Button.inline("⬅️ Voltar", b"p:status")])
    return texto, botoes


def _tela_fila():
    itens = db.listar_fila("pendente", limit=10)
    if not itens:
        texto = "📥 <b>Aguardando aprovação</b>\n\nNada pendente."
    else:
        linhas = [f"{i}. {html.escape((f['nome'] or f['chave'])[:50])} · {html.escape(f['loja'] or '')}\n"
                  f"    desde {f['criado_em'][11:16]}" for i, f in enumerate(itens, 1)]
        texto = "📥 <b>Aguardando aprovação</b>\n\n" + "\n".join(linhas)
    botoes = [[Button.inline(f"✅ Publicar {i}", f"p:fpub:{f['id']}".encode()),
               Button.inline(f"🗑 Descartar {i}", f"p:fdes:{f['id']}".encode())] for i, f in enumerate(itens, 1)]
    botoes.append([Button.inline("⬅️ Voltar", b"p:status")])
    return texto, botoes


def _texto_oferta(p: dict) -> str:
    """Nome, preço e loja do produto (linha de menores_precos_do_dia)."""
    from oferta import desconto_loja
    pct = desconto_loja(p)
    preco = (f"de <s>{brl(p['preco_original'])}</s> por <b>{brl(p['preco_hoje'])}</b> (-{pct}%)" if pct
             else f"<b>{brl(p['preco_hoje'])}</b>")
    return f"{html.escape(p['nome'][:60])}\n    {preco} · {html.escape(p['loja'])}"


def _resultado_busca(termo: str):
    """/buscar: busca agora em todas as fontes ativas (bloqueante: rodar em thread)."""
    import buscador
    import fontes
    if not fontes.ativas():
        return ("Nenhuma fonte de busca ativa. No app: Configurações → Mercado Livre → "
                "Usar nas buscas automáticas."), None
    achados, erros = buscador.buscar_agora(termo)
    top = achados[:5]
    if not top:
        texto = f"🔎 Nada encontrado para “{html.escape(termo)}”."
    else:
        linhas = []
        for i, p in enumerate(top, 1):
            pct = round((1 - p.preco / p.preco_original) * 100) if p.preco_original else 0
            preco = (f"de <s>{brl(p.preco_original)}</s> por <b>{brl(p.preco)}</b> (-{pct}%)" if pct > 0
                     else f"<b>{brl(p.preco)}</b>")
            linhas.append(f"{i}. {html.escape(p.nome[:60])}\n    {preco} · {html.escape(p.loja)}"
                          + (" · frete grátis" if p.frete_gratis else ""))
        texto = (f"🔎 <b>{html.escape(termo)}</b> — {len(achados)} encontrado(s), top {len(top)}\n\n"
                 + "\n\n".join(linhas))
    if erros:
        texto += "\n\n⚠️ " + html.escape("; ".join(erros))[:300]
    botoes = [[Button.inline(f"📤 Publicar {i}", f"p:spub:{p.chave}".encode()),
               Button.inline(f"👁 Monitorar {i}", f"p:mon:{p.chave}".encode())] for i, p in enumerate(top, 1)]
    return texto, botoes or None


async def _publicar(tm, chave: str, origem: str = "manual") -> str:
    destino = db.get_config("radar_destino")
    if not destino:
        return "❌ Defina o destino no app (Radar de Preços)."
    from oferta import publicar_oferta
    try:  # publicar_oferta é bloqueante (agenda no loop): roda em thread
        await asyncio.to_thread(publicar_oferta, chave, next(iter(tm.clients), None), destino, origem=origem)
        return "✅ Publicado"
    except Exception as e:
        return f"❌ {e}"[:190]


async def avisar_fila(tm, fila_id: int, p: dict):
    """Piloto em modo aprovação: pergunta ao admin, no privado do bot, se publica a oferta."""
    admin = _admin_id()
    if not (tm.bot and admin):
        return
    texto = f"📥 <b>Publicar esta oferta?</b>\n\n{_texto_oferta(p)}" + (f"\n    {selo(p)}" if selo(p) else "")
    await tm.bot.send_message(admin, texto, parse_mode="html", buttons=[
        [Button.inline("✅ Publicar", f"p:fpub:{fila_id}".encode()),
         Button.inline("🗑 Descartar", f"p:fdes:{fila_id}".encode())]])


def registrar(bot, tm):
    async def _negar(event):
        await event.respond(
            f"🔒 Acesso restrito.\nSeu ID é <code>{event.sender_id}</code>: "
            f"cadastre-o no app em Configurações → Bot.", parse_mode="html")

    @bot.on(events.NewMessage(pattern=r"^/buscar(?:@\w+)?(?:\s+([\s\S]+))?$", func=lambda e: e.is_private))
    async def _buscar(event):
        if event.sender_id != _admin_id():
            await _negar(event)
            return
        termo = (event.pattern_match.group(1) or "").strip()
        if not termo:
            await event.respond("Use /buscar seguido do produto. Ex.: /buscar air fryer")
            return
        msg = await event.respond(f"🔎 Buscando “{termo}”...")
        texto, botoes = await asyncio.to_thread(_resultado_busca, termo)
        await msg.edit(texto, buttons=botoes, parse_mode="html")

    @bot.on(events.NewMessage(pattern=r"^/(buscas|fila)(?:@\w+)?$", func=lambda e: e.is_private))
    async def _listas(event):
        if event.sender_id != _admin_id():
            await _negar(event)
            return
        texto, botoes = _tela_buscas() if event.pattern_match.group(1) == "buscas" else _tela_fila()
        await event.respond(texto, buttons=botoes, parse_mode="html")

    @bot.on(events.NewMessage(pattern=r"^/(start|painel|status)", func=lambda e: e.is_private))
    async def _painel(event):
        if event.sender_id != _admin_id():
            await _negar(event)
            return
        texto, botoes = _tela_status(tm)
        await event.respond(texto, buttons=botoes, parse_mode="html")

    @bot.on(events.CallbackQuery(pattern=rb"^p:"))
    async def _acao(event):
        if event.sender_id != _admin_id():
            await event.answer("Acesso restrito.", alert=True)
            return

        acao = event.data.decode()[2:]
        aviso = None
        tela = _tela_status
        if acao == "pausa":
            db.set_config("pausado", "0" if _pausado() else "1")
        elif acao == "piloto":
            db.set_config("piloto_ativo", "0" if _piloto() else "1")
        elif acao == "modo":
            db.set_config("piloto_modo", "automatico" if _modo() == "aprovacao" else "aprovacao")
        elif acao in ("repasses", "radar", "buscas", "fila"):
            tela = {"repasses": _tela_repasses, "radar": _tela_radar, "buscas": _tela_buscas, "fila": _tela_fila}[acao]
        elif acao.startswith("btog:"):
            b = db.get_busca(int(acao[5:]))
            if b:
                db.atualizar_busca(b["id"], {"ativo": 0 if b["ativo"] else 1})
            tela = _tela_buscas
        elif acao.startswith("bexe:"):
            import buscador
            b = db.get_busca(int(acao[5:]))
            tela = _tela_buscas
            if b:
                aviso = f"{b['nome'][:30]}: {await asyncio.to_thread(buscador.executar, b)}"[:190]
        elif acao.startswith(("spub:", "mon:")):
            tela = None  # o resultado do /buscar fica na tela; a resposta vem no aviso
            if acao.startswith("spub:"):
                aviso = await _publicar(tm, acao[5:])
            else:
                import buscador
                aviso = buscador.monitorar(acao[4:])[1][:190]
        elif acao.startswith(("fpub:", "fdes:")):
            item = db.get_fila(int(acao[5:]))
            tela = _tela_fila
            if not item or item["status"] != "pendente":
                aviso = "Já decidido."
            elif acao.startswith("fdes:"):
                db.decidir_fila(item["id"], "descartada")
                aviso = "Descartado"
            else:
                aviso = await _publicar(tm, item["chave"], origem="piloto")
                if aviso.startswith("✅"):
                    db.decidir_fila(item["id"], "aprovada")
        elif acao.startswith("tog:"):
            r = db.get_repasse(int(acao[4:]))
            if r:
                novo = 0 if r["ativo"] else 1
                db.toggle_repasse(r["id"], novo)
                if novo:
                    tm.iniciar_repasse(r["id"])
                else:
                    tm.parar_repasse(r["id"], r["conta_id"])
            tela = _tela_repasses
        elif acao.startswith("pub:"):
            tela = _tela_radar
            aviso = await _publicar(tm, acao[4:])

        if tela is not None:
            texto, botoes = tela() if tela is not _tela_status else tela(tm)
            try:
                await event.edit(texto, buttons=botoes, parse_mode="html")
            except MessageNotModifiedError:
                pass
        try:
            await event.answer(aviso or "", alert=bool(aviso and aviso.startswith("❌")))
        except Exception as e:  # toque respondido tarde demais (ex.: Executar agora demorou): o resultado já está na tela
            print(f"[Painel] Resposta ao toque não entregue: {e}")
