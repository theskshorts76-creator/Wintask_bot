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

# =========================================================
# TARGET GROUP
# Is group ka member count aur joins/leaves track honge
# =========================================================

TARGET_CHAT_ID = -100431801671

# India Standard Time
IST = timezone(timedelta(hours=5, minutes=30))

# Daily statistics
daily_stats = {}


# =========================================================
# ADMIN CHECK
# =========================================================

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.effective_chat or not update.effective_user:
        return False

    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id,
            update.effective_user.id
        )

        return member.status in ("administrator", "creator")

    except Exception as e:
        print("ADMIN CHECK ERROR:", repr(e))
        return False


# =========================================================
# START COMMAND
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
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

    # Sirf TARGET group ko track karo
    if chat_member.chat.id != TARGET_CHAT_ID:
        return

    old_status = chat_member.old_chat_member.status
    new_status = chat_member.new_chat_member.status

    active_statuses = {
        "member",
        "administrator",
        "creator"
    }

    # New member joined
    joined = (
        old_status not in active_statuses
        and new_status in active_statuses
    )

    # Member left/kicked
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
        print("TARGET GROUP JOIN")

    if left:
        daily_stats[today]["leaves"] += 1
        print("TARGET GROUP LEAVE")


# =========================================================
# STATS COMMAND
# =========================================================

async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    # Sirf admin ko reply
    admin = await is_admin(update, context)

    if not admin:
        # Non-admin ko koi reply nahi
        return

    today = datetime.now(IST).strftime("%Y-%m-%d")

    joins = daily_stats.get(today, {}).get(
        "joins", 0
    )

    leaves = daily_stats.get(today, {}).get(
        "leaves", 0
    )

    # =====================================================
    # TARGET GROUP MEMBER COUNT
    # =====================================================

    try:

        # Pehle target group ko access karke check karo
        target_chat = await context.bot.get_chat(
            TARGET_CHAT_ID
        )

        print(
            "TARGET GROUP FOUND:",
            target_chat.title,
            target_chat.id
        )

        # Target group ka member count
        member_count = await context.bot.get_chat_member_count(
            TARGET_CHAT_ID
        )

        print(
            "TARGET MEMBER COUNT:",
            member_count
        )

    except Exception as e:

        print(
            "TARGET GROUP ERROR:",
            repr(e)
        )

        await update.message.reply_text(
            "❌ Target group access error!\n\n"
            f"Error: {type(e).__name__}\n"
            f"Details: {e}\n\n"
            f"Target ID: {TARGET_CHAT_ID}"
        )

        return

    # =====================================================
    # FINAL STATS
    # =====================================================

    await update.message.reply_text(
        "📊 Group Stats\n\n"
        f"👥 Target group members: {member_count}\n"
        f"📥 Today joins: {joins}\n"
        f"📤 Today leaves: {leaves}"
    )


# =========================================================
# MAIN
# =========================================================

def main():

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # /start
    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    # /stats
    app.add_handler(
        CommandHandler(
            "stats",
            stats
        )
    )

    # Target group join/leave tracking
    app.add_handler(
        ChatMemberHandler(
            track_member,
            ChatMemberHandler.CHAT_MEMBER
        )
    )

    print("🤖 Bot started...")

    app.run_polling()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
