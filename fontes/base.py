"""
Contrato de uma fonte de busca de ofertas (marketplace). Cada fonte é um arquivo em fontes/ com uma
subclasse de Fonte; toda requisição dela passa pelo ClienteHTTP de fontes/http.py.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

TIPOS_BUSCA = ("categoria", "termo", "produto")


class FonteBloqueada(Exception):
    """A fonte (ou o endpoint) recusou acesso: não adianta insistir até um novo teste manual."""


class FonteIndisponivel(Exception):
    """Falha passageira (rede, 5xx, limite): a fonte tenta de novo na próxima execução."""


class ErroRequisicao(Exception):
    """Resposta 4xx que não é bloqueio (ex.: 404 de um id inexistente): erro da chamada, não da fonte."""

    def __init__(self, status: int, mensagem: str):
        super().__init__(f"HTTP {status}: {mensagem}")
        self.status = status


@dataclass
class ProdutoEncontrado:
    chave: str                  # mesmo formato de dedup.chave_produto(): "<prefixo de dedup.PADROES>:<id>"
    nome: str
    url: str
    preco: float
    preco_original: float | None = None   # só quando a loja informa um preço "de" real, maior que o atual
    imagem_url: str | None = None
    frete_gratis: bool = False
    categoria: str | None = None
    loja: str = ""


@dataclass
class Busca:
    tipo: str                   # categoria | termo | produto
    valor: str                  # id da categoria, termo de busca ou id/URL do produto
    limite: int = 10            # máximo de produtos devolvidos


class Fonte(ABC):
    id: str = ""                # prefixo de dedup.PADROES ("ml")
    nome: str = ""              # nome exibido ("Mercado Livre")
    loja: str = ""              # chave da loja em affiliate_helper.DOMINIOS ("mercadolivre")
    tipo: str = "api_oficial"   # api_oficial | scraping
    req_por_minuto: int = 30    # teto de requisições (o ClienteHTTP espera para não passar disso)
    intervalo_min_padrao: int = 60  # intervalo sugerido entre execuções de uma busca

    def __init__(self):
        from fontes.http import ClienteHTTP
        self.http = ClienteHTTP(self)

    @abstractmethod
    def buscar(self, busca: Busca) -> list[ProdutoEncontrado]:
        """Produtos encontrados agora. Levanta FonteBloqueada/FonteIndisponivel em falha."""

    @abstractmethod
    def testar(self) -> dict:
        """Teste manual: libera endpoints bloqueados e faz uma chamada a cada um.
        Retorna {"ok": bool, "endpoints": {endpoint: "ok" | motivo}, "mensagem": str}."""
