"""
Cliente HTTP único das fontes de busca. Nenhuma fonte faz requisição por fora dele.

- Limite de requisições por fonte (janela de 60 s): espera em vez de passar do teto.
- 429/5xx/rede: backoff exponencial com jitter (respeita Retry-After); esgotadas as tentativas, a falha
  conta para o circuit breaker do endpoint (3 falhas seguidas = endpoint em pausa por 15 min).
- 401/403 (API oficial): o endpoint fica bloqueado no banco até um novo teste manual da fonte.
- Fonte "scraping": consulta robots.txt (cache 24 h), User-Agent honesto, e a primeira resposta de bloqueio
  ou captcha pausa a fonte inteira e avisa o admin. Nada de proxy, rotação de IP ou disfarce de navegador.
- Cache com TTL (GET), timeout, e log de cada chamada em api_chamadas (sem URL, parâmetros ou credenciais).
"""
import random
import threading
import time
from collections import deque
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

import database as db
import fontes
from fontes.base import ErroRequisicao, FonteBloqueada, FonteIndisponivel

USER_AGENT = "PromoDoBaiano-Repasse/1.0 (app desktop de ofertas; respeita robots.txt)"
TIMEOUT_S = 15
TENTATIVAS = 3
BACKOFF_BASE_S = 2.0
BACKOFF_MAX_S = 60.0
FALHAS_PARA_ABRIR = 3
CIRCUITO_ABERTO_S = 15 * 60
ROBOTS_TTL_S = 24 * 3600
CACHE_MAX = 500
MARCAS_CAPTCHA = ("captcha", "cf-challenge", "challenge-platform", "are you a robot", "não sou um robô",
                  "nao sou um robo", "unusual traffic")


class ClienteHTTP:
    def __init__(self, fonte, sessao=None, relogio=time.monotonic, dormir=time.sleep):
        self.fonte = fonte
        self.sessao = sessao or requests.Session()
        self._relogio, self._dormir = relogio, dormir
        self._lock = threading.Lock()
        self._janela: deque[float] = deque()          # instantes das requisições do último minuto
        self._cache: dict[tuple, tuple[float, object]] = {}
        self._falhas: dict[str, int] = {}             # endpoint -> falhas seguidas
        self._aberto_ate: dict[str, float] = {}       # endpoint -> fim da pausa do circuit breaker
        self._ok_conhecidos: set[str] = set()         # endpoints já marcados "ok" no banco nesta sessão
        self._robots: dict[str, tuple[float, RobotFileParser]] = {}

    # ── API pública ──────────────────────────────────────────────────────────

    def get(self, url, endpoint, params=None, headers=None, cache_ttl=0, renovar_auth=None):
        return self.requisitar("GET", url, endpoint, params=params, headers=headers,
                               cache_ttl=cache_ttl, renovar_auth=renovar_auth)

    def post(self, url, endpoint, data=None, headers=None):
        return self.requisitar("POST", url, endpoint, data=data, headers=headers)

    def baixar(self, url, endpoint="/imagem", max_bytes=5_000_000) -> bytes | None:
        """Arquivo binário (foto do produto). Uma tentativa só; falha devolve None e a busca segue sem foto."""
        if not url or fontes.pausada(self.fonte.id):
            return None
        if self.fonte.tipo == "scraping" and not self._robots_permite(url):
            return None
        resp, status, _ = self._enviar("GET", url, endpoint, None, None, {"User-Agent": USER_AGENT})
        if resp is None or status != 200 or not resp.headers.get("Content-Type", "").startswith("image/"):
            return None
        return resp.content if len(resp.content) <= max_bytes else None

    def limpar_cache(self):
        self._cache.clear()

    def requisitar(self, metodo, url, endpoint, params=None, data=None, headers=None, cache_ttl=0,
                   renovar_auth=None):
        """JSON (ou texto, se a resposta não for JSON) do endpoint.
        renovar_auth: fn() -> headers novos, chamada uma vez se a resposta for 401 (token vencido)."""
        fid = self.fonte.id
        motivo = fontes.pausada(fid)
        if motivo:
            raise FonteBloqueada(f"{self.fonte.nome} pausada: {motivo}")
        bloqueio = db.endpoints_da_fonte(fid).get(endpoint)
        if bloqueio and bloqueio["status"] == "bloqueado":
            raise FonteBloqueada(f"{endpoint} bloqueado desde {bloqueio['atualizado_em']}: {bloqueio['detalhe']}. "
                                 "Teste a fonte em Configurações para tentar de novo.")
        if self._aberto_ate.get(endpoint, 0) > self._relogio():
            raise FonteIndisponivel(f"{endpoint} em pausa após falhas seguidas; tenta de novo mais tarde.")

        chave_cache = (metodo, url, tuple(sorted((params or {}).items())))
        if metodo == "GET" and cache_ttl:
            hit = self._cache.get(chave_cache)
            if hit and hit[0] > self._relogio():
                return hit[1]

        if self.fonte.tipo == "scraping" and not self._robots_permite(url):
            raise FonteBloqueada(f"robots.txt de {urlparse(url).netloc} não permite {urlparse(url).path}.")

        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"} | (headers or {})
        renovou = False
        tentativa = 0
        while True:
            tentativa += 1
            resp, status, ms = self._enviar(metodo, url, endpoint, params, data, headers)

            if status == 401 and renovar_auth and not renovou:
                renovou = True
                headers = headers | renovar_auth()
                tentativa -= 1  # renovar o token não gasta tentativa
                continue

            if self.fonte.tipo == "scraping" and resp is not None and self._parece_bloqueio(resp):
                fontes.pausar(fid, f"{urlparse(url).netloc} respondeu {status} com sinal de bloqueio/captcha "
                                   f"em {endpoint}. Retome manualmente depois de verificar.")
                raise FonteBloqueada(fontes.pausada(fid))

            if status in (401, 403):
                detalhe = f"HTTP {status}: {self._resumo(resp)}"
                db.marcar_endpoint(fid, endpoint, "bloqueado", detalhe)
                self._ok_conhecidos.discard(endpoint)
                fontes.avisar(fid, f"{self.fonte.nome}: {endpoint} recusou acesso ({detalhe}). "
                                   "O endpoint não será chamado de novo até um teste manual.")
                raise FonteBloqueada(f"{endpoint} recusou acesso ({detalhe}).")

            if status == 0 or status == 429 or status >= 500:
                espera = self._espera_backoff(tentativa, resp)
                if tentativa >= TENTATIVAS or espera is None:
                    self._registrar_falha(endpoint)
                    raise FonteIndisponivel(f"{endpoint} falhou ({'sem resposta' if status == 0 else f'HTTP {status}'})"
                                            f" após {tentativa} tentativa(s).")
                self._dormir(espera)
                continue

            if status >= 400:
                raise ErroRequisicao(status, self._resumo(resp))

            self._falhas.pop(endpoint, None)
            if endpoint not in self._ok_conhecidos:
                db.marcar_endpoint(fid, endpoint, "ok")
                self._ok_conhecidos.add(endpoint)
            try:
                dados = resp.json()
            except ValueError:
                dados = resp.text
            if metodo == "GET" and cache_ttl:
                if len(self._cache) >= CACHE_MAX:
                    self._cache.clear()
                self._cache[chave_cache] = (self._relogio() + cache_ttl, dados)
            return dados

    # ── Internos ─────────────────────────────────────────────────────────────

    def _enviar(self, metodo, url, endpoint, params, data, headers):
        """Uma requisição, dentro do limite da fonte, registrada em api_chamadas."""
        self._aguardar_vez()
        t0 = time.perf_counter()
        try:
            resp = self.sessao.request(metodo, url, params=params, data=data, headers=headers, timeout=TIMEOUT_S)
            status = resp.status_code
        except requests.RequestException:
            resp, status = None, 0
        ms = int((time.perf_counter() - t0) * 1000)
        try:
            db.registrar_chamada_api(self.fonte.id, endpoint, status, ms)
        except Exception as e:
            print(f"[Fontes] Falha ao registrar chamada: {e}")
        return resp, status, ms

    def _aguardar_vez(self):
        limite = max(1, fontes.req_por_minuto(self.fonte))
        with self._lock:
            agora = self._relogio()
            while self._janela and self._janela[0] <= agora - 60:
                self._janela.popleft()
            if len(self._janela) >= limite:
                espera = self._janela[0] + 60 - agora
                if espera > 0:
                    self._dormir(espera)
                agora = self._relogio()
                while self._janela and self._janela[0] <= agora - 60:
                    self._janela.popleft()
            self._janela.append(self._relogio())

    def _espera_backoff(self, tentativa, resp):
        """Segundos até a próxima tentativa; None = a espera pedida é longa demais, desiste agora."""
        retry_after = resp.headers.get("Retry-After") if resp is not None else None
        if retry_after:
            try:
                segundos = float(retry_after)
            except ValueError:
                segundos = BACKOFF_MAX_S + 1  # data HTTP: não vale segurar a busca, tenta na próxima rodada
            return segundos if segundos <= BACKOFF_MAX_S else None
        return min(BACKOFF_MAX_S, BACKOFF_BASE_S * 2 ** (tentativa - 1)) + random.uniform(0, BACKOFF_BASE_S)

    def _registrar_falha(self, endpoint):
        n = self._falhas.get(endpoint, 0) + 1
        self._falhas[endpoint] = n
        if n >= FALHAS_PARA_ABRIR:
            self._aberto_ate[endpoint] = self._relogio() + CIRCUITO_ABERTO_S
            self._falhas[endpoint] = 0
            fontes.avisar(self.fonte.id, f"{self.fonte.nome}: {endpoint} falhou {n} vezes seguidas; "
                                         f"pausado por {CIRCUITO_ABERTO_S // 60} min.")

    def _robots_permite(self, url) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        cache = self._robots.get(base)
        if not cache or cache[0] <= self._relogio():
            rp = RobotFileParser()
            resp, status, _ = self._enviar("GET", base + "/robots.txt", "/robots.txt", None, None,
                                           {"User-Agent": USER_AGENT})
            if status in (401, 403) or status == 0 or status >= 500:
                rp.disallow_all = True      # sem como saber o que é permitido: não acessa
            elif status >= 400:
                rp.allow_all = True         # robots.txt inexistente: tudo permitido
            else:
                rp.parse(resp.text.splitlines())
            self._robots[base] = (self._relogio() + ROBOTS_TTL_S, rp)
            cache = self._robots[base]
        return cache[1].can_fetch(USER_AGENT, url)

    @staticmethod
    def _parece_bloqueio(resp) -> bool:
        if resp.status_code in (401, 403, 429):
            return True
        if "text/html" in resp.headers.get("Content-Type", ""):
            corpo = resp.text[:20000].lower()
            return any(m in corpo for m in MARCAS_CAPTCHA)
        return False

    @staticmethod
    def _resumo(resp) -> str:
        if resp is None:
            return "sem resposta"
        try:
            j = resp.json()
            if isinstance(j, dict):
                return str(j.get("message") or j.get("error") or j.get("code") or "")[:200]
        except ValueError:
            pass
        return (resp.text or "")[:200]
