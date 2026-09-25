import os
from datetime import datetime, timezone, timedelta

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ChatMemberHandler,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")

IST = timezone(timedelta(hours=5, minutes=30))

daily_stats = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot is working!")


async def track_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_member = update.chat_member

    old_status = chat_member.old_chat_member.status
    new_status = chat_member.new_chat_member.status

    active_statuses = {"member", "administrator", "creator"}

    joined = (
        old_status not in active_statuses
        and new_status in active_statuses
    )

    left = (
        old_status in active_statuses
        and new_status in {"left", "kicked"}
    )

    if not joined and not left:
        return

    chat_id = chat_member.chat.id
    today = datetime.now(IST).strftime("%Y-%m-%d")

    key = (chat_id, today)

    if key not in daily_stats:
        daily_stats[key] = {"joins": 0, "leaves": 0}

    if joined:
        daily_stats[key]["joins"] += 1

    if left:
        daily_stats[key]["leaves"] += 1


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

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
app.add_handler(ChatMemberHandler(track_member, ChatMemberHandler.CHAT_MEMBER))

print("🤖 Bot started...")
app.run_polling()
