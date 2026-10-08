"""
Gerenciador Telegram — roda Telethon em thread separada com asyncio.
Toda comunicação com a UI é via callbacks thread-safe.
"""
import asyncio
import io
import threading
import json
import re
import time
from datetime import datetime

from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaWebPage

import database as db


class TelegramManager:
    def __init__(self):
        self._tasks: set[asyncio.Task] = set()              # refs fortes: asyncio só guarda refs fracas
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        self.bot: TelegramClient | None = None              # bot oficial: publica e serve o painel
        self.clients: dict[int, TelegramClient] = {}       # conta_id -> client
        self._pending: dict[int, TelegramClient] = {}      # aguardando código
        self._handlers: dict[int, callable] = {}           # repasse_id -> handler fn
        self._daily_count: dict[int, dict] = {}            # repasse_id -> {date, count}

    # ── Loop ────────────────────────────────────────────────────────────────

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _run(self, coro):
        """Envia coroutine para o loop e retorna Future.
        Mantém a task referenciada até terminar; sem isso o GC pode destruí-la no meio (ex.: connect)."""
        async def _keep():
            task = asyncio.current_task()
            self._tasks.add(task)
            try:
                return await coro
            finally:
                self._tasks.discard(task)
        return asyncio.run_coroutine_threadsafe(_keep(), self.loop)

    # ── Credenciais ──────────────────────────────────────────────────────────

    def get_creds(self):
        api_id = db.get_config("api_id")
        api_hash = db.get_config("api_hash")
        if not api_id or not api_hash:
            raise ValueError("Configure API ID e API Hash em Configurações → API Telegram.")
        return int(api_id), api_hash

    # ── Bot (publicação + painel) ────────────────────────────────────────────

    async def _start_bot(self):
        token = (db.get_config("bot_token") or "").strip()
        if not token:
            return None
        api_id, api_hash = self.get_creds()
        if self.bot:
            await self.bot.disconnect()
            self.bot = None

        # Sessão salva como "<bot_id>|<session>": evita re-login a cada start e troca de bot com sessão errada
        bot_id = token.split(":")[0]
        salva = db.get_config("bot_session") or ""
        sessao = salva.partition("|")[2] if salva.startswith(bot_id + "|") else ""

        bot = TelegramClient(StringSession(sessao), api_id, api_hash)
        await bot.start(bot_token=token)
        db.set_config("bot_session", f"{bot_id}|{bot.session.save()}")

        import admin_panel
        admin_panel.registrar(bot, self)
        self.bot = bot
        return (await bot.get_me()).username

    def iniciar_bot(self, callback=None):
        def _done(fut):
            try:
                res, err = fut.result(), None
            except Exception as e:
                res, err = None, str(e)
            if err:
                print(f"[Bot] Falha ao iniciar: {err}")
            elif res:
                print(f"[Bot] @{res} online.")
            if callback:
                callback(res, err)

        self._run(self._start_bot()).add_done_callback(_done)

    def via_bot(self) -> bool:
        return self.bot is not None and db.get_config("publicar_via_bot", "1") == "1"

    async def enviar(self, conta_id, destino, texto, file=None, botao_url=None, html=False):
        """Publica no destino: pelo bot quando ativo (API oficial, sem risco de ban da conta), senão pela conta."""
        if self.via_bot():
            client = self.bot
            buttons = [Button.url("🛒 Ver oferta", botao_url)] if botao_url else None
        else:
            client = self.clients.get(conta_id)
            if not client:
                raise RuntimeError("Conta remetente offline e bot não configurado.")
            buttons = None  # contas de usuário não enviam botões
        entity = await self.resolve_entity(client, destino)
        return await client.send_message(entity, texto, file=file, buttons=buttons,
                                         parse_mode="html" if html else ())

    async def _midia_para_envio(self, msg):
        """Mídia da origem pronta para reenvio. O bot não enxerga arquivos da conta: baixa em memória."""
        if not msg.media or isinstance(msg.media, MessageMediaWebPage):
            return None  # prévia de link é gerada de novo pelo próprio Telegram
        if not self.via_bot():
            return msg.media
        buf = io.BytesIO()
        await msg.download_media(file=buf)
        buf.name = "arquivo" + (msg.file.ext or "")
        buf.seek(0)
        return buf

    # ── Conexão de conta ─────────────────────────────────────────────────────

    async def _connect(self, conta_id: int, api_id: int, api_hash: str, session: str, phone: str):
        s = StringSession(session) if session else StringSession()
        client = TelegramClient(s, api_id, api_hash)
        await client.connect()

        if not await client.is_user_authorized():
            await client.send_code_request(phone)
            self._pending[conta_id] = (client, phone)
            return "needs_code"

        self.clients[conta_id] = client
        db.atualizar_conta(conta_id, client.session.save(), "conectada")
        self.restaurar_repasses_conta(conta_id)
        return "connected"

    async def _sign_in(self, conta_id: int, code: str, password: str = None):
        entry = self._pending.pop(conta_id, None)
        if not entry:
            raise RuntimeError("Sessão expirada. Tente conectar novamente.")
        client, phone = entry
        try:
            await client.sign_in(phone, code)
        except Exception as e:
            msg = str(e).lower()
            if "2fa" in msg or "password" in msg or "two" in msg:
                if not password:
                    self._pending[conta_id] = (client, phone)
                    raise RuntimeError("Conta com 2FA. Informe a senha.")
                await client.sign_in(password=password)
            else:
                raise

        self.clients[conta_id] = client
        session = client.session.save()
        db.atualizar_conta(conta_id, session, "conectada")
        self.restaurar_repasses_conta(conta_id)
        return session

    async def _disconnect(self, conta_id: int):
        client = self.clients.pop(conta_id, None)
        if client:
            await client.disconnect()
        db.atualizar_conta(conta_id, None, "desconectada")

    async def _get_groups(self, conta_id: int):
        client = self.clients.get(conta_id)
        if not client:
            return []
        dialogs = await client.get_dialogs()
        return [
            {"id": str(d.entity.id), "nome": d.name}
            for d in dialogs
            if d.is_group or d.is_channel
        ]

    async def _get_all_dialogs(self, conta_id: int):
        client = self.clients.get(conta_id)
        if not client:
            return []
        dialogs = await client.get_dialogs()
        res = []
        for d in dialogs:
            ident = str(d.entity.id)
            if d.is_channel:
                ident = f"-100{d.entity.id}"
            elif d.is_group:
                ident = f"-{d.entity.id}"
            
            tipo = "DM"
            if d.is_channel:
                tipo = "Canal"
            elif d.is_group:
                tipo = "Grupo"
                
            name = d.name or "Sem Nome"
            res.append({"id": ident, "nome": f"{tipo} | {name}"})
        return res

    async def resolve_entity(self, client: TelegramClient, identifier):
        """
        Resolve uma entidade (usuário, grupo, canal ou número de telefone) de forma robusta.
        Tenta buscar no cache do cliente, tenta formatar como telefone e, se necessário,
        importa como contato temporário para garantir a resolução.
        """
        from telethon.tl.functions.contacts import ImportContactsRequest
        from telethon.tl.types import InputPhoneContact

        ident_str = str(identifier).strip()
        
        # 1. Verificar se parece um número de telefone (com ou sem +)
        is_phone = False
        phone_number = ident_str
        if ident_str.startswith("+"):
            is_phone = True
        elif ident_str.isdigit() and len(ident_str) >= 10:
            is_phone = True
            phone_number = "+" + ident_str

        if is_phone:
            # Tenta obter a entidade com o número do telefone diretamente
            try:
                return await client.get_entity(phone_number)
            except Exception:
                # Se falhar, tenta importar como contato temporário para resolver
                try:
                    contact = InputPhoneContact(client_id=0, phone=phone_number, first_name=phone_number, last_name="")
                    result = await client(ImportContactsRequest([contact]))
                    if result and result.users:
                        return result.users[0]
                except Exception:
                    pass

        # 2. Tentar converter para int (IDs de chats/canais/usuários)
        if ident_str.isdigit() or (ident_str.startswith("-") and ident_str[1:].isdigit()):
            try:
                val = int(ident_str)
                # Tenta obter a entidade com o ID direto
                try:
                    return await client.get_entity(val)
                except Exception:
                    # ID salvo sem prefixo: tenta canal/supergrupo (-100…) e grupo básico (-…).
                    # O bot depende disso: ele não tem lista de diálogos para resolver pelo nome.
                    if val > 0:
                        for marcado in (int(f"-100{val}"), -val):
                            try:
                                return await client.get_entity(marcado)
                            except Exception:
                                pass
            except ValueError:
                pass

        # 3. Caso padrão (ex: usernames com @, links de convite ou fallback final)
        try:
            return await client.get_entity(identifier)
        except Exception:
            pass

        # 4. Busca por correspondência exata do nome do grupo/canal nos diálogos
        try:
            dialogs = await client.get_dialogs()
            for d in dialogs:
                if d.name == ident_str:
                    return d.entity
        except Exception:
            pass

        # Fallback final se nada der certo: retorna o próprio identificador original
        return identifier

    # ── Forwarding ───────────────────────────────────────────────────────────

    async def _start_repasse(self, repasse_id: int):
        r = db.get_repasse(repasse_id)
        if not r:
            return

        client = self.clients.get(r["conta_id"])
        if not client:
            return

        # Evitar duplicados
        await self._stop_repasse(repasse_id, r["conta_id"])

        filtros = json.loads(r["filtros"] or "{}")
        subs = json.loads(r["substituicoes"] or "[]")
        destinos = db.listar_destinos(repasse_id)

        async def _handler(event):
            # Verificar se repasse ainda está ativo
            current = db.get_repasse(repasse_id)
            if not current or not current["ativo"]:
                return

            # Radar de preços: registra o preço de toda oferta da origem, mesmo que não seja repassada
            try:
                import radar
                await radar.capturar(event.message, event.message.text or "", current["origem_nome"] or "")
            except Exception as e:
                print(f"[Radar] Falha ao registrar preço: {e}")

            # Pausa global (painel do bot)
            if db.get_config("pausado", "0") == "1":
                return

            # Limite diário (só conta mensagens efetivamente enviadas, ver final do handler)
            limite = current["limite_diario"]
            today = datetime.now().strftime("%Y-%m-%d")
            cnt = self._daily_count.get(repasse_id, {"date": "", "count": 0})
            if cnt["date"] != today:
                cnt = {"date": today, "count": 0}
                self._daily_count[repasse_id] = cnt
            if limite > 0 and cnt["count"] >= limite:
                return

            # Horário (aceita janela que cruza a meia-noite, ex.: 22:00–06:00)
            h_ini = current["horario_inicio"] or "00:00"
            h_fim = current["horario_fim"] or "00:00"
            if h_ini != "00:00" or h_fim != "00:00":
                now_t = datetime.now().strftime("%H:%M")
                dentro = h_ini <= now_t <= h_fim if h_ini <= h_fim else (now_t >= h_ini or now_t <= h_fim)
                if not dentro:
                    return

            text = event.message.text or ""

            # Filtro bloqueio de termos
            termos_bloquear = current["termos_bloquear"] or ""
            if termos_bloquear:
                for t in termos_bloquear.split(","):
                    if t.strip() and t.strip().lower() in text.lower():
                        return

            # Filtro permissão de termos
            termos_permitir = current["termos_permitir"] or ""
            if termos_permitir:
                allowed = False
                for t in termos_permitir.split(","):
                    if t.strip() and t.strip().lower() in text.lower():
                        allowed = True
                        break
                if not allowed:
                    return

            # Filtros de mídia
            msg = event.message
            if filtros.get("links") and re.search(r"https?://\S+", text):
                return
            if filtros.get("imagens") and msg.photo:
                return
            if filtros.get("videos") and msg.video:
                return
            if filtros.get("audios") and (msg.audio or msg.voice):
                return

            # Ofertas: exige link de loja e/ou ignora produto já publicado nas últimas 24h
            chaves = set()
            if filtros.get("somente_ofertas") or filtros.get("sem_repetidas"):
                import dedup
                chaves = await dedup.chaves_do_texto(text)
                if filtros.get("somente_ofertas") and not chaves:
                    return
                if filtros.get("sem_repetidas") and chaves and chaves <= db.ofertas_recentes(chaves):
                    db.adicionar_historico(repasse_id, "-", "Ignorada", "Produto já publicado nas últimas 24h")
                    return

            # Substituições manuais
            for sub in subs:
                busca = sub.get("busca", "")
                replace = sub.get("substituir", "")
                if busca:
                    text = text.replace(busca, replace)

            # Substituição inteligente de afiliados
            if filtros.get("substituir_afiliados"):
                try:
                    from affiliate_helper import process_text_urls
                    text = await process_text_urls(text)
                except Exception as aff_err:
                    db.adicionar_historico(repasse_id, "-", "Erro Afiliados", str(aff_err))

            # Delay
            delay = current["delay"] or 1
            if delay > 0:
                await asyncio.sleep(delay)

            # Enviar para destinos (bot se ativo, senão a própria conta)
            enviado = False
            for dest in destinos:
                try:
                    media = await self._midia_para_envio(event.message)
                    await self.enviar(r["conta_id"], dest["grupo_id"], text, file=media)
                    db.incrementar_repasse(repasse_id)
                    db.adicionar_historico(repasse_id, dest["grupo_nome"], "Sucesso")
                    enviado = True
                except Exception as exc:
                    db.adicionar_historico(repasse_id, dest["grupo_nome"], "Falha", str(exc))
            if enviado:
                cnt["count"] += 1
                if chaves:
                    db.marcar_ofertas(chaves)

        # Registrar handler no source
        try:
            source_entity = await self.resolve_entity(client, r["origem_id"])
            client.add_event_handler(_handler, events.NewMessage(chats=source_entity))
            self._handlers[repasse_id] = _handler
        except Exception as e:
            db.adicionar_historico(repasse_id, "-", "Falha ao iniciar", str(e))

    async def _stop_repasse(self, repasse_id: int, conta_id: int):
        handler = self._handlers.pop(repasse_id, None)
        if handler:
            client = self.clients.get(conta_id)
            if client:
                client.remove_event_handler(handler)

    # ── API Pública (thread-safe) ─────────────────────────────────────────────

    def conectar_conta(self, conta_id: int, phone: str, callback):
        try:
            api_id, api_hash = self.get_creds()
        except ValueError as e:
            callback(None, str(e))
            return

        contas = {c["id"]: c for c in db.listar_contas()}
        session = contas.get(conta_id, {}).get("session")

        def _done(fut):
            try:
                callback(fut.result(), None)
            except Exception as e:
                callback(None, str(e))

        self._run(self._connect(conta_id, api_id, api_hash, session, phone)).add_done_callback(_done)

    def confirmar_codigo(self, conta_id: int, code: str, callback, password: str = None):
        def _done(fut):
            try:
                callback(fut.result(), None)
            except Exception as e:
                callback(None, str(e))

        self._run(self._sign_in(conta_id, code, password)).add_done_callback(_done)

    def desconectar_conta(self, conta_id: int, callback=None):
        def _done(fut):
            if callback:
                try:
                    callback(None)
                except Exception:
                    pass

        self._run(self._disconnect(conta_id)).add_done_callback(_done)

    def get_groups(self, conta_id: int, callback):
        def _done(fut):
            try:
                callback(fut.result(), None)
            except Exception as e:
                callback([], str(e))

        self._run(self._get_groups(conta_id)).add_done_callback(_done)

    def get_all_dialogs(self, conta_id: int, callback):
        def _done(fut):
            try:
                callback(fut.result(), None)
            except Exception as e:
                callback([], str(e))

        self._run(self._get_all_dialogs(conta_id)).add_done_callback(_done)

    def iniciar_repasse(self, repasse_id: int):
        self._run(self._start_repasse(repasse_id))

    def parar_repasse(self, repasse_id: int, conta_id: int):
        self._run(self._stop_repasse(repasse_id, conta_id))

    def restaurar_repasses_ativos(self):
        """Chamado no startup para reativar repasses que estavam ativos."""
        for r in db.listar_repasses():
            if r["ativo"] and r["conta_id"] in self.clients:
                self.iniciar_repasse(r["id"])

    def restaurar_repasses_conta(self, conta_id: int):
        """Reativa repasses ativos vinculados a uma conta específica."""
        for r in db.listar_repasses():
            if r["ativo"] and r["conta_id"] == conta_id:
                try:
                    loop = asyncio.get_running_loop()
                    if loop == self.loop:
                        loop.create_task(self._start_repasse(r["id"]))
                        continue
                except RuntimeError:
                    pass
                self.iniciar_repasse(r["id"])


# Singleton global
telegram_manager = TelegramManager()
