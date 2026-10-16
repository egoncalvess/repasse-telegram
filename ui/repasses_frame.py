import customtkinter as ctk
from tkinter import messagebox

import database as db
from telegram_manager import telegram_manager
from ui import estilo as e


class RepassesFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, corner_radius=0, fg_color=e.FUNDO)
        acoes = e.cabecalho(self, "Repasses")
        e.acao(acoes, e.botao_texto(acoes, "Remover", self._remove, perigo=True))
        e.acao(acoes, e.botao(acoes, "Relatório", self._report))
        self._btn_pausar = e.acao(acoes, e.botao(acoes, "Pausar", self._toggle, largura=96))
        e.acao(acoes, e.botao(acoes, "Editar", self._edit))
        e.acao(acoes, e.botao_primario(acoes, "Novo repasse", self._add))

        # Sem bot, as mensagens saem pela conta de usuário (comportamento antigo): recomenda configurar o bot
        self._aviso_bot = ctk.CTkFrame(self, fg_color="transparent")
        e.rotulo(self._aviso_bot, "Sem bot configurado: os repasses são enviados pela sua conta.",
                 e.F_LEGENDA, secundario=True).pack(side="left")
        e.botao_texto(self._aviso_bot, "Configurar o bot", self._ir_bot).pack(side="left", padx=(e.E1, 0))

        lista = ctk.CTkFrame(self, fg_color="transparent")
        lista.pack(fill="both", expand=True, padx=e.MARGEM, pady=(0, e.E3))
        self._lista = lista
        self._tabela = e.Tabela(lista, [("status", "Status", 2, {"tipo": "status", "min": 104}), ("nome", "Nome", 4),
                                        ("origens", "Origens", 6), ("destinos", "Destinos", 5),
                                        ("total", "Enviados", 2, {"alinhar": "e", "min": 80})])
        self._tabela.ao_duplo_clique(lambda _: self._edit())
        self._tabela.ao_selecionar(lambda _: self._atualizar_botoes())
        self._vazio = e.estado_vazio(lista, "Nenhum repasse ainda. Crie um para levar ofertas de outros canais para "
                                            "os seus.", "Novo repasse", self._add)
        self._ativos: dict[str, int] = {}

    def refresh(self):
        if (db.get_config("bot_token") or "").strip():
            self._aviso_bot.pack_forget()
        else:
            self._aviso_bot.pack(anchor="w", padx=e.MARGEM, pady=(0, e.E2), before=self._lista)
        linhas, ids = [], []
        self._ativos = {}
        for r in db.listar_repasses():
            origens = [o["origem_nome"] for o in db.listar_origens(r["id"])]
            destinos = [d["grupo_nome"] for d in db.listar_destinos(r["id"])]
            linhas.append((("ok", "Ativo") if r["ativo"] else ("inativo", "Pausado"), r["descricao"],
                           _resumo(origens), _resumo(destinos) or ("Só radar, sem destino", "secundario"), r["total"]))
            ids.append(str(r["id"]))
            self._ativos[str(r["id"])] = r["ativo"]
        if ids:
            self._vazio.pack_forget()
            self._tabela.pack(fill="both", expand=True)
            self._tabela.carregar(linhas, ids)
        else:
            self._tabela.pack_forget()
            self._vazio.pack(anchor="w")
        self._atualizar_botoes()

    def _atualizar_botoes(self):
        rid = self._tabela.selecionado()
        self._btn_pausar.configure(text="Ativar" if rid and not self._ativos.get(rid) else "Pausar")

    def _ir_bot(self):
        app = self.winfo_toplevel()
        if hasattr(app, "show_frame"):
            app.show_frame("configuracoes")

    def _sel(self):
        rid = self._tabela.selecionado()
        if not rid:
            messagebox.showinfo("Repasses", "Selecione um repasse na lista.", parent=self)
        return int(rid) if rid else None

    def _toggle(self):
        rid = self._sel()
        r = db.get_repasse(rid) if rid else None
        if not r:
            return
        novo = 0 if r["ativo"] else 1
        db.toggle_repasse(rid, novo)
        if novo:
            telegram_manager.iniciar_repasse(rid)
        else:
            telegram_manager.parar_repasse(rid, r["conta_id"])
        telegram_manager.atualizar_radar(r["conta_id"])
        self.refresh()

    def _add(self):
        from ui.repasse_dialog import RepasseDialog
        RepasseDialog(self, repasse_id=None, ao_salvar=self.refresh)

    def _edit(self):
        rid = self._sel()
        if rid:
            from ui.repasse_dialog import RepasseDialog
            RepasseDialog(self, repasse_id=rid, ao_salvar=self.refresh)

    def _remove(self):
        rid = self._sel()
        if not rid:
            return
        r = db.get_repasse(rid)
        if not r:
            return self.refresh()
        if messagebox.askyesno("Remover repasse", f"Remover o repasse \"{r['descricao']}\"? Ele para na hora.",
                               parent=self):
            telegram_manager.parar_repasse(rid, r["conta_id"])
            db.remover_repasse(rid)
            telegram_manager.atualizar_radar(r["conta_id"])
            self.refresh()

    def _report(self):
        rid = self._sel()
        if rid:
            ReportDialog(self, rid)


def _resumo(nomes: list[str]) -> str:
    if not nomes:
        return ""
    return ", ".join(n[:25] for n in nomes[:2]) + (f" +{len(nomes) - 2}" if len(nomes) > 2 else "")


ESTADO_HISTORICO = {"Sucesso": "ok", "Falha": "falha", "Falha ao iniciar": "falha", "Erro Afiliados": "falha"}


class ReportDialog(ctk.CTkToplevel):
    def __init__(self, parent, repasse_id: int):
        super().__init__(parent)
        self._rid = repasse_id
        r = db.get_repasse(repasse_id)
        e.janela(self, f"Relatório: {r['descricao'] if r else repasse_id}", 900, 520, parent)
        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.pack(fill="x", padx=e.E3, pady=(e.E3, e.E2))
        e.rotulo(topo, r["descricao"] if r else "Relatório", e.F_SECAO).pack(side="left")
        e.botao_texto(topo, "Atualizar", self._load).pack(side="right")
        self._tabela = e.Tabela(self, [("data", "Data", 3, {"min": 144}), ("destino", "Destino ou origem", 4),
                                       ("status", "Status", 3, {"tipo": "status", "min": 120}), ("det", "Detalhes", 9)],
                                fundo=e.SUPERFICIE)
        self._tabela.pack(fill="both", expand=True, padx=e.E3, pady=(0, e.E3))
        self._load()

    def _load(self):
        self._tabela.carregar([(h["data"] or "—", h["destino"] or "—",
                                (ESTADO_HISTORICO.get(h["status"], "inativo"), h["status"]), h["detalhes"] or "")
                               for h in db.listar_historico(self._rid)])
