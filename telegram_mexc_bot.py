from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from mexc_api import MexcFuturesAPI

import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MEXC_API_KEY = os.getenv("MEXC_API_KEY")
MEXC_API_SECRET = os.getenv("MEXC_API_SECRET")

mexc = MexcFuturesAPI(MEXC_API_KEY, MEXC_API_SECRET)

# Armazena contexto da ordem para cada usuário
user_sessions = {}

async def start_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    signal = context.args
    pair = signal[0] if signal else "PLUME/USDT"
    user_sessions[update.effective_user.id] = {"pair": pair}

    await update.message.reply_text(
        f"💎 Sinal detectado para {pair}\n"
        "Quanto deseja investir em USDT?"
    )

async def set_usdt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_sessions:
        await update.message.reply_text("Por favor, envie um sinal primeiro.")
        return
    
    try:
        amount = float(update.message.text)
        user_sessions[user_id]["amount"] = amount
    except:
        await update.message.reply_text("Valor inválido. Digite um número válido em USDT.")
        return

    keyboard = [
        [InlineKeyboardButton("Sem alavancagem", callback_data="x1")],
        [InlineKeyboardButton("10x", callback_data="x10")],
        [InlineKeyboardButton("30x", callback_data="x30")],
        [InlineKeyboardButton("50x", callback_data="x50")],
        [InlineKeyboardButton("100x", callback_data="x100")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Escolha a alavancagem:", reply_markup=reply_markup)

async def set_leverage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    leverage = int(query.data.replace("x", ""))
    user_sessions[user_id]["leverage"] = leverage

    session = user_sessions[user_id]
    pair = session["pair"]
    amount = session["amount"]

    # Configura alavancagem e executa ordem
    mexc.set_leverage(symbol=pair, leverage=leverage)
    mexc.open_long(symbol=pair, usdt_amount=amount, leverage=leverage)

    await query.edit_message_text(
        f"✅ Ordem executada:\n"
        f"Par: {pair}\n"
        f"Investimento: {amount} USDT\n"
        f"Alavancagem: {leverage}x"
    )

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("trade", start_trade))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, set_usdt))
    app.add_handler(CallbackQueryHandler(set_leverage))
    app.run_polling()

if __name__ == "__main__":
    main()
