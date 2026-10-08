"""
Painel de controle inline no Telegram: chat privado com o bot, restrito ao admin (Configurações → Bot).
Uma única mensagem é editada a cada toque, como um app.
"""
import threading
from datetime import datetime

from telethon import events, Button
from telethon.errors import MessageNotModifiedError

import database as db


def _admin_id():
    v = (db.get_config("bot_admin_id") or "").strip()
    return int(v) if v.isdigit() else None


def _pausado() -> bool:
    return db.get_config("pausado", "0") == "1"


def _tela_status(tm):
    from niche_scheduler import niche_scheduler
    repasses = db.listar_repasses()
    ativos = sum(1 for r in repasses if r["ativo"])
    texto = (
        f"🤖 <b>Repasse Telegram</b> — {'⏸ PAUSADO' if _pausado() else '🟢 Rodando'}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👤 Contas conectadas: {len(tm.clients)}\n"
        f"🔁 Repasses ativos: {ativos}/{len(repasses)}\n"
        f"📨 Envios hoje: {db.contar_envios_hoje()}\n"
        f"🗓 Agendador: {niche_scheduler.last_status}\n"
        f"🕒 {datetime.now().strftime('%d/%m %H:%M:%S')}"
    )
    botoes = [
        [Button.inline("▶️ Retomar" if _pausado() else "⏸ Pausar tudo", b"p:pausa"),
         Button.inline("🔄 Atualizar", b"p:status")],
        [Button.inline("🔁 Repasses", b"p:repasses"),
         Button.inline("🔍 Buscar ofertas agora", b"p:rodar")],
    ]
    return texto, botoes


def _tela_repasses():
    botoes = [[Button.inline(f"{'✅' if r['ativo'] else '⛔'} {r['descricao'][:40]}", f"p:tog:{r['id']}".encode())]
              for r in db.listar_repasses()]
    botoes.append([Button.inline("⬅️ Voltar", b"p:status")])
    return "🔁 <b>Repasses</b> — toque para ativar/desativar", botoes


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
        if acao == "pausa":
            db.set_config("pausado", "0" if _pausado() else "1")
        elif acao == "rodar":
            from niche_scheduler import niche_scheduler
            if niche_scheduler.last_status == "Executando...":
                aviso = "Já existe uma busca em andamento."
            else:
                threading.Thread(target=niche_scheduler.executar_rotina_completa, daemon=True).start()
                aviso = "Busca iniciada. Toque em Atualizar para acompanhar."
        elif acao.startswith("tog:"):
            r = db.get_repasse(int(acao[4:]))
            if r:
                novo = 0 if r["ativo"] else 1
                db.toggle_repasse(r["id"], novo)
                if novo:
                    tm.iniciar_repasse(r["id"])
                else:
                    tm.parar_repasse(r["id"], r["conta_id"])

        texto, botoes = _tela_repasses() if acao == "repasses" or acao.startswith("tog:") else _tela_status(tm)
        try:
            await event.edit(texto, buttons=botoes, parse_mode="html")
        except MessageNotModifiedError:
            pass
        await event.answer(aviso or "")
