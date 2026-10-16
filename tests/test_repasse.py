"""
Motor de repasse com um client Telethon falso: ritmo de envio, ofertas repetidas, limite diário,
álbuns, FloodWait e mídia baixada uma vez. Roda sem Telegram e sem interface.
"""
import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from telethon.errors import FloodWaitError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database as db  # noqa: E402
from telegram_manager import TelegramManager  # noqa: E402

LINK = "https://www.amazon.com.br/dp/B0CHSHN67G"


class FakeMsg:
    def __init__(self, text="", media=None, grouped_id=None, photo=None):
        self.text = text
        self.media = media
        self.grouped_id = grouped_id
        self.photo = photo
        self.video = self.audio = self.voice = None
        self.chat_id = -1001
        self.file = SimpleNamespace(ext=".jpg")
        self.downloads = 0

    async def get_chat(self):
        return SimpleNamespace(title="Origem")

    async def download_media(self, file):
        self.downloads += 1
        file.write(b"foto")


class FakeClient:
    def __init__(self, flood_vezes=0):
        self.handlers = []
        self.enviados = []  # (instante, destino, texto, file)
        self.flood_vezes = flood_vezes

    def add_event_handler(self, fn, ev):
        self.handlers.append((fn, ev))

    def remove_event_handler(self, fn):
        self.handlers = [(f, e) for f, e in self.handlers if f is not fn]

    async def get_entity(self, ident):
        return SimpleNamespace(id=ident)

    async def get_me(self):
        return SimpleNamespace(username="bot")

    async def send_message(self, entity, texto, file=None, buttons=None, parse_mode=()):
        if self.flood_vezes:
            self.flood_vezes -= 1
            raise FloodWaitError(request=None, capture=0)
        self.enviados.append((time.monotonic(), entity.id, texto, file))

    def handler(self, nome):
        return next(f for f, _ in self.handlers if f.__name__ == nome)


@pytest.fixture(autouse=True)
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "repasse.db")
    db.init_db()


def criar_repasse(destinos=("-1002",), **campos):
    conta = db.adicionar_conta("+5571999999999", "teste")
    dados = {"descricao": "teste", "conta_id": conta, "origem_id": "-1001", "origem_nome": "Origem",
             "filtros": campos.pop("filtros", "{}"), "substituicoes": "[]", "delay": 1, "limite_diario": 0,
             "horario_inicio": "00:00", "horario_fim": "00:00", "termos_bloquear": "", "termos_permitir": ""}
    dados.update(campos)
    rid = db.adicionar_repasse(dados)
    db.set_origens(rid, [{"origem_id": "-1001", "origem_nome": "Origem"}])
    db.set_destinos(rid, [{"grupo_id": d, "grupo_nome": d} for d in destinos])
    return conta, rid


async def iniciar(conta, rid, client):
    tm = TelegramManager()  # o handler roda no loop do teste; o loop próprio do manager fica ocioso
    tm.clients[conta] = client
    await tm._start_repasse(rid)
    return tm


def nova(client, msg):
    return client.handler("_nova_mensagem")(SimpleNamespace(message=msg))


def test_intervalo_espaca_envios_que_chegam_juntos():
    async def cenario():
        conta, rid = criar_repasse(delay=1)
        client = FakeClient()
        await iniciar(conta, rid, client)
        inicio = time.monotonic()
        await asyncio.gather(*(nova(client, FakeMsg(f"oferta {i}")) for i in range(3)))
        return inicio, [t for t, *_ in client.enviados]

    inicio, tempos = asyncio.run(cenario())
    assert len(tempos) == 3
    assert tempos[0] - inicio < 0.5  # o primeiro sai na hora
    assert all(b - a >= 0.95 for a, b in zip(tempos, tempos[1:]))


def test_intervalo_zero_e_respeitado():
    async def cenario():
        conta, rid = criar_repasse(delay=0)
        client = FakeClient()
        await iniciar(conta, rid, client)
        inicio = time.monotonic()
        await asyncio.gather(nova(client, FakeMsg("a")), nova(client, FakeMsg("b")))
        return time.monotonic() - inicio, len(client.enviados)

    duracao, enviados = asyncio.run(cenario())
    assert enviados == 2 and duracao < 0.5


def test_mesma_oferta_de_dois_canais_ao_mesmo_tempo_sai_uma_vez():
    async def cenario():
        conta, rid = criar_repasse(filtros='{"sem_repetidas": true}')
        client = FakeClient()
        await iniciar(conta, rid, client)
        await asyncio.gather(nova(client, FakeMsg(f"Fone {LINK}")), nova(client, FakeMsg(f"Fone barato {LINK}")))
        return client.enviados, rid

    enviados, rid = asyncio.run(cenario())
    assert len(enviados) == 1
    assert [h["status"] for h in db.listar_historico(rid)].count("Ignorada") == 1


def test_limite_diario_sobrevive_a_reinicio():
    async def cenario():
        conta, rid = criar_repasse(delay=0, limite_diario=2)
        client = FakeClient()
        await iniciar(conta, rid, client)
        for i in range(3):
            await nova(client, FakeMsg(f"msg {i}"))
        antes = len(client.enviados)
        reiniciado = FakeClient()
        await iniciar(conta, rid, reiniciado)  # app reaberto no mesmo dia
        await nova(reiniciado, FakeMsg("depois do reinício"))
        return antes, len(reiniciado.enviados)

    assert asyncio.run(cenario()) == (2, 0)


def test_album_vira_um_envio_so():
    async def cenario():
        conta, rid = criar_repasse(delay=0)
        client = FakeClient()
        await iniciar(conta, rid, client)
        fotos = [FakeMsg("legenda", media="foto1", grouped_id=7), FakeMsg("", media="foto2", grouped_id=7)]
        for m in fotos:  # itens soltos do álbum também chegam como NewMessage: devem ser ignorados
            await nova(client, m)
        await client.handler("_novo_album")(SimpleNamespace(messages=fotos))
        return client.enviados

    enviados = asyncio.run(cenario())
    assert len(enviados) == 1
    _, _, texto, arquivos = enviados[0]
    assert texto == "legenda" and arquivos == ["foto1", "foto2"]


def test_flood_wait_espera_e_tenta_de_novo():
    async def cenario():
        conta, rid = criar_repasse(delay=0)
        client = FakeClient(flood_vezes=1)
        await iniciar(conta, rid, client)
        await nova(client, FakeMsg("oferta"))
        return client.enviados, rid

    enviados, rid = asyncio.run(cenario())
    assert len(enviados) == 1
    assert [h["status"] for h in db.listar_historico(rid)] == ["Sucesso"]


def test_midia_baixada_uma_vez_para_varios_destinos_pelo_bot():
    async def cenario():
        conta, rid = criar_repasse(destinos=("-1002", "-1003"), delay=0)
        db.set_config("publicar_via_bot", "1")
        conta_client, bot = FakeClient(), FakeClient()
        tm = await iniciar(conta, rid, conta_client)
        tm.bot = bot
        msg = FakeMsg("oferta", media="foto", photo=True)
        await nova(conta_client, msg)
        return msg.downloads, bot.enviados

    downloads, enviados = asyncio.run(cenario())
    assert downloads == 1 and len(enviados) == 2
    a, b = (e[3] for e in enviados)
    assert a is not b and a.getvalue() == b.getvalue() == b"foto"
