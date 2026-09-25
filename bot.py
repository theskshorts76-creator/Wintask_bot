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

# Target group jiska member count aur joins/leaves track karne hain
TARGET_CHAT_ID = -100431801671

# India time
IST = timezone(timedelta(hours=5, minutes=30))

# Daily statistics
daily_stats = {}


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check whether the person sending the command is an admin."""

    if not update.effective_chat or not update.effective_user:
        return False

    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id,
            update.effective_user.id
        )

        return member.status in ("administrator", "creator")

    except Exception:
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot is working!")


async def track_member(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    """Track joins/leaves ONLY from the target group."""

    chat_member = update.chat_member

    if not chat_member:
        return

    # Ignore every group except target group
    if chat_member.chat.id != TARGET_CHAT_ID:
        return

    old_status = chat_member.old_chat_member.status
    new_status = chat_member.new_chat_member.status

    active_statuses = {
        "member",
        "administrator",
        "creator"
    }

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

    today = datetime.now(IST).strftime("%Y-%m-%d")

    if today not in daily_stats:
        daily_stats[today] = {
            "joins": 0,
            "leaves": 0
        }

    if joined:
        daily_stats[today]["joins"] += 1

    if left:
        daily_stats[today]["leaves"] += 1


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # Sirf admin ko reply
    if not await is_admin(update, context):
        return

    today = datetime.now(IST).strftime("%Y-%m-%d")

    joins = daily_stats.get(today, {}).get("joins", 0)
    leaves = daily_stats.get(today, {}).get("leaves", 0)

    try:
        # IMPORTANT:
        # Member count target group ka liya ja raha hai
        member_count = await context.bot.get_chat_member_count(
            TARGET_CHAT_ID
        )

    except Exception as e:
        print("TARGET GROUP ERROR:", e)

        await update.message.reply_text(
            "❌ Target group ka member count nahi mil raha.\n\n"
            "Check karo ki:\n"
            "1️⃣ Bot target group me ADMIN hai\n"
            "2️⃣ Target group ID sahi hai\n\n"
            f"Target ID: {TARGET_CHAT_ID}"
        )
        return

    await update.message.reply_text(
        "📊 Group Stats\n\n"
        f"👥 Target group members: {member_count}\n"
        f"📥 Today joins: {joins}\n"
        f"📤 Today leaves: {leaves}"
    )


def main():

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

    # Target group ke join/leave events
    app.add_handler(
        ChatMemberHandler(
            track_member,
            ChatMemberHandler.CHAT_MEMBER
        )
    )

    print("🤖 Bot started...")

    app.run_polling()


if __name__ == "__main__":
    main()
