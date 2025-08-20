Bot de Telegram para executar sinais na MEXC (Spot V3)

Este projeto cria um bot do Telegram que lê sinais de trade no chat e executa ordens Spot na MEXC.
Ele permite configurar tamanho da ordem em USDT, tolerância de slippage e ativa um "guardião" que vende a mercado quando o preço atinge TP/SL.

Funcionalidades

Parser de sinais no formato:

"Trade Signal: $COIN ... Position: Long (Buy) | Pair: COIN/USDT ... Entry Price: X ... Take Profit: Y ... Stop Loss: Z".

Compra Spot por valor em USDT (MARKET), com fallback para LIMIT IOC quando MARKET não for suportado pelo par.

Guardião TP/SL (opcional) que monitora o preço e vende a mercado ao disparar.

Configurações por usuário via comando /config.

Persistência simples de configurações por usuário em ./data.

Avisos importantes

Nem todos os pares na MEXC são tradáveis via API e nem todos aceitam ordens MARKET. Para esses casos, o bot usa LIMIT IOC como fallback.

Sempre use API Keys com permissão APENAS de trading (sem saque) e whitelist de IP quando possível.

Teste em pequena escala antes de operar com valores maiores.

Requisitos

Python 3.11+

Conta na MEXC com API Key e Secret (Spot trading habilitado)

Bot do Telegram (crie com @BotFather e obtenha o token)

Configuração

Clone este repositório.

Copie o arquivo .env.example para .env e preencha:

cp .env.example .env
# edite .env e coloque seus valores reais

Instale dependências (se for rodar sem Docker):
pip install -r requirements.txt

Rode o bot localmente:
python seu_arquivo_principal.py


Substitua "seu_arquivo_principal.py" pelo nome do arquivo principal do seu projeto (ex.: telegram_mexc_bot.py).

Comandos no Telegram

/start: mensagem de boas-vindas.

/config: ajustar parâmetros, por exemplo:

/config quote_usdt=50 max_slippage=0.005 tp_mode=bot_guard sl_mode=bot_guard

Envie um sinal no formato suportado para executar:

💎 Trade Signal: $PLUME
📊 Position: Long (Buy) | Pair: PLUME/USDT
✅ Entry Price: 0.08153
🎯 Take Profit: 0.10770
❌ Stop Loss: 0.07166

Logs e dados

Configurações por usuário: ./data

Logs: ./logs

Deploy com Docker (recomendado para rodar 24/7)

Pré-requisitos: Docker e Docker Compose instalados.

Arquivos necessários:

Dockerfile

docker-compose.yml

requirements.txt

.env (com suas chaves)

Dockerfile sugerido:

FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "seu_arquivo_principal.py"]


docker-compose.yml sugerido:

version: '3.9'
services:
  mexc-bot:
    build: .
    container_name: mexc-bot
    restart: always
    env_file:
      - .env
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs


Subir o serviço:

docker compose up -d --build


Ver logs:

docker compose logs -f

Deploy no Proxmox (via LXC + Docker)

Crie um container LXC (Debian 12/Ubuntu 22.04), 1 vCPU, 1GB RAM, 5GB disco, rede com DHCP.

Dentro do container, instale Docker e Compose:

apt update && apt upgrade -y
apt install -y curl git python3 python3-pip
curl -fsSL https://get.docker.com | sh
apt install -y docker-compose-plugin


Clone o repositório no container, copie .env.example para .env e preencha valores.

Rode docker compose up -d --build na pasta do projeto.

Com restart: always, o bot reinicia após queda e sobe com o host.

Segurança

Nunca comite .env no Git; use .env.example como referência.

Restrinja sua API Key (apenas trading, sem withdrawal) e use IP whitelist.

Monitore os logs e status do container.

Troubleshooting

"Formato de sinal não reconhecido": confira o padrão do texto. O parser aceita Long/Buy e par COIN/USDT.

"API Key/Secret não configurados": preencha .env e reinicie o serviço.

Slippage muito alta: ajuste max_slippage ou aguarde o preço aproximar do entry.

Par não tradável ou sem MARKET: o bot tenta fallback LIMIT IOC; em mercados de baixa liquidez podem ocorrer partial fills.

Licença

Defina a licença que preferir (MIT, Apache-2.0, etc.) e adicione um arquivo LICENSE.