"""Tela de repasses: lista em tabela rápida, ativar/pausar, editar, relatório."""
import customtkinter as ctk
from tkinter import messagebox
import database as db
from telegram_manager import telegram_manager
from ui.estilo import Tabela, botao, cabecalho, card, FUNDO, F_PEQUENA, TEXTO_SEC


class RepassesFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, corner_radius=0, fg_color=FUNDO)
        acoes = cabecalho(self, "Repasses", "Várias origens → seus grupos/canais, com sua afiliação")
        botao(acoes, "+ Novo", self._add, "azul", 100).pack(side="left", padx=4)
        botao(acoes, "Editar", self._edit, "cinza", 90).pack(side="left", padx=4)
        botao(acoes, "Ativar/Pausar", self._toggle, "cinza", 120).pack(side="left", padx=4)
        botao(acoes, "Relatório", self._report, "cinza", 100).pack(side="left", padx=4)
        botao(acoes, "Remover", self._remove, "vermelho", 100).pack(side="left", padx=4)

        c = card(self, fill="both", expand=True)
        self._tabela = Tabela(c, [("status", "Status", 2), ("nome", "Nome", 4), ("origens", "Origens", 6),
                                  ("destinos", "Destinos", 5), ("total", "Enviados", 2)], altura=14)
        self._tabela.pack(fill="both", expand=True, padx=10, pady=10)
        self._tabela.tree.bind("<Double-1>", lambda _: self._edit())
        ctk.CTkLabel(self, text="Dica: duplo clique para editar.", font=F_PEQUENA,
                     text_color=TEXTO_SEC).pack(anchor="w", padx=24, pady=(0, 10))

    def refresh(self):
        linhas, ids = [], []
        for r in db.listar_repasses():
            origens = [o["origem_nome"] for o in db.listar_origens(r["id"])]
            destinos = [d["grupo_nome"] for d in db.listar_destinos(r["id"])]
            linhas.append(("🟢 Ativo" if r["ativo"] else "⏸ Pausado", r["descricao"],
                           _resumo(origens), _resumo(destinos) or "— só radar (sem destino)", r["total"]))
            ids.append(str(r["id"]))
        self._tabela.carregar(linhas, ids)

    def _sel(self):
        rid = self._tabela.selecionado()
        if not rid:
            messagebox.showwarning("Aviso", "Selecione um repasse na lista.")
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
        if rid and messagebox.askyesno("Confirmar", "Remover este repasse?"):
            r = db.get_repasse(rid)
            if r:
                telegram_manager.parar_repasse(rid, r["conta_id"])
            db.remover_repasse(rid)
            if r:
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


class ReportDialog(ctk.CTkToplevel):
    def __init__(self, parent, repasse_id: int):
        super().__init__(parent)
        self._rid = repasse_id
        r = db.get_repasse(repasse_id)
        self.title(f"Relatório — {r['descricao'] if r else repasse_id}")
        self.geometry("900x500")
        self.minsize(600, 360)
        self.configure(fg_color=FUNDO)
        self.transient(parent)
        acoes = cabecalho(self, "Relatório do repasse", r["descricao"] if r else "")
        botao(acoes, "↻ Atualizar", self._load, "cinza", 110).pack()
        c = card(self, fill="both", expand=True)
        self._tabela = Tabela(c, [("data", "Data", 3), ("destino", "Destino/origem", 4),
                                  ("status", "Status", 2), ("det", "Detalhes", 9)], altura=14)
        self._tabela.pack(fill="both", expand=True, padx=10, pady=10)
        self._load()

    def _load(self):
        icone = {"Sucesso": "✅", "Falha": "❌", "Ignorada": "⏭", "Falha ao iniciar": "⚠️"}
        self._tabela.carregar([(h["data"] or "-", h["destino"] or "-",
                                f"{icone.get(h['status'], '•')} {h['status']}", h["detalhes"] or "")
                               for h in db.listar_historico(self._rid)])
