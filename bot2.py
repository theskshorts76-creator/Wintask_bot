import os
import json
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import (
    Update,
    ChatPermissions,
)
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

GROUP_CHAT_ID = int(
    os.getenv("GROUP_CHAT_ID", "-1004318016710")
)

IST = ZoneInfo("Asia/Kolkata")

DATA_FILE = "bot2_data.json"


# =========================================================
# DEFAULT DATA
# =========================================================

DEFAULT_DATA = {
    "welcome_enabled": True,
    "welcome_message": (
        "👋 Welcome {mention}!\n\n"
        "🎉 Welcome to our group.\n"
        "Please read the group rules and stay active. ❤️"
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
        save_data(DEFAULT_DATA.copy())
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
# HELPERS
# =========================================================

def now_ist():
    return datetime.now(IST)


def current_time():
    return now_ist().strftime("%H:%M")


def current_date():
    return now_ist().strftime("%Y-%m-%d")


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.effective_user:
        return False

    if update.effective_chat.id != GROUP_CHAT_ID:
        return False

    try:
        member = await context.bot.get_chat_member(
            GROUP_CHAT_ID,
            update.effective_user.id
        )

        return member.status in ("administrator", "creator")

    except Exception:
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

    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "🤖 Bot 2 Active!\n\n"
            "Welcome + Scheduled Chat ON/OFF + Automatic Notices\n\n"
            "Group me /settings use karein."
        )
        return

    if update.effective_chat.id != GROUP_CHAT_ID:
        return

    await update.message.reply_text(
        "🤖 Second Bot Active!\n\n"
        "👋 Welcome Message\n"
        "🟢 Scheduled Chat ON\n"
        "🔴 Scheduled Chat OFF\n"
        "📢 Automatic Notices\n\n"
        "⚙️ Commands ke liye /settings use karein."
    )


# =========================================================
# ID
# =========================================================

async def show_id(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "🆔 Private Chat ID:\n"
            f"`{update.effective_chat.id}`",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        "🆔 Group Chat ID:\n"
        f"`{update.effective_chat.id}`",
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

    notices = len(data["notices"])

    text = (
        "⚙️ BOT SETTINGS\n\n"
        f"👋 Welcome: {welcome_status}\n"
        f"🟢 Chat ON: {chat_on} IST\n"
        f"🔴 Chat OFF: {chat_off} IST\n"
        f"📢 Notices: {notices}\n\n"
        "📌 Commands:\n\n"
        "/welcome on\n"
        "/welcome off\n"
        "/setwelcome MESSAGE\n"
        "/seton HH:MM\n"
        "/setoff HH:MM\n"
        "/notice HH:MM MESSAGE\n"
        "/notices\n"
        "/delnotice NUMBER\n"
        "/id\n"
        "/settings"
    )

    await update.message.reply_text(text)


# =========================================================
# WELCOME ON/OFF
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
            "❌ Sirf on ya off use karein."
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
            "/setwelcome MESSAGE\n\n"
            "Example:\n"
            "/setwelcome 👋 Welcome {mention}! ❤️"
        )
        return

    message = " ".join(context.args)

    data["welcome_message"] = message
    save_data(data)

    await update.message.reply_text(
        "✅ Welcome message updated."
    )


# =========================================================
# SET CHAT ON
# =========================================================

async def set_on(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await admin_only(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Use:\n/seton HH:MM\n\n"
            "Example:\n/seton 09:00"
        )
        return

    time_value = context.args[0]

    try:
        datetime.strptime(time_value, "%H:%M")
    except ValueError:
        await update.message.reply_text(
            "❌ Time galat hai.\nExample: /seton 09:00"
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
            "Use:\n/setoff HH:MM\n\n"
            "Example:\n/setoff 22:00"
        )
        return

    time_value = context.args[0]

    try:
        datetime.strptime(time_value, "%H:%M")
    except ValueError:
        await update.message.reply_text(
            "❌ Time galat hai.\nExample: /setoff 22:00"
        )
        return

    data["chat_off"] = time_value
    save_data(data)

    await update.message.reply_text(
        f"🔴 Chat OFF time set: {time_value} IST"
    )


# =========================================================
# SET CHAT PERMISSIONS
# =========================================================

async def set_chat_permissions(context, can_send: bool):

    if can_send:

        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_add_web_page_previews=True,
        )

    else:

        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_add_web_page_previews=False,
        )

    await context.bot.set_chat_permissions(
        chat_id=GROUP_CHAT_ID,
        permissions=permissions,
        use_independent_chat_permissions=True
    )


# =========================================================
# AUTOMATIC NOTICE
# =========================================================

async def notice(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await admin_only(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Use:\n"
            "/notice HH:MM MESSAGE\n\n"
            "Example:\n"
            "/notice 10:00 Good morning everyone ❤️"
        )
        return

    time_value = context.args[0]
    message = " ".join(context.args[1:])

    try:
        datetime.strptime(time_value, "%H:%M")
    except ValueError:
        await update.message.reply_text(
            "❌ Time galat hai.\nExample: /notice 10:00 Message"
        )
        return

    data["notices"].append({
        "time": time_value,
        "message": message
    })

    save_data(data)

    number = len(data["notices"])

    await update.message.reply_text(
        f"✅ Notice added.\n\n"
        f"#{number}\n"
        f"⏰ {time_value} IST\n"
        f"📢 {message}"
    )


# =========================================================
# SHOW NOTICES
# =========================================================

async def notices(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await admin_only(update, context):
        return

    if not data["notices"]:
        await update.message.reply_text(
            "📢 Abhi koi automatic notice set nahi hai."
        )
        return

    text = "📢 AUTOMATIC NOTICES\n\n"

    for i, item in enumerate(data["notices"], start=1):
        text += (
            f"{i}. ⏰ {item['time']} IST\n"
            f"   📢 {item['message']}\n\n"
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
            "Use:\n/delnotice NUMBER\n\n"
            "Example:\n/delnotice 1"
        )
        return

    try:
        number = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ Number galat hai."
        )
        return

    if number < 1 or number > len(data["notices"]):
        await update.message.reply_text(
            "❌ Notice number nahi mila."
        )
        return

    removed = data["notices"].pop(number - 1)
    save_data(data)

    await update.message.reply_text(
        f"🗑️ Notice deleted.\n\n"
        f"⏰ {removed['time']} IST\n"
        f"📢 {removed['message']}"
    )


# =========================================================
# NEW MEMBER WELCOME
# =========================================================

async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_chat.id != GROUP_CHAT_ID:
        return

    if not data["welcome_enabled"]:
        return

    chat_member_update = update.chat_member

    if not chat_member_update:
        return

    old_status = chat_member_update.old_chat_member.status
    new_status = chat_member_update.new_chat_member.status

    joined_statuses = {
        "member",
        "administrator",
        "creator"
    }

    left_statuses = {
        "left",
        "kicked"
    }

    if old_status in left_statuses and new_status in joined_statuses:

        user = chat_member_update.new_chat_member.user

        mention = user.mention_html()

        message = data["welcome_message"].replace(
            "{mention}",
            mention
        )

        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=message,
            parse_mode="HTML"
        )


# =========================================================
# SCHEDULER
# =========================================================

async def scheduler_loop(application):

    last_chat_on = None
    last_chat_off = None
    sent_notices = set()

    while True:

        try:
            now = now_ist()

            time_now = now.strftime("%H:%M")
            date_now = now.strftime("%Y-%m-%d")

            # ---------------------------------------------
            # CHAT ON
            # ---------------------------------------------

            if (
                data.get("chat_on")
                and time_now == data["chat_on"]
                and last_chat_on != f"{date_now}-{time_now}"
            ):

                try:
                    await set_chat_permissions(
                        application,
                        True
                    )

                    await application.bot.send_message(
                        chat_id=GROUP_CHAT_ID,
                        text=(
                            "🟢 GROUP CHAT ON\n\n"
                            "Ab members message bhej sakte hain."
                        )
                    )

                    last_chat_on = f"{date_now}-{time_now}"

                except Exception as e:
                    print("Chat ON error:", e)

            # ---------------------------------------------
            # CHAT OFF
            # ---------------------------------------------

            if (
                data.get("chat_off")
                and time_now == data["chat_off"]
                and last_chat_off != f"{date_now}-{time_now}"
            ):

                try:
                    await set_chat_permissions(
                        application,
                        False
                    )

                    await application.bot.send_message(
                        chat_id=GROUP_CHAT_ID,
                        text=(
                            "🔴 GROUP CHAT OFF\n\n"
                            "Ab members message nahi bhej sakte."
                        )
                    )

                    last_chat_off = f"{date_now}-{time_now}"

                except Exception as e:
                    print("Chat OFF error:", e)

            # ---------------------------------------------
            # AUTOMATIC NOTICES
            # ---------------------------------------------

            for index, item in enumerate(data.get("notices", [])):

                notice_id = f"{date_now}-{index}-{item['time']}"

                if (
                    time_now == item["time"]
                    and notice_id not in sent_notices
                ):

                    try:
                        await application.bot.send_message(
                            chat_id=GROUP_CHAT_ID,
                            text=item["message"]
                        )

                        sent_notices.add(notice_id)

                    except Exception as e:
                        print("Notice error:", e)

            # Old notice IDs remove
            sent_notices = {
                x for x in sent_notices
                if x.startswith(date_now)
            }

        except Exception as e:
            print("Scheduler error:", e)

        await asyncio.sleep(20)


# =========================================================
# STARTUP
# =========================================================

async def post_init(application):

    print("🤖 Second Bot Started...")
    print(f"🆔 GROUP_CHAT_ID: {GROUP_CHAT_ID}")
    print("🇮🇳 Timezone: Asia/Kolkata")

    try:
        await application.bot.delete_webhook(
            drop_pending_updates=False
        )

        print("✅ Webhook cleared")

    except Exception as e:
        print("Webhook clear error:", e)

    # Start our own scheduler.
    # JobQueue ki zarurat nahi hai.
    application.create_task(
        scheduler_loop(application)
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:
        print("❌ BOT_TOKEN missing in Railway Variables")
        return

    if GROUP_CHAT_ID == 0:
        print("❌ GROUP_CHAT_ID missing in Railway Variables")
        return

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Commands
    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("id", show_id)
    )

    application.add_handler(
        CommandHandler("settings", settings)
    )

    application.add_handler(
        CommandHandler("welcome", welcome)
    )

    application.add_handler(
        CommandHandler("setwelcome", set_welcome)
    )

    application.add_handler(
        CommandHandler("seton", set_on)
    )

    application.add_handler(
        CommandHandler("setoff", set_off)
    )

    application.add_handler(
        CommandHandler("notice", notice)
    )

    application.add_handler(
        CommandHandler("notices", notices)
    )

    application.add_handler(
        CommandHandler("delnotice", delete_notice)
    )

    # New member handler
    application.add_handler(
        ChatMemberHandler(
            new_member,
            ChatMemberHandler.CHAT_MEMBER
        )
    )

    print("🚀 Starting Telegram polling...")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False
    )


if __name__ == "__main__":
    main()
