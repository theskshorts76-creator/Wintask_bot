import os
from datetime import datetime, timezone, timedelta

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")

# India Standard Time
IST = timezone(timedelta(hours=5, minutes=30))

# Daily stats memory
daily_stats = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot is working!")


async def member_joined(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return

    chat_id = update.effective_chat.id
    today = datetime.now(IST).strftime("%Y-%m-%d")
    key = (chat_id, today)

    if key not in daily_stats:
        daily_stats[key] = {"joins": 0, "leaves": 0}

    bot_id = context.bot.id

    for member in update.message.new_chat_members:
        # Bot khud join ho to count nahi karna
        if member.id != bot_id:
            daily_stats[key]["joins"] += 1


async def member_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.left_chat_member:
        return

    chat_id = update.effective_chat.id
    today = datetime.now(IST).strftime("%Y-%m-%d")
    key = (chat_id, today)

    if key not in daily_stats:
        daily_stats[key] = {"joins": 0, "leaves": 0}

    member = update.message.left_chat_member

    # Bot khud leave ho to count nahi karna
    if member.id != context.bot.id:
        daily_stats[key]["leaves"] += 1


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    # Current total members
    member_count = await context.bot.get_chat_member_count(chat_id)

    today = datetime.now(IST).strftime("%Y-%m-%d")
    key = (chat_id, today)

    joins = daily_stats.get(key, {}).get("joins", 0)
    leaves = daily_stats.get(key, {}).get("leaves", 0)

    await update.message.reply_text(
        f"📊 Group Stats\n\n"
        f"👥 Total members: {member_count}\n"
        f"📥 Today joins: {joins}\n"
        f"📤 Today leaves: {leaves}"
    )


app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stats", stats))

# Join/Leave messages track karna
app.add_handler(
    MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, member_joined)
)

app.add_handler(
    MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, member_left)
)

print("🤖 Bot started...")

app.run_polling()
