import os
import json
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update, ChatPermissions
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
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "0"))

IST = ZoneInfo("Asia/Kolkata")
DATA_FILE = "bot2_data.json"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# DEFAULT DATA
# =========================================================

DEFAULT_DATA = {
    "welcome_enabled": True,
    "welcome_message": (
        "👋 Welcome {mention}!\n\n"
        "🎉 Welcome to our group.\n"
        "Please follow the group rules."
    ),
    "chat_on": None,
    "chat_off": None,
    "notices": []
}


# =========================================================
# DATA FUNCTIONS
# =========================================================

def load_data():
    if not os.path.exists(DATA_FILE):
        return DEFAULT_DATA.copy()

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        for key, value in DEFAULT_DATA.items():
            if key not in data:
                data[key] = value

        return data

    except Exception:
        return DEFAULT_DATA.copy()


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


data = load_data()


# =========================================================
# TIME
# =========================================================

def ist_now():
    return datetime.now(IST)


def current_time():
    return ist_now().strftime("%H:%M")


# =========================================================
# ADMIN CHECK
# =========================================================

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.effective_chat:
        return False

    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id,
            update.effective_user.id
        )

        return member.status in ("administrator", "creator")

    except Exception as e:
        logger.error("Admin check error: %s", e)
        return False


async def admin_only(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        if update.message:
            await update.message.reply_text(
                "❌ Sirf group admins ye command use kar sakte hain."
            )
        return False

    return True


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context):
        return

    await update.message.reply_text(
        "🤖 Bot 2 Active!\n\n"
        "👋 Welcome Messages\n"
        "🟢 Scheduled Chat ON\n"
        "🔴 Scheduled Chat OFF\n"
        "📢 Automatic Notices\n\n"
        "⚙️ Commands ke liye /settings use karein."
    )


# =========================================================
# ID
# =========================================================

async def show_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context):
        return

    chat = update.effective_chat

    await update.message.reply_text(
        f"🆔 Chat ID:\n`{chat.id}`",
        parse_mode="Markdown"
    )


# =========================================================
# SETTINGS
# =========================================================

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context):
        return

    welcome_status = "🟢 ON" if data["welcome_enabled"] else "🔴 OFF"

    chat_on = data["chat_on"] or "Not set"
    chat_off = data["chat_off"] or "Not set"

    notices_count = len(data["notices"])

    await update.message.reply_text(
        "⚙️ BOT SETTINGS\n\n"
        f"👋 Welcome: {welcome_status}\n"
        f"🟢 Chat ON: {chat_on} IST\n"
        f"🔴 Chat OFF: {chat_off} IST\n"
        f"📢 Notices: {notices_count}\n\n"
        "📌 Commands:\n\n"
        "/welcome on\n"
        "/welcome off\n"
        "/setwelcome MESSAGE\n"
        "/seton HH:MM\n"
        "/setoff HH:MM\n"
        "/notice HH:MM MESSAGE\n"
        "/notices\n"
        "/delnotice NUMBER\n"
        "/id"
    )


# =========================================================
# WELCOME ON / OFF
# =========================================================

async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Use:\n"
            "/welcome on\n"
            "/welcome off"
        )
        return

    option = context.args[0].lower()

    if option == "on":
        data["welcome_enabled"] = True
        save_data(data)

        await update.message.reply_text(
            "👋 Welcome message: 🟢 ON"
        )

    elif option == "off":
        data["welcome_enabled"] = False
        save_data(data)

        await update.message.reply_text(
            "👋 Welcome message: 🔴 OFF"
        )

    else:
        await update.message.reply_text(
            "❌ Sirf `on` ya `off` use karein."
        )


# =========================================================
# SET WELCOME MESSAGE
# =========================================================

async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Use:\n"
            "/setwelcome Welcome {mention} 🎉"
        )
        return

    message = " ".join(context.args)

    data["welcome_message"] = message
    save_data(data)

    await update.message.reply_text(
        "✅ Welcome message save ho gaya."
    )


# =========================================================
# NEW MEMBER WELCOME
# =========================================================

async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.chat_member:
        return

    chat = update.chat_member.chat

    if GROUP_CHAT_ID and chat.id != GROUP_CHAT_ID:
        return

    old_status = update.chat_member.old_chat_member.status
    new_status = update.chat_member.new_chat_member.status

    joined = (
        new_status in ("member", "administrator")
        and old_status in ("left", "kicked")
    )

    if not joined:
        return

    if not data["welcome_enabled"]:
        return

    user = update.chat_member.new_chat_member.user

    mention = user.mention_html()

    message = data["welcome_message"].replace(
        "{mention}",
        mention
    )

    try:
        await context.bot.send_message(
            chat_id=chat.id,
            text=message,
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error("Welcome error: %s", e)


# =========================================================
# SET CHAT ON
# =========================================================

async def set_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Use:\n/seton 09:00"
        )
        return

    time_value = context.args[0]

    if not valid_time(time_value):
        await update.message.reply_text(
            "❌ Time galat hai.\nExample: `/seton 09:00`"
        )
        return

    data["chat_on"] = time_value
    save_data(data)

    await update.message.reply_text(
        f"🟢 Chat ON time set: {time_value} IST"
    )


# =========================================================
# SET CHAT OFF
# =========================================================

async def set_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Use:\n/setoff 22:00"
        )
        return

    time_value = context.args[0]

    if not valid_time(time_value):
        await update.message.reply_text(
            "❌ Time galat hai.\nExample: `/setoff 22:00`"
        )
        return

    data["chat_off"] = time_value
    save_data(data)

    await update.message.reply_text(
        f"🔴 Chat OFF time set: {time_value} IST"
    )


# =========================================================
# TIME VALIDATION
# =========================================================

def valid_time(value):
    try:
        datetime.strptime(value, "%H:%M")
        return True
    except ValueError:
        return False


# =========================================================
# CHAT ON
# =========================================================

async def chat_on(context: ContextTypes.DEFAULT_TYPE):
    if not GROUP_CHAT_ID:
        return

    try:
        await context.bot.set_chat_permissions(
            chat_id=GROUP_CHAT_ID,
            permissions=ChatPermissions.all_permissions()
        )

        logger.info("Chat turned ON")

    except Exception as e:
        logger.error("Chat ON error: %s", e)


# =========================================================
# CHAT OFF
# =========================================================

async def chat_off(context: ContextTypes.DEFAULT_TYPE):
    if not GROUP_CHAT_ID:
        return

    try:
        await context.bot.set_chat_permissions(
            chat_id=GROUP_CHAT_ID,
            permissions=ChatPermissions.no_permissions()
        )

        logger.info("Chat turned OFF")

    except Exception as e:
        logger.error("Chat OFF error: %s", e)


# =========================================================
# NOTICE ADD
# =========================================================

async def add_notice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Use:\n"
            "/notice 12:00 Important notice message"
        )
        return

    time_value = context.args[0]

    if not valid_time(time_value):
        await update.message.reply_text(
            "❌ Time galat hai.\nExample: `/notice 12:00 Message`"
        )
        return

    message = " ".join(context.args[1:])

    data["notices"].append({
        "time": time_value,
        "message": message
    })

    save_data(data)

    number = len(data["notices"])

    await update.message.reply_text(
        f"✅ Notice #{number} save ho gaya.\n\n"
        f"⏰ Time: {time_value} IST\n"
        f"📢 Message: {message}"
    )


# =========================================================
# SHOW NOTICES
# =========================================================

async def show_notices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context):
        return

    if not data["notices"]:
        await update.message.reply_text(
            "📢 Abhi koi notice set nahi hai."
        )
        return

    text = "📢 SCHEDULED NOTICES\n\n"

    for i, notice in enumerate(data["notices"], start=1):
        text += (
            f"{i}. ⏰ {notice['time']} IST\n"
            f"   📢 {notice['message']}\n\n"
        )

    await update.message.reply_text(text)


# =========================================================
# DELETE NOTICE
# =========================================================

async def delete_notice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Use:\n/delnotice 1"
        )
        return

    try:
        number = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ Notice number sahi dalein."
        )
        return

    if number < 1 or number > len(data["notices"]):
        await update.message.reply_text(
            "❌ Ye notice number available nahi hai."
        )
        return

    removed = data["notices"].pop(number - 1)
    save_data(data)

    await update.message.reply_text(
        f"🗑️ Notice #{number} delete ho gaya.\n"
        f"⏰ {removed['time']} IST"
    )


# =========================================================
# SCHEDULE CHECK
# =========================================================

async def scheduler(context: ContextTypes.DEFAULT_TYPE):
    if not GROUP_CHAT_ID:
        return

    now = current_time()

    # ---------------------------------------------
    # CHAT ON
    # ---------------------------------------------

    if data["chat_on"] == now:
        await chat_on(context)

    # ---------------------------------------------
    # CHAT OFF
    # ---------------------------------------------

    if data["chat_off"] == now:
        await chat_off(context)

    # ---------------------------------------------
    # NOTICES
    # ---------------------------------------------

    for notice in data["notices"]:
        if notice["time"] == now:
            try:
                await context.bot.send_message(
                    chat_id=GROUP_CHAT_ID,
                    text=notice["message"]
                )

                logger.info(
                    "Notice sent: %s",
                    notice["message"]
                )

            except Exception as e:
                logger.error(
                    "Notice error: %s",
                    e
                )


# =========================================================
# STARTUP
# =========================================================

async def post_init(application: Application):

    print("🤖 Second Bot Started...")
    print(f"🆔 GROUP_CHAT_ID: {GROUP_CHAT_ID}")
    print("🇮🇳 Timezone: Asia/Kolkata")

    # Remove any old webhook before polling
    try:
        await application.bot.delete_webhook(
            drop_pending_updates=False
        )
        print("✅ Webhook cleared")
    except Exception as e:
        print(f"Webhook clear warning: {e}")

    # Scheduler using JobQueue
    application.job_queue.run_repeating(
        scheduler,
        interval=20,
        first=5
    )

    print("⏰ Scheduler Started")


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(
        "Exception while handling update:",
        exc_info=context.error
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN Railway Variables me set nahi hai."
        )

    if not GROUP_CHAT_ID:
        raise RuntimeError(
            "GROUP_CHAT_ID Railway Variables me set nahi hai."
        )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Commands
    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("id", show_id)
    )

    app.add_handler(
        CommandHandler("settings", settings)
    )

    app.add_handler(
        CommandHandler("welcome", welcome)
    )

    app.add_handler(
        CommandHandler("setwelcome", set_welcome)
    )

    app.add_handler(
        CommandHandler("seton", set_on)
    )

    app.add_handler(
        CommandHandler("setoff", set_off)
    )

    app.add_handler(
        CommandHandler("notice", add_notice)
    )

    app.add_handler(
        CommandHandler("notices", show_notices)
    )

    app.add_handler(
        CommandHandler("delnotice", delete_notice)
    )

    # New member handler
    app.add_handler(
        ChatMemberHandler(
            new_member,
            ChatMemberHandler.CHAT_MEMBER
        )
    )

    # Error handler
    app.add_error_handler(error_handler)

    print("🚀 Starting Telegram polling...")

    # Only ONE polling process should use this BOT TOKEN.
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False
    )


if __name__ == "__main__":
    main()
