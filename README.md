# Repasse Automático Telegram

Ferramenta desktop para automatizar o repasse de mensagens entre grupos e canais do Telegram, inspirada no CAT - Clonador Automático Telegram.

## Funcionalidades

- **Múltiplas contas** — Gerencie várias contas Telegram simultaneamente
- **Repasses configuráveis** — Origem → múltiplos destinos
- **Filtros de mídia** — Bloqueie links, imagens, vídeos, áudios
- **Filtros por palavras** — Permita ou bloqueie mensagens por termos
- **Substituições de texto** — Troque links, textos, tags de afiliado
- **Delay configurável** — Delay entre repasses para evitar ban
- **Limite diário** — Limite de repasses por dia
- **Horário de funcionamento** — Defina o intervalo de horas
- **Integrações de afiliados** — Amazon, Mercado Livre, Shopee, AliExpress, Magalu
- **Relatórios** — Histórico de todos os repasses com status
- **Radar de Preços** — Registra o preço de cada oferta vista nos canais de origem e mostra os menores preços do dia (com publicação em 1 clique, também pelo painel do bot)
- **Bot + painel inline** — Publicação pelo bot oficial e controle pelo chat privado (/start)
- **Interface gráfica** — GUI desktop moderna com CustomTkinter

## Requisitos

- Python 3.10 ou superior
- Conta Telegram com API ID e API Hash (gratuito em my.telegram.org)

## Executável (sem instalar nada)

Cada push em `main` ou `etapa*/**` gera o `repasse_telegram.exe` no GitHub Actions:
**Actions → execução mais recente → Artifacts**. Não precisa de Python nem de `pip` na máquina.

## Modo headless (servidor / 24h)

```bash
repasse_telegram.exe --headless      # ou: python main.py --headless
```

Roda só o motor (repasses + agendador de nichos), sem janela. As contas precisam ter sido
conectadas antes pela GUI (a sessão fica salva em `data/repasse.db`). Sem console, o log vai
para `data/app.log`.

## Instalação (desenvolvimento)

```bash
# 1. Clone ou baixe o projeto
cd repasse_telegram

# 2. Crie um ambiente virtual (recomendado)
python -m venv venv
source venv/bin/activate      # Linux/Mac
venv\Scripts\activate         # Windows

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Execute
python main.py
```

## Configuração Inicial

1. Acesse [my.telegram.org](https://my.telegram.org)
2. Faça login → **API development tools**
3. Crie um aplicativo e copie o **API ID** e **API Hash**
4. No app, vá em **Configurações → API Telegram** e cole as credenciais
5. Em **Contas**, adicione seu número de telefone e clique em **Conectar**
6. Insira o código recebido pelo Telegram

## Como criar um Repasse

1. Vá em **Repasses** → **+ Adicionar**
2. Defina o nome da tarefa
3. Selecione a conta e clique em **Carregar Grupos**
4. Escolha o **Grupo de Origem** e adicione os **Grupos de Destino**
5. Configure filtros e substituições se necessário
6. **Salvar**
7. Ative o toggle na lista de repasses

## Estrutura do Projeto

```
repasse_telegram/
├── main.py                  # Ponto de entrada
├── database.py              # Camada de dados (SQLite)
├── telegram_manager.py      # Gerenciador Telethon (async)
├── requirements.txt
├── data/
│   └── repasse.db           # Banco de dados (criado automaticamente)
└── ui/
    ├── main_window.py       # Janela principal com sidebar
    ├── contas_frame.py      # Aba de contas
    ├── repasses_frame.py    # Aba de repasses
    ├── repasse_dialog.py    # Diálogo criar/editar repasse
    ├── integracoes_frame.py # Aba de integrações
    └── configuracoes_frame.py # Aba de configurações
```

## Aviso Legal

Esta ferramenta utiliza a API de usuário do Telegram (Telethon), que é diferente da Bot API.
O uso da API de usuário para automação pode violar os Termos de Serviço do Telegram.
Use com responsabilidade e moderação para evitar banimentos de conta.

## Próximos Passos (roadmap)

- [ ] Suporte a Bot API além de contas de usuário
- [ ] Inserção automática de tags de afiliado nos links
- [ ] Clonagem de canais/grupos
- [ ] Exportar/importar configurações
- [ ] Sistema de proxy
- [ ] Notificações desktop
