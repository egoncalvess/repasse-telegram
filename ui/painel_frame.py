"""
Painel (tela inicial): o resumo do dia numa frase e as quedas de preço de agora.
"""
import customtkinter as ctk
from tkinter import messagebox

import database as db
from oferta import brl, queda, selo
from ui import estilo as e
from ui.fundo import em_segundo_plano

# Mesma tabela no Painel e em Ofertas
COLUNAS_OFERTAS = [("produto", "Produto", 8), ("loja", "Loja", 3, {"min": 112, "opcional": True}),
                   ("agora", "Agora", 2, {"alinhar": "e", "min": 104}),
                   ("antes", "Antes", 2, {"alinhar": "e", "min": 104, "opcional": True}),
                   ("queda", "Queda", 2, {"alinhar": "e", "tipo": "queda", "min": 72})]


def linha_oferta(p: dict) -> tuple:
    antes, pct = queda(p)
    return (p["nome"], p["loja"], brl(p["preco_hoje"]), brl(antes) if antes else ("—", "secundario"),
            f"-{pct}%" if pct else ("—", "secundario"))


def _contagem(n: int, um: str, varios: str, nenhum: str) -> str:
    return nenhum if n == 0 else (f"1 {um}" if n == 1 else f"{n} {varios}")


class PainelFrame(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, corner_radius=0, fg_color=e.FUNDO)
        self._app = app
        acoes = e.cabecalho(self, "Painel")
        e.acao(acoes, e.botao_texto(acoes, "Atualizar", self.refresh))

        resumo = ctk.CTkFrame(self, fg_color="transparent")
        resumo.pack(fill="x", padx=e.MARGEM, pady=(0, e.E3))
        # a frase quebra linha quando o painel de detalhe aperta a tela
        self._resumo = e.paragrafo(resumo, "Carregando…", e.F_CORPO, secundario=False)
        self._fila = e.botao_texto(resumo, "", lambda: FilaDialog(self, self.refresh))

        self._bloco = e.secao(self, "Quedas de preço agora", fill="both", expand=True)
        self._tabela = e.Tabela(self._bloco, COLUNAS_OFERTAS)
        self._tabela.ao_selecionar(self._app.abrir_detalhe)
        self._vazio = e.estado_vazio(self._bloco, "Nenhuma queda de preço hoje. Crie uma busca para o app procurar "
                                                  "sozinho.", "Nova busca", self._nova_busca, primario=True)

    def refresh(self):
        def _ler():
            itens = db.menores_precos_do_dia(limit=5000)
            fora = db.descartados()
            quedas = [p for p in itens if p["chave"] not in fora and selo(p)]
            return {"encontrados": len(itens), "quedas": quedas, "publicados": db.contar_envios_hoje(),
                    "falhas": db.falhas_hoje(), "fila": db.contar_fila_pendente()}

        em_segundo_plano(self, _ler, lambda dados, err: self._render(err or dados))

    def _render(self, d):
        if not self.winfo_exists():
            return
        if isinstance(d, Exception):
            self._resumo.configure(text=f"Não foi possível ler o banco: {d}")
            return
        self._resumo.configure(text="Hoje: " + ", ".join([
            _contagem(d["encontrados"], "encontrado", "encontrados", "nenhum encontrado"),
            _contagem(len(d["quedas"]), "queda", "quedas", "nenhuma queda"),
            _contagem(d["publicados"], "publicado", "publicados", "nenhum publicado"),
            _contagem(d["falhas"], "falha", "falhas", "nenhuma falha")]) + ".")
        if d["fila"]:
            self._fila.configure(text=f"{d['fila']} aguardando aprovação")
            self._fila.pack(anchor="w", pady=(4, 0))
        else:
            self._fila.pack_forget()

        if d["quedas"]:
            self._vazio.pack_forget()
            self._tabela.pack(fill="both", expand=True)
            self._tabela.carregar([linha_oferta(p) for p in d["quedas"]], ids=[p["chave"] for p in d["quedas"]])
        else:
            self._tabela.pack_forget()
            self._vazio.pack(anchor="w", pady=(e.E1, 0))

    def limpar_selecao(self):
        self._tabela.selecionar(None)

    def _nova_busca(self):
        self._app.show_frame("buscas")
        self._app._frames["buscas"].nova()


class FilaDialog(ctk.CTkToplevel):
    """Ofertas que o piloto deixou aguardando aprovação (modo com aprovação)."""

    def __init__(self, parent, ao_mudar):
        super().__init__(parent)
        e.janela(self, "Aguardando aprovação", 760, 460, parent)
        self._ao_mudar = ao_mudar
        rod = ctk.CTkFrame(self, fg_color="transparent")
        rod.pack(side="bottom", fill="x", padx=e.E3, pady=e.E3)
        e.botao_primario(rod, "Publicar", self._publicar).pack(side="right")
        e.botao(rod, "Descartar", self._descartar).pack(side="right", padx=(0, e.E1))
        self._aviso = e.rotulo(rod, "", e.F_LEGENDA, secundario=True)
        self._aviso.pack(side="left")
        e.rotulo(self, "Aguardando aprovação", e.F_SECAO).pack(anchor="w", padx=e.E3, pady=(e.E3, e.E2))
        self._tabela = e.Tabela(self, [("produto", "Produto", 8), ("loja", "Loja", 3),
                                       ("desde", "Desde", 2, {"alinhar": "e"})], fundo=e.SUPERFICIE)
        self._tabela.pack(fill="both", expand=True, padx=e.E3)
        self._carregar()

    def _carregar(self):
        itens = db.listar_fila("pendente", limit=200)
        self._tabela.carregar([(f["nome"] or f["chave"], f["loja"] or "—", f["criado_em"][11:16]) for f in itens],
                              ids=[f["id"] for f in itens])
        if not itens:
            self._aviso.configure(text="Nada aguardando aprovação.")

    def _item(self):
        fid = self._tabela.selecionado()
        if not fid:
            messagebox.showinfo("Aguardando aprovação", "Selecione uma oferta na lista.", parent=self)
            return None
        return db.get_fila(int(fid))

    def _publicar(self):
        item = self._item()
        destino = (db.get_config("radar_destino") or "").strip()
        if not item:
            return
        if not destino:
            messagebox.showwarning("Aguardando aprovação", "Defina onde publicar em Ofertas → Publicação automática.",
                                   parent=self)
            return
        self._aviso.configure(text="Publicando…")

        def _trabalho():
            from oferta import publicar_oferta
            from telegram_manager import telegram_manager
            publicar_oferta(item["chave"], next(iter(telegram_manager.clients), None), destino, origem="piloto")
            db.decidir_fila(item["id"], "aprovada")

        def _fim(_, err):
            self._aviso.configure(text=f"Não publicado: {err}" if err else "Publicado.")
            self._carregar()
            self._ao_mudar()
        em_segundo_plano(self, _trabalho, _fim)

    def _descartar(self):
        item = self._item()
        if item:
            db.decidir_fila(item["id"], "descartada")
            self._aviso.configure(text="Descartado.")
            self._carregar()
            self._ao_mudar()
