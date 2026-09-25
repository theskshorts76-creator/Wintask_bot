import os
from datetime import datetime
from collections import defaultdict

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ChatMemberHandler,
    ContextTypes,
)

# =========================================================
# SETTINGS
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

# TARGET GROUP CHAT ID
TARGET_CHAT_ID = -1004318016710


# =========================================================
# DATA
# =========================================================

daily_joins = defaultdict(int)
daily_leaves = defaultdict(int)

total_joins = 0
total_leaves = 0


# =========================================================
# TIME
# =========================================================

def today():
    return datetime.now().strftime("%Y-%m-%d")


# =========================================================
# CHECK ADMIN
# =========================================================

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.effective_chat or not update.effective_user:
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

    await update.message.reply_text(
        "✅ Bot is working!\n\n"
        "Commands:\n"
        "/id - Current chat ID\n"
        "/stats - Target group statistics"
    )


# =========================================================
# ID COMMAND
# =========================================================

async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.effective_chat:
        return

    chat = update.effective_chat

    chat_name = chat.title or chat.first_name or "Private Chat"

    await update.message.reply_text(
        "🆔 CHAT INFORMATION\n\n"
        f"📌 Name: {chat_name}\n"
        f"💬 Type: {chat.type}\n"
        f"🆔 Chat ID: {chat.id}"
    )


# =========================================================
# MEMBER JOIN / LEAVE TRACKING
# =========================================================

async def member_update(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    global total_joins
    global total_leaves

    chat_member = update.chat_member

    if not chat_member:
        return

    # Only target group
    if chat_member.chat.id != TARGET_CHAT_ID:
        return

    old_status = chat_member.old_chat_member.status
    new_status = chat_member.new_chat_member.status

    # JOIN
    if (
        new_status in ["member", "administrator"]
        and old_status in ["left", "kicked"]
    ):
        total_joins += 1
        daily_joins[today()] += 1

        print(
            f"JOIN: {chat_member.new_chat_member.user.id}"
        )

    # LEAVE
    elif (
        new_status in ["left", "kicked"]
        and old_status in ["member", "administrator"]
    ):
        total_leaves += 1
        daily_leaves[today()] += 1

        print(
            f"LEAVE: {chat_member.old_chat_member.user.id}"
        )


# =========================================================
# STATS COMMAND
# =========================================================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # Only admin can use /stats
    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ Sirf group admin /stats command use kar sakta hai."
        )

        return

    command_chat_id = update.effective_chat.id

    # =====================================================
    # CHECK TARGET GROUP
    # =====================================================

    try:

        target_chat = await context.bot.get_chat(
            TARGET_CHAT_ID
        )

    except Exception as e:

        await update.message.reply_text(
            "❌ Target group access error!\n\n"
            f"Error: {type(e).__name__}\n"
            f"Details: {e}\n\n"
            f"Target ID: {TARGET_CHAT_ID}\n\n"
            "⚠️ Bot ko target group me add karke ADMIN banao."
        )

        return

    # =====================================================
    # CHECK BOT ADMIN
    # =====================================================

    try:

        bot_member = await context.bot.get_chat_member(
            TARGET_CHAT_ID,
            context.bot.id
        )

        if bot_member.status not in [
            "administrator",
            "creator"
        ]:

            await update.message.reply_text(
                "❌ Bot target group me ADMIN nahi hai.\n\n"
                "Target group me Wintask ko ADMIN banao.\n\n"
                f"Target ID: {TARGET_CHAT_ID}"
            )

            return

    except Exception as e:

        await update.message.reply_text(
            "❌ Target group access error!\n\n"
            f"Error: {type(e).__name__}\n"
            f"Details: {e}\n\n"
            f"Target ID: {TARGET_CHAT_ID}"
        )

        return

    # =====================================================
    # TODAY DATA
    # =====================================================

    d = today()

    joins_today = daily_joins[d]
    leaves_today = daily_leaves[d]

    # =====================================================
    # RESULT
    # =====================================================

    text = (
        "📊 TARGET GROUP STATS\n\n"
        f"🎯 Target Group:\n"
        f"{target_chat.title}\n\n"
        f"🆔 Target ID:\n"
        f"{TARGET_CHAT_ID}\n\n"
        f"📥 Today's joins: {joins_today}\n"
        f"📤 Today's leaves: {leaves_today}\n\n"
        f"📈 Total tracked joins: {total_joins}\n"
        f"📉 Total tracked leaves: {total_leaves}"
    )

    await context.bot.send_message(
        chat_id=command_chat_id,
        text=text
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    print("ERROR:", context.error)


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN variable missing!"
        )

    print("🤖 Bot started...")

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands
    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("id", chat_id)
    )

    app.add_handler(
        CommandHandler("stats", stats)
    )

    # Member tracking
    app.add_handler(
        ChatMemberHandler(
            member_update,
            ChatMemberHandler.CHAT_MEMBER
        )
    )

    # Error handler
    app.add_error_handler(error_handler)

    # Start bot
    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
