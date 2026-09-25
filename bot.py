import os
from datetime import datetime, timedelta, timezone

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ChatMemberHandler,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")

# =========================================================
# TARGET GROUP
# Isi group ke members ke JOIN / LEAVE track honge
# =========================================================
TARGET_CHAT_ID = -100431801671

# IST timezone
IST = timezone(timedelta(hours=5, minutes=30))

# Daily statistics
daily_stats = {}


# =========================================================
# CHECK ADMIN
# =========================================================
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.effective_chat:
        return False

    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id,
            update.effective_user.id
        )

        return member.status in ["administrator", "creator"]

    except Exception:
        return False


# =========================================================
# START
# =========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update, context):
        return

    await update.message.reply_text(
        "✅ Bot is working!"
    )


# =========================================================
# TRACK TARGET GROUP MEMBERS
# =========================================================
async def track_member(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_member = update.chat_member

    if not chat_member:
        return

    # Sirf TARGET GROUP ko track karo
    if chat_member.chat.id != TARGET_CHAT_ID:
        return

    old_status = chat_member.old_chat_member.status
    new_status = chat_member.new_chat_member.status

    active_statuses = {
        "member",
        "administrator",
        "creator"
    }

    # JOIN
    joined = (
        old_status not in active_statuses
        and new_status in active_statuses
    )

    # LEAVE
    left = (
        old_status in active_statuses
        and new_status in {"left", "kicked"}
    )

    if not joined and not left:
        return

    today = datetime.now(IST).strftime("%Y-%m-%d")

    key = (TARGET_CHAT_ID, today)

    if key not in daily_stats:
        daily_stats[key] = {
            "joins": 0,
            "leaves": 0
        }

    if joined:
        daily_stats[key]["joins"] += 1

    if left:
        daily_stats[key]["leaves"] += 1


# =========================================================
# STATS
# =========================================================
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # Sirf admin ko reply
    if not await is_admin(update, context):
        return

    # Jis group me /stats bheja gaya hai,
    # result wahi dikhega.
    display_chat_id = update.effective_chat.id

    try:
        # TARGET GROUP ka member count
        member_count = await context.bot.get_chat_member_count(
            TARGET_CHAT_ID
        )

    except Exception:
        await update.message.reply_text(
            "❌ Target group ka member count nahi mil raha.\n\n"
            "Check karo ki bot target group me ADMIN hai."
        )
        return

    today = datetime.now(IST).strftime("%Y-%m-%d")
    key = (TARGET_CHAT_ID, today)

    joins = daily_stats.get(key, {}).get("joins", 0)
    leaves = daily_stats.get(key, {}).get("leaves", 0)

    await update.message.reply_text(
        "📊 Group Stats\n\n"
        f"👥 Target group members: {member_count}\n"
        f"📥 Today joins: {joins}\n"
        f"📤 Today leaves: {leaves}"
    )


# =========================================================
# BOT START
# =========================================================
app = (
    Application.builder()
    .token(BOT_TOKEN)
    .build()
)

app.add_handler(
    CommandHandler("start", start)
)

app.add_handler(
    CommandHandler("stats", stats)
)

app.add_handler(
    ChatMemberHandler(
        track_member,
        ChatMemberHandler.CHAT_MEMBER
    )
)

print("🤖 Bot started...")

app.run_polling()
