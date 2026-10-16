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

from telethon import TelegramClient, events, Button
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaWebPage

import database as db

MAX_FLOOD_WAIT_S = 600   # espera pedida pelo Telegram acima disso vira falha (não segura a fila por horas)
TENTATIVAS_ENVIO = 3


class TelegramManager:
    def __init__(self):
        self._tasks: set[asyncio.Task] = set()              # refs fortes: asyncio só guarda refs fracas
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        self.bot: TelegramClient | None = None              # bot oficial: publica e serve o painel
        self.clients: dict[int, TelegramClient] = {}       # conta_id -> client
        self._pending: dict[int, TelegramClient] = {}      # aguardando código
        self._handlers: dict[int, list] = {}               # repasse_id -> [(client que lê, handler)]
        self.leitura: dict[tuple, str] = {}                # (repasse_id, origem_id) -> "bot" | "conta" | "sem acesso"
        self._radar_handlers: dict[int, callable] = {}     # conta_id -> handler do radar
        self._ritmo: dict[int, dict] = {}                  # repasse_id -> {lock, ultimo envio (monotonic)}
        self._ofertas_em_envio: set[str] = set()           # chaves de produto reservadas por envios em curso

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
        self.restaurar_repasses_ativos()  # o bot assume a leitura das origens onde é administrador
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
        return self.bot is not None

    async def enviar(self, conta_id, destino, texto, file=None, botao_url=None, html=False):
        """Publica no destino. Com bot configurado, SEMPRE pelo bot (a conta só lê); sem bot, pela conta."""
        if self.bot is not None:
            client = self.bot
            buttons = [Button.url("🛒 Ver oferta", botao_url)] if botao_url else None
        elif (db.get_config("bot_token") or "").strip():
            raise RuntimeError("Bot configurado, mas offline: nada é enviado pela conta. "
                               "Verifique o bot em Configurações → Bot.")
        else:
            client = self.clients.get(conta_id)
            if not client:
                raise RuntimeError("Conta remetente offline e bot não configurado.")
            buttons = None  # contas de usuário não enviam botões
        entity = await self.resolve_entity(client, destino)
        if isinstance(entity, (str, int)):  # resolve_entity devolve o próprio identificador quando falha
            quem = f"@{(await client.get_me()).username}" if client is self.bot else "a conta"
            raise RuntimeError(f"{quem} não tem acesso ao destino {destino}: adicione como administrador do grupo/canal.")
        for tentativa in range(1, TENTATIVAS_ENVIO + 1):
            try:
                return await client.send_message(entity, texto, file=file, buttons=buttons,
                                                 parse_mode="html" if html else ())
            except FloodWaitError as e:
                if tentativa == TENTATIVAS_ENVIO or e.seconds > MAX_FLOOD_WAIT_S:
                    raise
                print(f"[Envio] Telegram pediu {e.seconds}s de espera antes de publicar em {destino}; aguardando.")
                await asyncio.sleep(e.seconds + 1)
                for f in (file if isinstance(file, list) else [file]):
                    if isinstance(f, io.BytesIO):
                        f.seek(0)  # o upload da tentativa anterior consumiu o arquivo

    async def _midia_para_envio(self, msg, leitor=None):
        """Mídia da origem pronta para reenvio. Quem lê e quem envia são o mesmo client: reaproveita a mídia;
        senão (conta lê, bot envia) baixa os bytes uma vez. leitor=None é a conta."""
        if not msg.media or isinstance(msg.media, MessageMediaWebPage):
            return None  # prévia de link é gerada de novo pelo próprio Telegram
        if (leitor is not None and leitor is self.bot) == self.via_bot():
            return msg.media
        buf = io.BytesIO()
        await msg.download_media(file=buf)
        return "arquivo" + (msg.file.ext or ""), buf.getvalue()

    @staticmethod
    def _arquivo(midia):
        """Arquivo para um envio: bytes baixados viram um BytesIO novo por destino (o upload consome o stream)."""
        if isinstance(midia, tuple):
            buf = io.BytesIO(midia[1])
            buf.name = midia[0]
            return buf
        return midia

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
        elif ident_str.isdigit() and len(ident_str) >= 12:  # IDs de grupo/canal têm até ~11 dígitos; telefone c/ DDI 12+
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

        conta = self.clients.get(r["conta_id"])
        if not conta and not self.bot:
            return

        # Evitar duplicados
        await self._stop_repasse(repasse_id, r["conta_id"])

        ctx = {"filtros": json.loads(r["filtros"] or "{}"), "subs": json.loads(r["substituicoes"] or "[]"),
               "destinos": db.listar_destinos(repasse_id), "conta_id": r["conta_id"]}

        # Cada origem é lida pelo bot quando ele consegue (admin); senão pela conta, só leitura
        origens = db.listar_origens(repasse_id) or ([{"origem_id": r["origem_id"], "origem_nome": r["origem_nome"]}]
                                                     if r["origem_id"] else [])
        por_leitor: dict = {}
        for o in origens:
            try:
                leitor, ent, motivo = await self._leitor_da_origem(o["origem_id"], conta)
                if leitor is None:
                    raise ValueError(motivo)
                por_leitor.setdefault(leitor, []).append(ent)
                self.leitura[(repasse_id, str(o["origem_id"]))] = "bot" if leitor is self.bot else "conta"
            except Exception as e:
                self.leitura[(repasse_id, str(o["origem_id"]))] = "sem acesso"
                db.adicionar_historico(repasse_id, o["origem_nome"] or o["origem_id"], "Falha ao iniciar", str(e))

        registrados = []
        for leitor, entidades in por_leitor.items():
            def _handlers(leitor=leitor):
                async def _nova_mensagem(event):
                    if event.message.grouped_id:  # item de álbum: vai inteiro pelo handler de Album
                        return
                    await self._processar_postagem(repasse_id, ctx, [event.message], event.message.text or "", leitor)

                async def _novo_album(event):
                    await self._processar_postagem(repasse_id, ctx, list(event.messages),
                                                   next((m.text for m in event.messages if m.text), ""), leitor)
                return _nova_mensagem, _novo_album

            nova, album = _handlers()
            leitor.add_event_handler(nova, events.NewMessage(chats=entidades))
            leitor.add_event_handler(album, events.Album(chats=entidades))
            registrados += [(leitor, nova), (leitor, album)]
        if registrados:
            self._handlers[repasse_id] = registrados

    async def _processar_postagem(self, repasse_id: int, ctx: dict, msgs: list, text: str, leitor=None):
        """Pipeline único do repasse: uma postagem da origem (mensagem única ou álbum), lida pela conta ou
        pelo bot (leitor), passa pelos filtros e vai para os destinos."""
        filtros = ctx["filtros"]
        # Verificar se repasse ainda está ativo
        current = db.get_repasse(repasse_id)
        if not current or not current["ativo"]:
            return
        chat = await msgs[0].get_chat()
        print(f"[Repasse {current['descricao']}] nova mensagem de {getattr(chat, 'title', msgs[0].chat_id)}")

        # Pausa global (painel do bot)
        if db.get_config("pausado", "0") == "1":
            return

        # Limite diário (contado no banco: sobrevive a reinícios; conferido de novo antes de enviar)
        limite = current["limite_diario"] or 0
        if limite > 0 and db.enviadas_hoje(repasse_id) >= limite:
            return

        # Horário (aceita janela que cruza a meia-noite, ex.: 22:00–06:00)
        h_ini = current["horario_inicio"] or "00:00"
        h_fim = current["horario_fim"] or "00:00"
        import autonomia
        if not autonomia.dentro_do_horario(h_ini, h_fim):
            return

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

        # Filtros de mídia (num álbum, basta um item do tipo bloqueado)
        if filtros.get("links") and re.search(r"https?://\S+", text):
            return
        if filtros.get("imagens") and any(m.photo for m in msgs):
            return
        if filtros.get("videos") and any(m.video for m in msgs):
            return
        if filtros.get("audios") and any(m.audio or m.voice for m in msgs):
            return

        # Ofertas: exige link de loja e/ou ignora produto já publicado nas últimas 24h
        chaves = set()
        if filtros.get("somente_ofertas") or filtros.get("sem_repetidas"):
            import dedup
            chaves = await dedup.chaves_do_texto(text)
            if filtros.get("somente_ofertas") and not chaves:
                return
            # Produto em envio agora (outro canal postou a mesma oferta segundos antes) também conta como repetido
            if filtros.get("sem_repetidas") and chaves and chaves <= (db.ofertas_recentes(chaves)
                                                                      | self._ofertas_em_envio):
                db.adicionar_historico(repasse_id, "-", "Ignorada", "Produto já publicado nas últimas 24h")
                return

        # Reserva os produtos até o fim do envio (checagem e reserva sem await entre elas)
        reservadas = (chaves - self._ofertas_em_envio) if filtros.get("sem_repetidas") else set()
        self._ofertas_em_envio |= reservadas
        try:
            # Substituições manuais
            for sub in ctx["subs"]:
                busca = sub.get("busca", "")
                replace = sub.get("substituir", "")
                if busca:
                    text = text.replace(busca, replace)

            # Substituição inteligente de afiliados
            if filtros.get("substituir_afiliados"):
                try:
                    from affiliate_helper import converter_links
                    text, nao_convertidos = await converter_links(text)
                except Exception as aff_err:
                    db.adicionar_historico(repasse_id, "-", "Erro Afiliados", str(aff_err))
                    nao_convertidos = ["(erro na conversão)"]
                # Não divulga link que renderia comissão para outra pessoa
                if nao_convertidos and filtros.get("exigir_afiliado"):
                    db.adicionar_historico(repasse_id, "-", "Ignorada",
                                           "Link sem conversão p/ afiliado: " + ", ".join(nao_convertidos)[:300])
                    return

            # Ritmo: um envio por vez por repasse, com pelo menos `delay` segundos entre eles
            ritmo = self._ritmo.setdefault(repasse_id, {"lock": asyncio.Lock(), "ultimo": 0.0})
            async with ritmo["lock"]:
                if limite > 0 and db.enviadas_hoje(repasse_id) >= limite:
                    return
                delay = current["delay"] if current["delay"] is not None else 1
                espera = ritmo["ultimo"] + delay - time.monotonic()
                if espera > 0:
                    await asyncio.sleep(espera)

                # Mídia baixada uma vez só, reaproveitada em todos os destinos
                midias = [m for m in [await self._midia_para_envio(msg, leitor) for msg in msgs] if m is not None]

                # Enviar para destinos (bot se ativo, senão a própria conta)
                enviado = False
                for dest in ctx["destinos"]:
                    try:
                        arquivos = [self._arquivo(m) for m in midias]
                        arquivo = arquivos if len(arquivos) > 1 else (arquivos[0] if arquivos else None)
                        await self.enviar(ctx["conta_id"], dest["grupo_id"], text, file=arquivo)
                        db.incrementar_repasse(repasse_id)
                        db.adicionar_historico(repasse_id, dest["grupo_nome"], "Sucesso")
                        enviado = True
                    except Exception as exc:
                        db.adicionar_historico(repasse_id, dest["grupo_nome"], "Falha", str(exc))
                        await autonomia.alertar(self, f"repasse{repasse_id}-{dest['grupo_id']}",
                                                f"Repasse '{current['descricao']}' falhou para {dest['grupo_nome']}: {exc}")
                ritmo["ultimo"] = time.monotonic()
                if enviado:
                    db.registrar_envio_dia(repasse_id)
                    if chaves:
                        db.marcar_ofertas(chaves)
        finally:
            self._ofertas_em_envio -= reservadas

    async def _stop_repasse(self, repasse_id: int, conta_id: int):
        for client, handler in self._handlers.pop(repasse_id, []):
            client.remove_event_handler(handler)

    async def _bot_le(self, origem_id):
        """Entidade da origem se o bot recebe as mensagens dela: admin, ou membro de grupo com a
        privacidade do bot desligada. Canal só entrega posts a bot administrador."""
        from telethon.tl.types import Chat, User
        try:
            ent = await self.resolve_entity(self.bot, origem_id)
            if isinstance(ent, (str, int, User)):
                return None
            if (await self.bot.get_permissions(ent, "me")).is_admin:
                return ent
            eh_grupo = isinstance(ent, Chat) or getattr(ent, "megagroup", False)
            if eh_grupo and getattr(await self.bot.get_me(), "bot_chat_history", False):
                return ent
        except Exception:
            pass
        return None

    async def _leitor_da_origem(self, origem_id, conta):
        """(client que lê, entidade, motivo se nenhum lê). O bot tem preferência; a conta só lê."""
        if self.bot:
            ent = await self._bot_le(origem_id)
            if ent is not None:
                return self.bot, ent, None
        if conta:
            ent = await self.resolve_entity(conta, origem_id)
            if not isinstance(ent, (str, int)):
                return conta, ent, None
            return None, None, "a conta não participa deste grupo/canal"
        return None, None, ("o bot não lê este chat (adicione-o como administrador) e a conta do repasse "
                            "não está conectada")

    async def _leitura_origens(self, conta_id, origem_ids) -> dict:
        conta = self.clients.get(conta_id)
        res = {}
        for oid in origem_ids:
            try:
                leitor, _, _ = await self._leitor_da_origem(oid, conta)
            except Exception:
                leitor = None
            res[str(oid)] = "sem acesso" if leitor is None else ("bot" if leitor is self.bot else "conta")
        return res

    def leitura_origens(self, conta_id, origem_ids, callback):
        """{origem_id: "bot" | "conta" | "sem acesso"} para a UI (callback fora do loop)."""
        def _done(fut):
            try:
                callback(fut.result(), None)
            except Exception as e:
                callback({}, str(e))
        self._run(self._leitura_origens(conta_id, list(origem_ids))).add_done_callback(_done)

    # ── Importação de histórico (Radar) ──────────────────────────────────────

    async def _importar_historico(self, dias: int, progresso=None):
        """Importa as postagens antigas de cada canal de origem (uma vez por canal), pela conta do repasse."""
        import radar
        origens = {}  # chat_id -> (conta_id, nome)
        for conta_id in self.clients:
            for chat_id, nome in db.chats_do_radar(conta_id).items():
                origens.setdefault(chat_id, (conta_id, nome))
        if not origens:
            raise RuntimeError("Nenhuma fonte do radar nem repasse ativo com conta conectada.")
        total_lidas = total_reg = 0
        for i, (origem_id, (conta_id, nome)) in enumerate(origens.items(), 1):
            nome = nome or origem_id
            client = self.clients[conta_id]
            entity = await self.resolve_entity(client, origem_id)
            if isinstance(entity, (str, int)):
                print(f"[Radar] Sem acesso a {nome}; pulando.")
                continue

            def _prog(lidas, reg, nome=nome, i=i):
                if progresso:
                    progresso(f"[{i}/{len(origens)}] {nome[:30]}: {lidas} msgs lidas, {reg} preços")

            lidas, reg = await radar.importar_historico(client, entity, nome, dias, _prog)
            print(f"[Radar] Histórico de {nome}: {lidas} mensagens lidas, {reg} preços registrados")
            total_lidas += lidas
            total_reg += reg
        return f"{len(origens)} canais · {total_lidas} mensagens lidas · {total_reg} preços registrados"

    def importar_historico(self, dias: int, callback, progresso=None):
        def _done(fut):
            try:
                callback(fut.result(), None)
            except Exception as e:
                callback(None, str(e))

        self._run(self._importar_historico(dias, progresso)).add_done_callback(_done)

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
            if r["ativo"] and (r["conta_id"] in self.clients or self.bot):
                self.iniciar_repasse(r["id"])

    def restaurar_repasses_conta(self, conta_id: int):
        """Reativa repasses ativos da conta e o ouvinte do radar.
        Sempre via _run (referência forte); create_task solto podia ser destruído pelo GC."""
        for r in db.listar_repasses():
            if r["ativo"] and r["conta_id"] == conta_id:
                self.iniciar_repasse(r["id"])
        self.atualizar_radar(conta_id)

    # ── Radar: ouvinte único por conta (fontes + origens dos repasses) ────────

    async def _start_radar(self, conta_id: int):
        client = self.clients.get(conta_id)
        antigo = self._radar_handlers.pop(conta_id, None)
        if client and antigo:
            client.remove_event_handler(antigo)
        if not client:
            return
        entidades = []
        for chat_id, nome in db.chats_do_radar(conta_id).items():
            try:
                ent = await self.resolve_entity(client, chat_id)
                if not isinstance(ent, (str, int)):
                    entidades.append(ent)
            except Exception as e:
                print(f"[Radar] Não foi possível ouvir {nome}: {e}")
        if not entidades:
            return

        async def _capturar(event):
            import radar
            try:
                chat = await event.get_chat()
                await radar.capturar(event.message, event.message.text or "", getattr(chat, "title", "") or "")
            except Exception as e:
                print(f"[Radar] Falha ao registrar preço: {e}")

        client.add_event_handler(_capturar, events.NewMessage(chats=entidades))
        self._radar_handlers[conta_id] = _capturar
        print(f"[Radar] Monitorando {len(entidades)} canais/grupos.")

    def atualizar_radar(self, conta_id: int = None):
        """(Re)registra o ouvinte do radar — chamar após mudar fontes ou repasses."""
        for cid in ([conta_id] if conta_id else list(self.clients)):
            self._run(self._start_radar(cid))

    async def _listar_chats(self, conta_id: int):
        """Canais e grupos da conta com ID marcado (-100… / -…), sem ambiguidade com usuários."""
        from telethon import utils
        client = self.clients.get(conta_id)
        if not client:
            raise RuntimeError("Conta não conectada.")
        chats = []
        async for d in client.iter_dialogs():
            if d.is_group or d.is_channel:
                tipo = "Canal" if d.is_channel and not d.is_group else "Grupo"
                chats.append({"id": str(utils.get_peer_id(d.entity)), "nome": d.name or "Sem nome", "tipo": tipo})
        return chats

    def listar_chats(self, conta_id: int, callback):
        def _done(fut):
            try:
                callback(fut.result(), None)
            except Exception as e:
                callback([], str(e))

        self._run(self._listar_chats(conta_id)).add_done_callback(_done)


# Singleton global
telegram_manager = TelegramManager()
