"""
Fontes de busca de ofertas (marketplaces). Registro das fontes e configuração de cada uma.

Config por fonte (tabela config, preenchida pela GUI):
  fonte_<id>_ativa            "1" liga a fonte nas buscas automáticas
  fonte_<id>_pausada          motivo da pausa (vazio = rodando); bloqueio pausa e avisa o admin
  fonte_<id>_req_por_minuto   teto opcional de requisições, menor que o declarado pela fonte
Credenciais ficam nas chaves que cada fonte declara (ex.: ml_client_id), nunca no código nem em log.
"""
import database as db
from fontes.base import (TIPOS_BUSCA, Busca, ErroRequisicao, Fonte, FonteBloqueada,  # noqa: F401
                         FonteIndisponivel, ProdutoEncontrado)

_registro: dict[str, Fonte] | None = None
_ouvintes_bloqueio: list = []   # fn(fonte_id, texto): quem avisa o admin (o loop do bot registra)


def registro() -> dict[str, Fonte]:
    """id -> instância de cada fonte disponível no app."""
    global _registro
    if _registro is None:
        from fontes.mercadolivre import MercadoLivre
        _registro = {f.id: f for f in (MercadoLivre(),)}
    return _registro


def get(fonte_id: str) -> Fonte | None:
    return registro().get(fonte_id)


def ativas() -> list[Fonte]:
    """Fontes ligadas e não pausadas."""
    return [f for f in registro().values() if ativa(f.id) and not pausada(f.id)]


def ativa(fonte_id: str) -> bool:
    return db.get_config(f"fonte_{fonte_id}_ativa", "0") == "1"


def definir_ativa(fonte_id: str, ligada: bool):
    db.set_config(f"fonte_{fonte_id}_ativa", "1" if ligada else "0")


def pausada(fonte_id: str) -> str:
    """Motivo da pausa ("" = não pausada)."""
    return db.get_config(f"fonte_{fonte_id}_pausada", "") or ""


def pausar(fonte_id: str, motivo: str):
    db.set_config(f"fonte_{fonte_id}_pausada", motivo)
    avisar(fonte_id, f"Fonte {fonte_id} pausada: {motivo}")


def retomar(fonte_id: str):
    db.set_config(f"fonte_{fonte_id}_pausada", "")


def req_por_minuto(fonte: Fonte) -> int:
    """Teto efetivo: o configurado pelo usuário, sem nunca passar do declarado pela fonte."""
    try:
        cfg = int(db.get_config(f"fonte_{fonte.id}_req_por_minuto", "0") or 0)
    except ValueError:
        cfg = 0
    return min(cfg, fonte.req_por_minuto) if cfg > 0 else fonte.req_por_minuto


def ao_bloquear(fn):
    """Registra quem recebe os avisos de bloqueio (ex.: alerta ao admin pelo bot)."""
    if fn not in _ouvintes_bloqueio:
        _ouvintes_bloqueio.append(fn)


def avisar(fonte_id: str, texto: str):
    print(f"[Fontes] {texto}")
    for fn in list(_ouvintes_bloqueio):
        try:
            fn(fonte_id, texto)
        except Exception as e:
            print(f"[Fontes] Falha ao avisar sobre {fonte_id}: {e}")
