import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot is working!")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    member_count = await context.bot.get_chat_member_count(chat_id)

    await update.message.reply_text(
        f"📊 Group Stats\n\n"
        f"👥 Total members: {member_count}\n"
        f"📥 Today joins: 0\n"
        f"📤 Today leaves: 0"
    )


app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stats", stats))

print("🤖 Bot started...")
app.run_polling()
