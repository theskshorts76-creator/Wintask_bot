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

# Target group:
# Work From Home 100-300RS Earn
TARGET_CHAT_ID = -100431801671

# Daily statistics
daily_stats = {}


def get_today_key():
    return datetime.now(IST).strftime("%Y-%m-%d")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot is working!")


async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    await update.message.reply_text(
        f"🆔 Chat ID:\n`{chat_id}`",
        parse_mode="Markdown"
    )


async def member_joined(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # Sirf target group ko track karo
    if update.effective_chat.id != TARGET_CHAT_ID:
        return

    if not update.message or not update.message.new_chat_members:
        return

    today = get_today_key()
    key = (TARGET_CHAT_ID, today)

    if key not in daily_stats:
        daily_stats[key] = {
            "joins": 0,
            "leaves": 0
        }

    for member in update.message.new_chat_members:

        # Bot ko count nahi karna
        if member.id == context.bot.id:
            continue

        daily_stats[key]["joins"] += 1


async def member_left(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # Sirf target group ko track karo
    if update.effective_chat.id != TARGET_CHAT_ID:
        return

    if not update.message or not update.message.left_chat_member:
        return

    member = update.message.left_chat_member

    # Bot ko count nahi karna
    if member.id == context.bot.id:
        return

    today = get_today_key()
    key = (TARGET_CHAT_ID, today)

    if key not in daily_stats:
        daily_stats[key] = {
            "joins": 0,
            "leaves": 0
        }

    daily_stats[key]["leaves"] += 1


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.effective_user:
        return

    dashboard_chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # Sirf dashboard group ke admins ko reply
    try:
        member = await context.bot.get_chat_member(
            dashboard_chat_id,
            user_id
        )

        if member.status not in ["administrator", "creator"]:
            return

    except Exception:
        return

    # Target group ka current member count
    try:
        member_count = await context.bot.get_chat_member_count(
            TARGET_CHAT_ID
        )
    except Exception:
        await update.message.reply_text(
            "❌ Target group ka member count nahi mil raha.\n\n"
            "Check karo ki Wintask target group me Admin hai."
        )
        return

    today = get_today_key()
    key = (TARGET_CHAT_ID, today)

    joins = daily_stats.get(key, {}).get("joins", 0)
    leaves = daily_stats.get(key, {}).get("leaves", 0)

    await update.message.reply_text(
        f"📊 Group Stats\n\n"
        f"👥 Total members: {member_count}\n"
        f"📥 Today joins: {joins}\n"
        f"📤 Today leaves: {leaves}"
    )


# ==============================
# BOT SETUP
# ==============================

app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("id", get_id))
app.add_handler(CommandHandler("stats", stats))

# New members
app.add_handler(
    MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS,
        member_joined
    )
)

# Members leaving
app.add_handler(
    MessageHandler(
        filters.StatusUpdate.LEFT_CHAT_MEMBER,
        member_left
    )
)

print("🤖 Bot started...")

app.run_polling()
