"""
Janela principal: barra lateral (navegação + status), conteúdo da tela e painel de detalhe à direita
(abre ao selecionar uma oferta, fecha com Esc).
"""
import customtkinter as ctk
from PIL import Image

from ui import estilo as e
from ui.fontes import recurso  # noqa: F401  (reexportado: outros módulos importam daqui)

NAVEGACAO = [("painel", "Painel"), ("ofertas", "Ofertas"), ("buscas", "Buscas"), ("repasses", "Repasses"),
             ("contas", "Contas"), ("afiliados", "Afiliados"), ("configuracoes", "Configurações")]


class ItemNavegacao(ctk.CTkFrame):
    """Só texto; o ativo fica em TINTA SemiBold com barra AZUL de 3 px à esquerda."""

    def __init__(self, parent, texto, comando):
        super().__init__(parent, fg_color="transparent", corner_radius=0, height=36, cursor="hand2")
        self.pack_propagate(False)
        self._barra = ctk.CTkFrame(self, width=3, corner_radius=0, fg_color="transparent")
        self._barra.pack(side="left", fill="y")
        self._texto = e.rotulo(self, texto, e.F_CORPO, secundario=True)
        self._texto.pack(side="left", padx=(e.E3 - 3, 0))
        for w in (self, self._texto):
            w.bind("<Button-1>", lambda _: comando())
            w.bind("<Enter>", lambda _: self.configure(fg_color=e.REALCE))
            w.bind("<Leave>", lambda _: self.configure(fg_color="transparent"))

    def ativar(self, ativo: bool):
        self._barra.configure(fg_color=e.AZUL if ativo else "transparent")
        self._texto.configure(font=e.F_CORPO_FORTE if ativo else e.F_CORPO,
                              text_color=e.TINTA if ativo else e.TINTA_2)


class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("PROMO DO BAIANO — Repasse & Radar")
        self.geometry("1240x760")
        self.minsize(980, 620)
        self.configure(fg_color=e.FUNDO)
        try:
            self.iconbitmap(str(recurso("assets/logo.ico")))
        except Exception:
            pass

        self._build_lateral()
        e.divisoria(self, vertical=True).pack(side="left", fill="y")
        self._content = ctk.CTkFrame(self, corner_radius=0, fg_color=e.FUNDO)
        self._content.pack(side="left", fill="both", expand=True)

        from ui.detalhe import PainelDetalhe
        self._div_detalhe = e.divisoria(self, vertical=True)
        self._detalhe = PainelDetalhe(self, ao_fechar=self.fechar_detalhe, ao_mudar=self._recarregar_atual)
        self._detalhe_aberto = False
        self.bind("<Escape>", lambda _: self.fechar_detalhe())

        self._frames = {}
        self._atual = None
        self._load_frames()
        self.show_frame("painel")
        self.after(1500, self._atualizar_status)

    # ── Barra lateral ────────────────────────────────────────────────────────

    def _build_lateral(self):
        lat = ctk.CTkFrame(self, width=e.LARGURA_LATERAL, corner_radius=0, fg_color=e.FUNDO)
        lat.pack(side="left", fill="y")
        lat.pack_propagate(False)

        marca = ctk.CTkFrame(lat, fg_color="transparent")
        marca.pack(fill="x", padx=e.E3, pady=(e.E3, e.E4))
        try:
            img = ctk.CTkImage(Image.open(recurso("assets/logo.png")), size=(32, 32))
            ctk.CTkLabel(marca, image=img, text="").pack(side="left", padx=(0, e.E1))
        except Exception:
            pass
        e.rotulo(marca, "Promo do Baiano", e.F_CORPO_FORTE).pack(side="left")

        self._nav: dict[str, ItemNavegacao] = {}
        for chave, texto in NAVEGACAO:
            item = ItemNavegacao(lat, texto, lambda k=chave: self.show_frame(k))
            item.pack(fill="x")
            self._nav[chave] = item

        self._rodape = ctk.CTkFrame(lat, fg_color="transparent")
        self._rodape.pack(side="bottom", fill="x", padx=e.E3, pady=e.E3)
        self._pontos: dict[str, e.PontoStatus] = {}
        self._pausa = e.rotulo(self._rodape, "", e.F_LEGENDA)
        self._pausa.configure(text_color=e.ERRO)

    def _estados(self) -> list[tuple[str, str, str]]:
        """[(chave, estado, texto)] do rodapé: bot, conta e cada fonte ativa."""
        import database as db
        import fontes
        from telegram_manager import telegram_manager as tm

        if tm.bot:
            bot = ("ok", "Bot online")
        elif (db.get_config("bot_token") or "").strip():
            bot = ("falha", "Bot offline")
        else:
            bot = ("inativo", "Sem bot")
        itens = [("bot", *bot),
                 ("conta", "ok" if tm.clients else "inativo", "Conta conectada" if tm.clients else "Sem conta")]
        for f in fontes.registro().values():
            if not fontes.ativa(f.id):
                continue
            bloqueados = [ep for ep, s in db.endpoints_da_fonte(f.id).items() if s["status"] == "bloqueado"]
            if fontes.pausada(f.id):
                itens.append((f"fonte_{f.id}", "falha", f"{f.nome} pausada"))
            elif bloqueados:
                itens.append((f"fonte_{f.id}", "falha", f"{f.nome} com bloqueio"))
            else:
                itens.append((f"fonte_{f.id}", "ok", f"{f.nome} ok"))
        return itens

    def _atualizar_status(self):
        try:
            import database as db
            itens = self._estados()
            if [k for k, _, _ in itens] != list(self._pontos):
                for p in self._pontos.values():
                    p.destroy()
                self._pontos = {k: e.ponto_status(self._rodape) for k, _, _ in itens}
                for p in self._pontos.values():
                    p.pack(anchor="w", pady=(0, 4))
            for k, estado, texto in itens:
                self._pontos[k].atualizar(estado, texto)
            pausado = db.get_config("pausado", "0") == "1"
            self._pausa.configure(text="Pausado" if pausado else "")
            if pausado:
                self._pausa.pack(anchor="w", pady=(e.E1, 0))
            else:
                self._pausa.pack_forget()
        except Exception as ex:
            print(f"[UI] Falha ao atualizar o status: {ex}")
        finally:
            self.after(5000, self._atualizar_status)

    # ── Conteúdo ─────────────────────────────────────────────────────────────

    def _load_frames(self):
        from ui.painel_frame import PainelFrame
        from ui.radar_frame import OfertasFrame
        from ui.buscador_frame import BuscasFrame
        from ui.repasses_frame import RepassesFrame
        from ui.contas_frame import ContasFrame
        from ui.integracoes_frame import IntegracoesFrame
        from ui.configuracoes_frame import ConfiguracoesFrame
        from ui.banco_frame import BancoFrame

        self._frames = {
            "painel":        PainelFrame(self._content, self),
            "ofertas":       OfertasFrame(self._content, self),
            "buscas":        BuscasFrame(self._content),
            "repasses":      RepassesFrame(self._content),
            "contas":        ContasFrame(self._content),
            "afiliados":     IntegracoesFrame(self._content),
            "configuracoes": ConfiguracoesFrame(self._content, self),
            "banco":         BancoFrame(self._content, self),   # aberta por Configurações → Dados
        }

    def show_frame(self, name: str):
        self.fechar_detalhe()
        for f in self._frames.values():
            f.pack_forget()
        for k, item in self._nav.items():
            item.ativar(k == name or (name == "banco" and k == "configuracoes"))
        self._atual = name
        self._frames[name].pack(fill="both", expand=True)
        if hasattr(self._frames[name], "refresh"):
            self._frames[name].refresh()

    def _recarregar_atual(self):
        frame = self._frames.get(self._atual)
        if frame is not None and hasattr(frame, "refresh"):
            frame.refresh()

    # ── Painel de detalhe ────────────────────────────────────────────────────

    def abrir_detalhe(self, chave: str):
        if not self._detalhe_aberto:
            self._detalhe.pack(side="right", fill="y", before=self._content)
            self._div_detalhe.pack(side="right", fill="y", before=self._content)
            self._detalhe_aberto = True
        self._detalhe.mostrar(chave)

    def fechar_detalhe(self):
        if self._detalhe_aberto:
            self._detalhe.pack_forget()
            self._div_detalhe.pack_forget()
            self._detalhe_aberto = False
            frame = self._frames.get(self._atual)
            if frame is not None and hasattr(frame, "limpar_selecao"):
                frame.limpar_selecao()
