"""
Autenticação, sessão assinada (HMAC-SHA256), proteção CSRF, rate-limit de login e mascaramento de segredos.
Sem dependências externas além da biblioteca padrão.
"""
import hashlib
import hmac
import os
import secrets
import socket
import time

import database as db

COOKIE_NOME = "repasse_sessao"
PBKDF2_ITER = 260000
SESSAO_TTL_S = 30 * 86400       # 30 dias
JANELA_FALHAS_S = 15 * 60       # 15 minutos
MAX_FALHAS_LOGIN = 5

CHAVES_SENSIVEIS = frozenset({
    "session",
    "bot_token",
    "bot_session",
    "api_hash",
    "ml_access_token",
    "ml_refresh_token",
    "ml_client_secret",
    "cookie",
    "web_password_hash",
    "web_session_secret",
})

_falhas_por_ip: dict[str, list[float]] = {}


def mascarar_config(dados: dict) -> dict:
    """Retorna cópia de um dicionário ocultando qualquer credencial, sessão ou segredo."""
    out = {}
    for k, v in (dados or {}).items():
        kl = str(k).lower()
        sensivel = (
            kl in CHAVES_SENSIVEIS
            or kl.endswith(("_secret", "_token", "_hash", "_password", "session", "cookie"))
        )
        if sensivel:
            out[k] = "••••••••" if v else ""
        else:
            out[k] = v
    return out


def segredo_sessao() -> bytes:
    atual = (db.get_config("web_session_secret") or "").strip()
    if len(atual) < 32:
        atual = secrets.token_hex(32)
        db.set_config("web_session_secret", atual)
    return atual.encode("utf-8")


def tem_senha_web() -> bool:
    env_pw = (os.environ.get("WEB_PASSWORD") or "").strip()
    db_hash = (db.get_config("web_password_hash") or "").strip()
    return bool(env_pw or db_hash)


def gerar_hash_senha(senha: str) -> str:
    limpa = (senha or "").strip()
    if len(limpa) < 6:
        raise ValueError("A senha precisa ter pelo menos 6 caracteres.")
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", limpa.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITER).hex()
    return f"pbkdf2_sha256${PBKDF2_ITER}${salt}${dk}"


def definir_senha_web(senha: str) -> None:
    db.set_config("web_password_hash", gerar_hash_senha(senha))


def verificar_senha_web(senha: str) -> bool:
    tentativa = (senha or "").strip()
    if not tentativa:
        return False
    env_pw = (os.environ.get("WEB_PASSWORD") or "").strip()
    if env_pw:
        return secrets.compare_digest(tentativa.encode("utf-8"), env_pw.encode("utf-8"))
    salvo = (db.get_config("web_password_hash") or "").strip()
    if not salvo:
        return False
    try:
        alg, iters_s, salt_hex, dk_hex = salvo.split("$", 3)
        if alg != "pbkdf2_sha256":
            return False
        calculado = hashlib.pbkdf2_hmac(
            "sha256", tentativa.encode("utf-8"), bytes.fromhex(salt_hex), int(iters_s)
        ).hex()
        return secrets.compare_digest(calculado, dk_hex)
    except Exception:
        return False


def ip_cliente(request) -> str:
    xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if xff:
        return xff
    return request.client.host if request.client else "0.0.0.0"


def eh_acesso_local(request) -> bool:
    if request.headers.get("x-forwarded-for") or request.headers.get("cf-connecting-ip"):
        return False
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost", "testclient")


def criar_cookie_sessao(agora: float | None = None) -> str:
    exp = int((agora if agora is not None else time.time()) + SESSAO_TTL_S)
    nonce = secrets.token_hex(12)
    payload = f"{exp}.{nonce}"
    assinatura = hmac.new(segredo_sessao(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{assinatura}"


def validar_cookie_sessao(valor: str | None, agora: float | None = None) -> str | None:
    """Retorna o payload da sessão se válido e não expirado; caso contrário, None."""
    if not valor or valor.count(".") != 2:
        return None
    exp_s, nonce, assinatura = valor.split(".", 2)
    if not exp_s.isdigit() or not nonce:
        return None
    payload = f"{exp_s}.{nonce}"
    esperada = hmac.new(segredo_sessao(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not secrets.compare_digest(assinatura, esperada):
        return None
    if int(exp_s) < int(agora if agora is not None else time.time()):
        return None
    return payload


def gerar_csrf(payload_sessao: str) -> str:
    return hmac.new(
        segredo_sessao(), f"csrf:{payload_sessao}".encode("utf-8"), hashlib.sha256
    ).hexdigest()[:32]


def validar_csrf(payload_sessao: str, token_enviado: str | None, request=None) -> bool:
    esperado = gerar_csrf(payload_sessao)
    if token_enviado and secrets.compare_digest(str(token_enviado), esperado):
        return True
    if request is not None:
        hdr = request.headers.get("x-csrf-token")
        if hdr and secrets.compare_digest(hdr, esperado):
            return True
    return False


def bloqueado_login(ip: str, agora: float | None = None) -> bool:
    ts = agora if agora is not None else time.time()
    recentes = [t for t in _falhas_por_ip.get(ip, []) if ts - t < JANELA_FALHAS_S]
    _falhas_por_ip[ip] = recentes
    return len(recentes) >= MAX_FALHAS_LOGIN


def registrar_falha_login(ip: str, agora: float | None = None) -> None:
    ts = agora if agora is not None else time.time()
    recentes = [t for t in _falhas_por_ip.get(ip, []) if ts - t < JANELA_FALHAS_S]
    recentes.append(ts)
    _falhas_por_ip[ip] = recentes


def limpar_falhas_login(ip: str) -> None:
    _falhas_por_ip.pop(ip, None)


def resetar_rate_limit() -> None:
    _falhas_por_ip.clear()


def obter_ip_rede_local() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.4)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return "127.0.0.1"
