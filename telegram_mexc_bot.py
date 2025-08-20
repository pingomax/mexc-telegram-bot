"""
telegram_mexc_bot.py

Requisitos:
- Python 3.10+
- pip install python-telegram-bot==21.6 httpx==0.27.2 python-dotenv==1.0.1

Como usar:
1) Crie um bot no @BotFather e obtenha o TOKEN do Telegram.
2) Na MEXC, crie uma API Key com permissões SPOT_ACCOUNT_READ e SPOT_DEAL_WRITE. (Recomendo whitelistar IP.)
3) Crie um arquivo .env na mesma pasta com:
   TELEGRAM_TOKEN=xxxxxxxx:yyyyyyyyyyyy
   MEXC_API_KEY=seu_api_key
   MEXC_API_SECRET=seu_api_secret
   # Parâmetros padrão do usuário (podem ser mudados via /config no chat)
   DEFAULT_QUOTE_USDT=20            # valor fixo em USDT por operação
   DEFAULT_MAX_SLIPPAGE=0.004       # 0.4% de slippage máxima ao comprar
   DEFAULT_TP_MODE=bot_guard        # bot_guard | none
   DEFAULT_SL_MODE=bot_guard        # bot_guard | none

4) Rode: python telegram_mexc_bot.py

O que ele faz (MVP):
- Comando /config para ver/alterar parâmetros padrão do usuário.
- Quando recebe um texto de sinal no padrão abaixo, faz:
  * Lê par, entry, TP e SL
  * Calcula a quantidade a comprar usando DEFAULT_QUOTE_USDT
  * Coloca ordem de COMPRA (market by quote) via Spot V3
  * Liga um "guardião" local (bot_guard) que monitora preço e envia ordem MARKET de venda quando atingir TP ou SL (fail-safe caso a exchange não ofereça OCO/TP/SL nativo por API)

Formato do sinal suportado (exemplo):
"""
from __future__ import annotations

import asyncio
import hmac
import hashlib
import time
import re
import os
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

BASE_URL = "https://api.mexc.com"

SIGNAL_REGEX = re.compile(
    r"\$?(?P<coin>[A-Z0-9]+)\s*\n?.*?Position:\s*(?P<side>Long|Buy|Short|Sell).*?Pair:\s*(?P<pair>[A-Z0-9/:-]+)" \
    r".*?Entry Price:\s*(?P<entry>[0-9]*\.?[0-9]+)" \
    r".*?Take Profit:\s*(?P<tp>[0-9]*\.?[0-9]+)" \
    r".*?Stop Loss:\s*(?P<sl>[0-9]*\.?[0-9]+)",
    re.IGNORECASE | re.DOTALL,
)

@dataclass
class UserConfig:
    quote_usdt: float = 20.0
    max_slippage: float = 0.004  # 0.4%
    tp_mode: str = "bot_guard"   # or "none"
    sl_mode: str = "bot_guard"   # or "none"

    def to_lines(self):
        return [
            f"quote_usdt={self.quote_usdt}",
            f"max_slippage={self.max_slippage}",
            f"tp_mode={self.tp_mode}",
            f"sl_mode={self.sl_mode}",
        ]

# Em memória (para MVP). Em produção, use DB.
USER_CONFIGS: Dict[int, UserConfig] = {}
GUARDS: Dict[str, asyncio.Task] = {}

# --- util MEXC ---

def sign_params(secret: str, params: Dict[str, Any]) -> str:
    query = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()

async def mexc_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    api_key: str,
    api_secret: str,
    params: Optional[Dict[str, Any]] = None,
    signed: bool = False,
) -> Any:
    params = params.copy() if params else {}
    headers = {"X-MEXC-APIKEY": api_key}
    if signed:
        params["timestamp"] = int(time.time() * 1000)
        signature = sign_params(api_secret, params)
        params["signature"] = signature
    url = f"{BASE_URL}{path}"
    r = await client.request(method, url, params=params, headers=headers, timeout=20.0)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and data.get("code") not in (None, 0):
        raise httpx.HTTPError(f"MEXC error: {data}")
    return data

async def get_price(client: httpx.AsyncClient, symbol: str) -> float:
    data = await mexc_request(client, "GET", "/api/v3/ticker/price", api_key="", api_secret="", params={"symbol": symbol}, signed=False)
    return float(data["price"])

async def get_account_info(client: httpx.AsyncClient, api_key: str, api_secret: str) -> Dict[str, Any]:
    return await mexc_request(client, "GET", "/api/v3/account", api_key, api_secret, signed=True)

async def place_market_buy_by_quote(
    client: httpx.AsyncClient,
    api_key: str,
    api_secret: str,
    symbol: str,
    quote_usdt: float,
) -> Dict[str, Any]:
    params = {
        "symbol": symbol,
        "side": "BUY",
        "type": "MARKET",
        "quoteOrderQty": f"{quote_usdt:.8f}",
    }
    return await mexc_request(client, "POST", "/api/v3/order", api_key, api_secret, params=params, signed=True)

async def place_market_sell_all(
    client: httpx.AsyncClient,
    api_key: str,
    api_secret: str,
    symbol: str,
) -> Dict[str, Any]:
    # Descobre saldo do ativo base e vende tudo a mercado
    base = symbol.replace("USDT", "")
    info = await get_account_info(client, api_key, api_secret)
    qty = 0.0
    for b in info.get("balances", []):
        if b.get("asset") == base:
            qty = float(b.get("free", 0))
            break
    if qty <= 0:
        raise httpx.HTTPError("Sem saldo para vender.")
    params = {
        "symbol": symbol,
        "side": "SELL",
        "type": "MARKET",
        "quantity": f"{qty:.8f}",
    }
    return await mexc_request(client, "POST", "/api/v3/order", api_key, api_secret, params=params, signed=True)

# --- Guardião de TP/SL local (bot_guard) ---
async def bot_guard_monitor(
    chat_id: int,
    symbol: str,
    take_profit: float,
    stop_loss: float,
    api_key: str,
    api_secret: str,
    max_runtime_sec: int = 2 * 60 * 60,  # 2h de guarda
    poll_sec: float = 2.0,
):
    async with httpx.AsyncClient() as client:
        start = time.time()
        while time.time() - start < max_runtime_sec:
            try:
                price = await get_price(client, symbol)
                if price >= take_profit:
                    await place_market_sell_all(client, api_key, api_secret, symbol)
                    print(f"[GUARD] TP atingido {price} >= {take_profit}, vendi mercado.")
                    return
                if price <= stop_loss:
                    await place_market_sell_all(client, api_key, api_secret, symbol)
                    print(f"[GUARD] SL atingido {price} <= {stop_loss}, vendi mercado.")
                    return
            except Exception as e:
                print("[GUARD] erro:", e)
            await asyncio.sleep(poll_sec)
        print("[GUARD] tempo esgotado, finalizando sem vender.")

# --- Telegram ---

def get_user_cfg(user_id: int) -> UserConfig:
    return USER_CONFIGS.setdefault(user_id, UserConfig(
        quote_usdt=float(os.getenv("DEFAULT_QUOTE_USDT", 20.0)),
        max_slippage=float(os.getenv("DEFAULT_MAX_SLIPPAGE", 0.004)),
        tp_mode=os.getenv("DEFAULT_TP_MODE", "bot_guard"),
        sl_mode=os.getenv("DEFAULT_SL_MODE", "bot_guard"),
    ))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = get_user_cfg(update.effective_user.id)
    await update.message.reply_text(
        "Bem-vindo! Envie um sinal no formato do exemplo que eu executo.\n" \
        "Use /config para ver ou alterar seus padrões.\n\n" \
        + "\n".join(cfg.to_lines())
    )

async def config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = get_user_cfg(update.effective_user.id)
    args = context.args
    if not args:
        await update.message.reply_text("Config atual:\n" + "\n".join(cfg.to_lines()))
        return
    # Ex: /config quote_usdt=50 max_slippage=0.005
    for a in args:
        if "=" in a:
            k, v = a.split("=", 1)
            try:
                if k == "quote_usdt":
                    cfg.quote_usdt = float(v)
                elif k == "max_slippage":
                    cfg.max_slippage = float(v)
                elif k == "tp_mode":
                    cfg.tp_mode = v
                elif k == "sl_mode":
                    cfg.sl_mode = v
            except Exception:
                pass
    await update.message.reply_text("Config atualizada:\n" + "\n".join(cfg.to_lines()))

async def handle_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    m = SIGNAL_REGEX.search(text)
    if not m:
        await update.message.reply_text("Não reconheci o sinal. Envie no formato padrão com Entry/TP/SL.")
        return

    side = m.group("side").upper()
    pair = m.group("pair").upper().replace(":", "/").replace("-", "/")
    # Normaliza para SYMBOL tipo PLUMEUSDT
    symbol = pair.replace("/", "")
    entry = float(m.group("entry"))
    take_profit = float(m.group("tp"))
    stop_loss = float(m.group("sl"))

    user_id = update.effective_user.id
    cfg = get_user_cfg(user_id)

    load_dotenv()
    api_key = os.getenv("MEXC_API_KEY", "")
    api_secret = os.getenv("MEXC_API_SECRET", "")
    if not api_key or not api_secret:
        await update.message.reply_text("API Key/Secret não configurados no .env")
        return

    if side not in ("LONG", "BUY"):
        await update.message.reply_text("Este MVP só executa compras (Long/Buy) spot.")
        return

    # Compra a mercado por valor em USDT
    async with httpx.AsyncClient() as client:
        try:
            last = await get_price(client, symbol)
        except Exception as e:
            await update.message.reply_text(f"Erro ao obter preço de {symbol}: {e}")
            return

        # Checa slippage vs entry
        if abs(last - entry) / entry > cfg.max_slippage:
            await update.message.reply_text(
                f"Preço atual {last:.8f} distante do entry {entry:.8f} (> {cfg.max_slippage*100:.2f}% ). Abortando."
            )
            return

        try:
            order = await place_market_buy_by_quote(client, api_key, api_secret, symbol, cfg.quote_usdt)
        except Exception as e:
            await update.message.reply_text(f"Falha ao comprar {symbol}: {e}")
            return

    msg = [
        f"\u2705 COMPRA executada em {symbol}",
        f"Quote USDT: {cfg.quote_usdt}",
        f"TP: {take_profit} | SL: {stop_loss}",
    ]
    await update.message.reply_text("\n".join(msg))

    # Inicia guardião TP/SL se habilitado
    guard_key = f"{user_id}:{symbol}"
    if cfg.tp_mode == "bot_guard" or cfg.sl_mode == "bot_guard":
        if task := GUARDS.get(guard_key):
            task.cancel()
        GUARDS[guard_key] = asyncio.create_task(
            bot_guard_monitor(user_id, symbol, take_profit, stop_loss, api_key, api_secret)
        )
        await update.message.reply_text("Guardião TP/SL ativado (venda a mercado em disparo).")

async def main():
    load_dotenv()
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_TOKEN ausente no .env")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("config", config))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_signal))

    print("Bot rodando...")
    await app.run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
