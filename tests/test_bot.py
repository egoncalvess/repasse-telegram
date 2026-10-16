"""
Bot como centro da operação, sem Telegram: o bot lê as origens onde é admin e publica tudo; com bot
configurado a conta nunca envia; comandos /buscar e a fila de aprovação do piloto.
"""
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import admin_panel  # noqa: E402
import autonomia  # noqa: E402
import database as db  # noqa: E402
import fontes  # noqa: E402
import oferta  # noqa: E402
import radar  # noqa: E402
from fontes.base import Fonte, ProdutoEncontrado  # noqa: E402
from telegram_manager import TelegramManager  # noqa: E402

ADMIN = 4242


class Msg:
    def __init__(self, text="", media=None, photo=None, chat_id=-1001):
        self.text, self.media, self.photo, self.chat_id = text, media, photo, chat_id
        self.grouped_id = None
        self.video = self.audio = self.voice = None
        self.file = SimpleNamespace(ext=".jpg")
        self.downloads = 0

    async def get_chat(self):
        return SimpleNamespace(title="Origem")

    async def download_media(self, file):
        self.downloads += 1
        file.write(b"foto")


class Cliente:
    """Client Telethon falso (conta ou bot)."""

    def __init__(self, admin_de=(), eh_bot=False):
        self.handlers, self.enviados, self.admin_de, self.eh_bot = [], [], set(admin_de), eh_bot
        self.callbacks = []

    def add_event_handler(self, fn, ev):
        self.handlers.append((fn, ev))

    def remove_event_handler(self, fn):
        self.handlers = [(f, e) for f, e in self.handlers if f is not fn]

    def on(self, ev):  # usado pelo admin_panel.registrar
        def deco(fn):
            self.callbacks.append((fn, ev))
            return fn
        return deco

    async def get_entity(self, ident):
        return SimpleNamespace(id=ident)

    async def get_permissions(self, ent, quem):
        return SimpleNamespace(is_admin=ent.id in self.admin_de)

    async def get_me(self):
        return SimpleNamespace(username="bot", bot_chat_history=False)

    async def send_message(self, entity, texto, file=None, buttons=None, parse_mode=()):
        self.enviados.append((getattr(entity, "id", entity), texto, file, buttons))

    def handler(self, nome, chats=None):
        for fn, ev in self.handlers:
            if fn.__name__ == nome and (chats is None or [c.id for c in ev.chats] == chats):
                return fn
        raise LookupError(nome)


@pytest.fixture(autouse=True)
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "repasse.db")
    monkeypatch.setattr(radar, "PASTA_IMAGENS", tmp_path / "imagens")
    db.init_db()
    db.set_config("bot_admin_id", str(ADMIN))


def criar_repasse(origens=("-1001",), **campos):
    conta = db.adicionar_conta("+5571999999999", "teste")
    dados = {"descricao": "teste", "conta_id": conta, "origem_id": origens[0], "origem_nome": "Origem",
             "filtros": "{}", "substituicoes": "[]", "delay": 0, "limite_diario": 0, "horario_inicio": "00:00",
             "horario_fim": "00:00", "termos_bloquear": "", "termos_permitir": ""} | campos
    rid = db.adicionar_repasse(dados)
    db.set_origens(rid, [{"origem_id": o, "origem_nome": f"Origem {o}"} for o in origens])
    db.set_destinos(rid, [{"grupo_id": "-2002", "grupo_nome": "Destino"}])
    return conta, rid


def evento(msg):
    return SimpleNamespace(message=msg)


# ── Repasse lido pelo bot ─────────────────────────────────────────────────────

def test_origem_onde_o_bot_e_admin_funciona_so_com_o_bot():
    async def cenario():
        _, rid = criar_repasse()
        tm = TelegramManager()
        tm.bot = Cliente(admin_de={-1001}, eh_bot=True)       # nenhuma conta conectada
        await tm._start_repasse(rid)
        msg = Msg("oferta", media="foto", photo=True)
        await tm.bot.handler("_nova_mensagem")(evento(msg))
        return tm, rid, msg

    tm, rid, msg = asyncio.run(cenario())
    assert tm.leitura[(rid, "-1001")] == "bot"
    [(destino, texto, arquivo, _)] = tm.bot.enviados
    assert destino == -2002 and texto == "oferta"
    assert arquivo == "foto" and msg.downloads == 0           # mesma mídia, sem baixar


def test_filtros_do_repasse_valem_igual_para_o_bot():
    async def cenario():
        _, rid = criar_repasse(termos_bloquear="sorteio")
        tm = TelegramManager()
        tm.bot = Cliente(admin_de={-1001}, eh_bot=True)
        await tm._start_repasse(rid)
        nova = tm.bot.handler("_nova_mensagem")
        await nova(evento(Msg("Grande SORTEIO hoje")))
        await nova(evento(Msg("Fone por R$ 49")))
        return [t for _, t, _, _ in tm.bot.enviados]

    assert asyncio.run(cenario()) == ["Fone por R$ 49"]


def test_origem_sem_bot_fica_com_a_conta_que_so_le_e_o_bot_envia():
    async def cenario():
        conta_id, rid = criar_repasse(origens=("-1001", "-1009"))
        tm = TelegramManager()
        conta = Cliente()
        tm.clients[conta_id] = conta
        tm.bot = Cliente(admin_de={-1001}, eh_bot=True)
        await tm._start_repasse(rid)
        msg = Msg("oferta da conta", media="foto", photo=True, chat_id=-1009)
        await conta.handler("_nova_mensagem", chats=[-1009])(evento(msg))
        return tm, rid, conta, msg

    tm, rid, conta, msg = asyncio.run(cenario())
    assert tm.leitura[(rid, "-1001")] == "bot" and tm.leitura[(rid, "-1009")] == "conta"
    assert [ev.chats[0].id for _, ev in tm.bot.handlers] == [-1001, -1001]
    assert [ev.chats[0].id for _, ev in conta.handlers] == [-1009, -1009]
    assert conta.enviados == []
    [(_, texto, arquivo, _)] = tm.bot.enviados
    assert texto == "oferta da conta" and arquivo.getvalue() == b"foto" and msg.downloads == 1


def test_bot_configurado_e_offline_nao_envia_pela_conta():
    async def cenario():
        conta_id, rid = criar_repasse()
        db.set_config("bot_token", "123:ABC")
        tm = TelegramManager()
        conta = Cliente()
        tm.clients[conta_id] = conta
        await tm._start_repasse(rid)
        await conta.handler("_nova_mensagem")(evento(Msg("oferta")))
        return conta, rid

    conta, rid = asyncio.run(cenario())
    assert conta.enviados == []
    [h] = db.listar_historico(rid)
    assert h["status"] == "Falha" and "offline" in h["detalhes"]


def test_parar_remove_os_ouvintes_do_bot_e_da_conta():
    async def cenario():
        conta_id, rid = criar_repasse(origens=("-1001", "-1009"))
        tm = TelegramManager()
        conta = Cliente()
        tm.clients[conta_id] = conta
        tm.bot = Cliente(admin_de={-1001}, eh_bot=True)
        await tm._start_repasse(rid)
        await tm._stop_repasse(rid, conta_id)
        return conta, tm.bot

    conta, bot = asyncio.run(cenario())
    assert conta.handlers == [] and bot.handlers == []


# ── /buscar e Monitorar ───────────────────────────────────────────────────────

class FonteFalsa(Fonte):
    id, nome, loja = "ml", "Mercado Livre", "mercadolivre"

    def __init__(self, produtos):
        super().__init__()
        self.produtos = produtos
        self.http.baixar = lambda *a, **k: None

    def buscar(self, busca):
        return self.produtos

    def testar(self):
        return {}


def prod(n, preco, original=None):
    url = f"https://www.mercadolivre.com.br/p/MLB{n:08d}"
    return ProdutoEncontrado(chave=f"ml:{n:08d}", nome=f"Produto {n}", url=url, preco=preco,
                             preco_original=original, loja="Mercado Livre")


def test_buscar_mostra_top_5_com_publicar_e_monitorar(monkeypatch):
    produtos = [prod(1, 100), prod(2, 50, 100), prod(3, 80, 100), prod(4, 30), prod(5, 40), prod(6, 90, 95)]
    monkeypatch.setattr(fontes, "_registro", {"ml": FonteFalsa(produtos)})
    fontes.definir_ativa("ml", True)
    texto, botoes = admin_panel._resultado_busca("fone")
    assert "6 encontrado(s), top 5" in texto
    ordem = [linha[0].data.decode() for linha in botoes]
    assert ordem == ["p:spub:ml:00000002", "p:spub:ml:00000003", "p:spub:ml:00000006",
                     "p:spub:ml:00000004", "p:spub:ml:00000005"]   # maior desconto da loja, depois menor preço
    assert botoes[0][1].data == b"p:mon:ml:00000002"
    assert "de <s>R$ 100,00</s> por <b>R$ 50,00</b> (-50%)" in texto
    assert len(db.menores_precos_do_dia()) == 6                     # tudo foi para o radar


def test_buscar_sem_fonte_ativa_explica_como_ligar():
    texto, botoes = admin_panel._resultado_busca("fone")
    assert "Nenhuma fonte de busca ativa" in texto and botoes is None


def test_monitorar_cria_busca_de_produto_uma_vez(monkeypatch):
    import buscador
    monkeypatch.setattr(fontes, "_registro", {"ml": FonteFalsa([])})
    db.registrar_preco("ml:00000002", "Produto 2", "Mercado Livre", "https://www.mercadolivre.com.br/p/MLB00000002", 50)
    bid, msg = buscador.monitorar("ml:00000002")
    assert msg.startswith("Monitorando")
    b = db.get_busca(bid)
    assert (b["tipo"], b["valor"], b["fonte_id"]) == ("produto", "https://www.mercadolivre.com.br/p/MLB00000002", "ml")
    assert buscador.monitorar("ml:00000002")[1].startswith("Já monitorado") and len(db.listar_buscas()) == 1


# ── Piloto em modo aprovação ──────────────────────────────────────────────────

def preparar_piloto(modo):
    for chave, valor in {"piloto_ativo": "1", "piloto_inicio": "00:00", "piloto_fim": "00:00",
                         "radar_destino": "-2002", "piloto_modo": modo}.items():
        db.set_config(chave, valor)
    url = "https://www.mercadolivre.com.br/p/MLB00000007"
    for dias in range(1, 9):  # 8 dias a R$ 100 e hoje R$ 80: "Menor preço em 8 dias"
        db.registrar_preco("ml:00000007", "Air fryer", "Mercado Livre", url, 100,
                           visto_em=datetime.now() - timedelta(days=dias))
    db.registrar_preco("ml:00000007", "Air fryer", "Mercado Livre", url, 80)


def test_modo_aprovacao_enfileira_avisa_o_admin_e_nao_publica(monkeypatch):
    preparar_piloto("aprovacao")
    monkeypatch.setattr(oferta, "publicar_oferta", lambda *a, **k: pytest.fail("não deveria publicar"))
    tm = TelegramManager()
    tm.bot = Cliente(eh_bot=True)
    primeiro = asyncio.run(autonomia.ciclo_piloto(tm))
    segundo = asyncio.run(autonomia.ciclo_piloto(tm))
    assert primeiro.startswith("aguardando aprovação: Air fryer")
    assert segundo == "nenhuma oferta nova para aprovar"
    [item] = db.listar_fila()
    assert item["chave"] == "ml:00000007" and item["status"] == "pendente"
    [(destino, texto, _, botoes)] = tm.bot.enviados
    assert destino == ADMIN and "Publicar esta oferta?" in texto
    assert [b.data for b in botoes[0]] == [f"p:fpub:{item['id']}".encode(), f"p:fdes:{item['id']}".encode()]


def test_pendentes_contam_no_limite_diario():
    preparar_piloto("aprovacao")
    db.set_config("piloto_max_dia", "1")
    db.adicionar_fila("ml:outro")
    tm = TelegramManager()
    assert asyncio.run(autonomia.ciclo_piloto(tm)) == "limite diário atingido (1)"


def acionar(tm, dado: bytes):
    """Simula o toque num botão inline do painel (só o admin)."""
    bot = Cliente(eh_bot=True)
    admin_panel.registrar(bot, tm)
    acao = next(fn for fn, _ in bot.callbacks if fn.__name__ == "_acao")
    respostas = []

    async def edit(texto, **k):
        respostas.append(("edit", texto))

    async def answer(texto="", **k):
        respostas.append(("answer", texto))
    asyncio.run(acao(SimpleNamespace(sender_id=ADMIN, data=dado, edit=edit, answer=answer)))
    return respostas


def test_aprovar_publica_por_publicar_oferta_e_descartar_nao(monkeypatch):
    preparar_piloto("aprovacao")
    publicados = []
    monkeypatch.setattr(oferta, "publicar_oferta", lambda chave, conta, destino, origem="manual", **k:
                        publicados.append((chave, destino, origem)))
    a, b = db.adicionar_fila("ml:00000007"), db.adicionar_fila("ml:00000008")
    tm = TelegramManager()
    assert ("answer", "✅ Publicado") in acionar(tm, f"p:fpub:{a}".encode())
    assert ("answer", "Descartado") in acionar(tm, f"p:fdes:{b}".encode())
    assert publicados == [("ml:00000007", "-2002", "piloto")]
    assert db.get_fila(a)["status"] == "aprovada" and db.get_fila(b)["status"] == "descartada"
    assert ("answer", "Já decidido.") in acionar(tm, f"p:fpub:{a}".encode())
    assert len(publicados) == 1
