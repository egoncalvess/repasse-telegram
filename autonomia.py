"""
Rotinas autônomas (rodam no loop asyncio do TelegramManager, junto com repasses e bot):

- Piloto automático: a cada X minutos publica a melhor oferta REAL do radar (com selo de queda),
  respeitando janela de horário, limite diário, pausa global, afiliação e repetição em 24h.
- Vigia: reconecta contas/bot que caírem e avisa o admin.
- Manutenção diária: backup do banco (mantém 7) e resumo do dia para o admin.
"""
import asyncio
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import database as db

PASTA_BACKUP = Path("data/backups")
_ultimo_alerta: dict[str, float] = {}


def cfg(chave: str, padrao: str) -> str:
    return db.get_config(chave, padrao) or padrao


def dentro_do_horario(inicio: str, fim: str, agora: str = None) -> bool:
    """Janela HH:MM; '00:00'-'00:00' = dia todo; aceita janela que cruza a meia-noite (22:00–06:00)."""
    if inicio == fim == "00:00":
        return True
    agora = agora or datetime.now().strftime("%H:%M")
    return inicio <= agora <= fim if inicio <= fim else (agora >= inicio or agora <= fim)


async def alertar(tm, chave: str, texto: str, intervalo_s: int = 3600):
    """Mensagem privada para o admin pelo bot, no máximo 1 por chave a cada intervalo."""
    print(f"[Alerta] {texto}")
    admin = cfg("bot_admin_id", "")
    if not (tm.bot and admin.isdigit()) or time.time() - _ultimo_alerta.get(chave, 0) < intervalo_s:
        return
    _ultimo_alerta[chave] = time.time()
    try:
        await tm.bot.send_message(int(admin), f"⚠️ {texto}")
    except Exception as e:
        print(f"[Alerta] Não foi possível avisar o admin: {e}")


# ── Piloto automático ─────────────────────────────────────────────────────────

def publicados_pelo_piloto_hoje() -> int:
    conn = db.get_conn()
    n = conn.execute("SELECT COUNT(*) FROM publicacoes WHERE status='enviado' AND detalhes='piloto' "
                     "AND data >= date('now', 'localtime')").fetchone()[0]
    conn.close()
    return n


async def ciclo_piloto(tm) -> str:
    """Uma rodada do piloto. Retorna o que aconteceu (para log/painel)."""
    from oferta import selo, publicar_oferta

    if cfg("piloto_ativo", "0") != "1":
        return "desligado"
    if cfg("pausado", "0") == "1":
        return "pausa global"
    if not dentro_do_horario(cfg("piloto_inicio", "08:00"), cfg("piloto_fim", "22:00")):
        return "fora do horário"
    maximo = int(cfg("piloto_max_dia", "10"))
    if publicados_pelo_piloto_hoje() >= maximo:
        return f"limite diário atingido ({maximo})"
    destino = cfg("radar_destino", "")
    if not destino:
        return "sem destino (Radar de Preços)"

    from buscador import permite_publicar
    # 200: produtos novos das buscas (sem histórico, só com preço "de" da loja) ficam no fim da ordenação
    candidatos = [p for p in db.menores_precos_do_dia(limit=200)
                  if selo(p) and not db.ofertas_recentes({p["chave"]}, 24) and permite_publicar(p)]
    conta_id = next(iter(tm.clients), None)
    for p in candidatos:
        try:
            await asyncio.to_thread(publicar_oferta, p["chave"], conta_id, destino, origem="piloto")
            return f"publicado: {p['nome'][:40]} ({selo(p)})"
        except RuntimeError as e:
            if "sem conversão" in str(e):  # sem afiliação possível: tenta o próximo
                continue
            raise
    return "nenhuma oferta com queda real agora"


async def loop_piloto(tm):
    while True:
        try:
            resultado = await ciclo_piloto(tm)
            if resultado.startswith("publicado"):
                print(f"[Piloto] {resultado}")
            db.set_config("piloto_status", f"{datetime.now():%H:%M} {resultado}")
        except Exception as e:
            db.set_config("piloto_status", f"{datetime.now():%H:%M} erro: {e}"[:200])
            await alertar(tm, "piloto", f"Piloto automático falhou ao publicar: {e}")
        await asyncio.sleep(max(5, int(cfg("piloto_intervalo_min", "30"))) * 60)


# ── Vigia + manutenção ────────────────────────────────────────────────────────

def backup_diario() -> str | None:
    """Cópia consistente do banco (API de backup do SQLite) uma vez por dia; mantém as 7 mais novas."""
    hoje = datetime.now().strftime("%Y-%m-%d")
    destino = PASTA_BACKUP / f"repasse-{hoje}.db"
    if destino.exists():
        return None
    PASTA_BACKUP.mkdir(parents=True, exist_ok=True)
    origem, copia = db.get_conn(), sqlite3.connect(destino)
    with copia:
        origem.backup(copia)
    origem.close()
    copia.close()
    for antigo in sorted(PASTA_BACKUP.glob("repasse-*.db"))[:-7]:
        antigo.unlink()
    return str(destino)


def texto_resumo() -> str:
    conn = db.get_conn()
    hoje_br = datetime.now().strftime("%d/%m/%Y") + "%"
    rep = dict(conn.execute("SELECT status, COUNT(*) FROM historico WHERE data LIKE ? GROUP BY status",
                            (hoje_br,)).fetchall())
    pub = dict(conn.execute("SELECT status, COUNT(*) FROM publicacoes WHERE data >= date('now', 'localtime') "
                            "GROUP BY status").fetchall())
    conn.close()
    radar = db.resumo_radar()
    return (f"📊 <b>Resumo do dia {datetime.now():%d/%m}</b>\n"
            f"🔁 Repasses: {rep.get('Sucesso', 0)} enviados · {rep.get('Ignorada', 0)} ignorados · "
            f"{rep.get('Falha', 0)} falhas\n"
            f"📤 Radar/piloto: {pub.get('enviado', 0)} publicados · {pub.get('falha', 0)} falhas\n"
            f"📉 Radar: {radar['produtos']} produtos · {radar['precos_hoje']} preços hoje")


async def loop_manutencao(tm):
    while True:
        try:
            for conta_id, client in list(tm.clients.items()):  # vigia: reconecta quem caiu
                if not client.is_connected():
                    await alertar(tm, f"conta{conta_id}", f"Conta {conta_id} desconectou; reconectando...")
                    await client.connect()
            if tm.bot and not tm.bot.is_connected():
                await tm.bot.connect()

            arquivo = await asyncio.to_thread(backup_diario)
            if arquivo:
                print(f"[Manutenção] Backup salvo em {arquivo}")

            hoje = datetime.now().strftime("%Y-%m-%d")
            admin = cfg("bot_admin_id", "")
            if (datetime.now().strftime("%H:%M") >= cfg("resumo_hora", "22:00")
                    and cfg("resumo_ultimo_dia", "") != hoje and tm.bot and admin.isdigit()):
                await tm.bot.send_message(int(admin), texto_resumo(), parse_mode="html")
                db.set_config("resumo_ultimo_dia", hoje)
        except Exception as e:
            print(f"[Manutenção] {e}")
        await asyncio.sleep(300)


async def iniciar(tm):
    """Sobe as rotinas autônomas no loop do TelegramManager (referências fortes em tm._tasks)."""
    import fontes
    from buscador import loop_buscador

    loop = asyncio.get_running_loop()
    # Bloqueio de fonte acontece numa thread do buscador: o alerta ao admin roda no loop do bot
    fontes.ao_bloquear(lambda fid, texto: asyncio.run_coroutine_threadsafe(
        alertar(tm, f"fonte-{fid}-{texto[:50]}", texto), loop))
    for rotina in (loop_piloto, loop_manutencao, loop_buscador):
        task = asyncio.create_task(rotina(tm))
        tm._tasks.add(task)
    print("[Autonomia] Piloto automático, buscador e manutenção ativos.")
