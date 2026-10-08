"""
Painel de controle inline no Telegram: chat privado com o bot, restrito ao admin (Configurações → Bot).
Uma única mensagem é editada a cada toque, como um app.
"""
import asyncio
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
        f"🤖 Piloto: {'ligado' if _piloto() else 'desligado'} · {db.get_config('piloto_status') or '-'}\n"
        f"🕒 {datetime.now().strftime('%d/%m %H:%M:%S')}"
    )
    botoes = [
        [Button.inline("▶️ Retomar" if _pausado() else "⏸ Pausar tudo", b"p:pausa"),
         Button.inline("🔄 Atualizar", b"p:status")],
        [Button.inline("🔁 Repasses", b"p:repasses"),
         Button.inline("📉 Menores preços hoje", b"p:radar")],
        [Button.inline("🤖 Desligar piloto" if _piloto() else "🤖 Ligar piloto", b"p:piloto")],
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


def registrar(bot, tm):
    @bot.on(events.NewMessage(pattern=r"^/(start|painel)", func=lambda e: e.is_private))
    async def _painel(event):
        if event.sender_id != _admin_id():
            await event.respond(
                f"🔒 Acesso restrito.\nSeu ID é <code>{event.sender_id}</code>: "
                f"cadastre-o no app em Configurações → Bot.", parse_mode="html")
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
        elif acao in ("repasses", "radar"):
            tela = _tela_repasses if acao == "repasses" else _tela_radar
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
            destino = db.get_config("radar_destino")
            if not destino:
                aviso = "Defina o destino no app (Radar de Preços)."
            else:
                from oferta import publicar_oferta
                try:  # publicar_oferta é bloqueante (agenda no loop): roda em thread
                    await asyncio.to_thread(publicar_oferta, acao[4:], next(iter(tm.clients), None), destino)
                    aviso = "✅ Publicado!"
                except Exception as e:
                    aviso = f"❌ {e}"[:190]

        texto, botoes = tela() if tela is not _tela_status else tela(tm)
        try:
            await event.edit(texto, buttons=botoes, parse_mode="html")
        except MessageNotModifiedError:
            pass
        await event.answer(aviso or "", alert=bool(aviso and aviso.startswith("❌")))
