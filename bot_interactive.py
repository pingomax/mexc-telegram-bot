import os
import logging
import telebot
from mexc_api import MexcAPI

# Configuração
TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("MEXC_API_KEY")
API_SECRET = os.getenv("MEXC_API_SECRET")

bot = telebot.TeleBot(TOKEN)
mexc = MexcAPI(API_KEY, API_SECRET)

logging.basicConfig(level=logging.INFO)

# Estado temporário para ordens
user_orders = {}

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(message.chat.id, "🚀 Bot MEXC conectado! Envie um sinal de trade.")

@bot.message_handler(func=lambda msg: "Trade Signal" in msg.text)
def handle_signal(message):
    chat_id = message.chat.id
    user_orders[chat_id] = {"signal": message.text}
    bot.send_message(chat_id, "💵 Quanto deseja investir em USDT?")

@bot.message_handler(func=lambda msg: msg.chat.id in user_orders and "usdt" not in user_orders[msg.chat.id])
def set_usdt(message):
    chat_id = message.chat.id
    try:
        amount = float(message.text)
        user_orders[chat_id]["usdt"] = amount
        bot.send_message(chat_id, "📈 Deseja operar alavancado? (responda com: não, 10, 30, 50 ou 100)")
    except:
        bot.send_message(chat_id, "❌ Valor inválido, digite novamente.")

@bot.message_handler(func=lambda msg: msg.chat.id in user_orders and "leverage" not in user_orders[msg.chat.id] and "usdt" in user_orders[msg.chat.id])
def set_leverage(message):
    chat_id = message.chat.id
    leverage = message.text.strip().lower()
    if leverage == "não":
        user_orders[chat_id]["leverage"] = 1
    elif leverage.isdigit() and int(leverage) in [10, 30, 50, 100]:
        user_orders[chat_id]["leverage"] = int(leverage)
    else:
        bot.send_message(chat_id, "❌ Opção inválida. Responda com: não, 10, 30, 50 ou 100")
        return

    signal = user_orders[chat_id]["signal"]
    usdt = user_orders[chat_id]["usdt"]
    lev = user_orders[chat_id]["leverage"]
    bot.send_message(chat_id, f"✅ Ordem configurada!
USDT: {usdt}
Alavancagem: {lev}x

Executando ordem...")
    
    # Aqui chamaria API da MEXC para abrir ordem
    mexc.place_order(signal, usdt, lev)

    del user_orders[chat_id]

bot.polling()
