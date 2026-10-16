# Como adicionar um marketplace

Uma fonte nova é um arquivo em `fontes/`, mais o padrão de link em `dedup.py` e a conversão de afiliado
em `affiliate_helper.py`. O núcleo (buscador, radar, piloto, publicação) não muda.

## 0. Escolha o tipo de acesso (nesta ordem)

1. **API oficial de afiliados** da loja (ex.: Amazon Creators/PA-API, Shopee Affiliate Open API,
   AliExpress Affiliate API, Magalu Parceiro). `tipo = "api_oficial"`.
2. **Feed ou API pública** documentada (XML/JSON de ofertas). `tipo = "api_oficial"`.
3. **Scraping de páginas públicas**, só se o `robots.txt` permitir e os termos de uso não proibirem.
   `tipo = "scraping"`.

Regras que valem para qualquer tipo (o `ClienteHTTP` já aplica, não contorne):
- toda requisição passa por `self.http` (fontes/http.py), nunca por `requests` direto;
- proibido resolver captcha, rotacionar proxy/IP, falsificar navegador ou fingerprint, ignorar 403/429;
- bloqueio (401/403, captcha, 429 em scraping) pausa a fonte e avisa o admin;
- credenciais ficam na tabela `config`, preenchidas pela GUI; nunca no código nem em log.

## 1. Crie `fontes/<loja>.py`

```python
from fontes.base import Busca, Fonte, ProdutoEncontrado

class MinhaLoja(Fonte):
    id = "mgl"                 # o MESMO prefixo usado em dedup.PADROES
    nome = "Magalu"
    loja = "magalu"            # chave em affiliate_helper.DOMINIOS
    tipo = "api_oficial"       # ou "scraping"
    req_por_minuto = 20        # o limite documentado pela loja (ou menor)
    intervalo_min_padrao = 60

    def buscar(self, busca: Busca) -> list[ProdutoEncontrado]:
        dados = self.http.get("https://api.loja/ofertas", "/ofertas",
                              params={"q": busca.valor}, cache_ttl=300)
        ...  # monte ProdutoEncontrado; a chave sai de dedup.chave_produto(url)

    def testar(self) -> dict:
        ...  # db.liberar_endpoints(self.id); uma chamada por endpoint
        return {"ok": True, "endpoints": {"/ofertas": "ok"}, "mensagem": "Conectado."}
```

- `endpoint` (2º argumento do `http.get`) é o **modelo** do caminho (`/produtos/{id}`), não a URL real:
  é por ele que o bloqueio, o circuit breaker e o log em `api_chamadas` funcionam.
- `preco_original` só quando a loja informa um preço "de" real e maior que o atual.
- `chave` precisa bater com `dedup.chave_produto()` do link do mesmo produto postado num canal.

## 2. Registre

Em `fontes/__init__.py`, função `registro()`: importe a classe e inclua na tupla.

## 3. Link do produto e afiliado

- `dedup.py` → `PADROES`: `(prefixo, regex do ID na URL final)`. Encurtadores da loja em `ENCURTADORES`.
- `affiliate_helper.py` → `DOMINIOS` (domínios e encurtadores) e `converter_url()` (como gerar o seu link).
- `radar.py` → `LOJAS`: nome exibido para o prefixo.

## 4. Teste sem rede

- Salve respostas reais de exemplo (sem dados pessoais nem tokens) em `tests/fixtures/<loja>_*.json`
  (ou `.html` para scraping).
- Em `tests/test_fontes.py`, use a `Sessao` falsa: confira a chave igual à de `dedup.chave_produto()`,
  o preço, o `preco_original` e o comportamento em 403/429.
- `python -m pytest tests -q` precisa passar.
