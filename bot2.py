import os
import json
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import (
    Update,
    ChatPermissions,
)
from telegram.constants import ParseMode
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

DATA_FILE = "welcome_notice_data.json"

DEFAULT_WELCOME = (
    "👋 Welcome {mention}!\n\n"
    "🎉 Welcome to our group.\n"
    "Please read the group rules and enjoy!"
)


# =========================================================
# DATA
# =========================================================

default_data = {
    "welcome_enabled": True,
    "welcome_message": DEFAULT_WELCOME,
    "chat_on_time": "",
    "chat_off_time": "",
    "notices": []
}


def load_data():
    if not os.path.exists(DATA_FILE):
        return default_data.copy()

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        for key, value in default_data.items():
            if key not in data:
                data[key] = value

        return data

    except Exception:
        return default_data.copy()


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


data = load_data()


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

    except Exception:
        return False


async def admin_only(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        if update.message:
            await update.message.reply_text(
                "❌ Ye command sirf group admins use kar sakte hain."
            )
        return False

    return True


# =========================================================
# /START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Bot 2 Active!\n\n"
        "Welcome + Scheduled Chat ON/OFF + Automatic Notices\n\n"
        "Commands ke liye /settings use karein."
    )


# =========================================================
# /ID
# =========================================================

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat:
        return

    await update.message.reply_text(
        f"🆔 Chat ID:\n`{update.effective_chat.id}`",
        parse_mode=ParseMode.MARKDOWN
    )


# =========================================================
# WELCOME SETTINGS
# =========================================================

async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context):
        return

    if not context.args:
        status = "ON 🟢" if data["welcome_enabled"] else "OFF 🔴"

        await update.message.reply_text(
            f"👋 Welcome message: {status}\n\n"
            f"ON karne ke liye:\n"
            f"`/welcome on`\n\n"
            f"OFF karne ke liye:\n"
            f"`/welcome off`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    value = context.args[0].lower()

    if value == "on":
        data["welcome_enabled"] = True
        save_data(data)

        await update.message.reply_text(
            "✅ Welcome message ON kar diya."
        )

    elif value == "off":
        data["welcome_enabled"] = False
        save_data(data)

        await update.message.reply_text(
            "🔴 Welcome message OFF kar diya."
        )

    else:
        await update.message.reply_text(
            "Use:\n`/welcome on`\n`/welcome off`",
            parse_mode=ParseMode.MARKDOWN
        )


# =========================================================
# /SETWELCOME
# =========================================================

async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "❌ Message bhi likho.\n\n"
            "Example:\n"
            "`/setwelcome 👋 Welcome {mention} to our group!`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    message = " ".join(context.args)

    data["welcome_message"] = message
    save_data(data)

    await update.message.reply_text(
        "✅ Welcome message save ho gaya.\n\n"
        "User mention ke liye `{mention}` use karna."
    )


# =========================================================
# NEW MEMBER WELCOME
# =========================================================

async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not data["welcome_enabled"]:
        return

    if not update.chat_member:
        return

    chat = update.chat_member.chat

    if GROUP_CHAT_ID and chat.id != GROUP_CHAT_ID:
        return

    old_status = update.chat_member.old_chat_member.status
    new_status = update.chat_member.new_chat_member.status

    joined_statuses = {
        "member",
        "restricted"
    }

    # Sirf actual new join par welcome
    if old_status in ("left", "kicked") and new_status in joined_statuses:

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
                parse_mode=ParseMode.HTML
            )

        except Exception as e:
            print("Welcome error:", e)


# =========================================================
# CHAT PERMISSIONS
# =========================================================

async def set_chat_open(context: ContextTypes.DEFAULT_TYPE):
    if GROUP_CHAT_ID == 0:
        print("GROUP_CHAT_ID not set.")
        return

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
        can_invite_users=True
    )

    try:
        await context.bot.set_chat_permissions(
            chat_id=GROUP_CHAT_ID,
            permissions=permissions
        )

        print("Group chat OPEN")

    except Exception as e:
        print("OPEN error:", e)


async def set_chat_closed(context: ContextTypes.DEFAULT_TYPE):
    if GROUP_CHAT_ID == 0:
        print("GROUP_CHAT_ID not set.")
        return

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
        can_invite_users=True
    )

    try:
        await context.bot.set_chat_permissions(
            chat_id=GROUP_CHAT_ID,
            permissions=permissions
        )

        print("Group chat CLOSED")

    except Exception as e:
        print("CLOSE error:", e)


# =========================================================
# /SETON
# =========================================================

async def set_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Example:\n`/seton 09:00`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    time_value = context.args[0]

    if not valid_time(time_value):
        await update.message.reply_text(
            "❌ Time galat hai.\nExample: `/seton 09:00`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    data["chat_on_time"] = time_value
    save_data(data)

    await update.message.reply_text(
        f"🟢 Group Chat ON time set:\n`{time_value}` IST",
        parse_mode=ParseMode.MARKDOWN
    )


# =========================================================
# /SETOFF
# =========================================================

async def set_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Example:\n`/setoff 22:00`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    time_value = context.args[0]

    if not valid_time(time_value):
        await update.message.reply_text(
            "❌ Time galat hai.\nExample: `/setoff 22:00`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    data["chat_off_time"] = time_value
    save_data(data)

    await update.message.reply_text(
        f"🔴 Group Chat OFF time set:\n`{time_value}` IST",
        parse_mode=ParseMode.MARKDOWN
    )


# =========================================================
# TIME CHECK
# =========================================================

def valid_time(value):
    try:
        datetime.strptime(value, "%H:%M")
        return True
    except ValueError:
        return False


# =========================================================
# NOTICE ADD
# =========================================================

async def add_notice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Format:\n"
            "`/notice 20:00 Important notice yahan likho`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    time_value = context.args[0]
    message = " ".join(context.args[1:])

    if not valid_time(time_value):
        await update.message.reply_text(
            "❌ Time galat hai.\nExample: `/notice 20:00 Meeting hai`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    data["notices"].append({
        "time": time_value,
        "message": message,
        "enabled": True
    })

    save_data(data)

    number = len(data["notices"])

    await update.message.reply_text(
        f"✅ Notice #{number} save ho gaya.\n\n"
        f"⏰ Time: {time_value} IST\n"
        f"📢 Message: {message}"
    )


# =========================================================
# /NOTICES
# =========================================================

async def list_notices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context):
        return

    notices = data["notices"]

    if not notices:
        await update.message.reply_text(
            "📭 Abhi koi scheduled notice nahi hai."
        )
        return

    text = "📢 Scheduled Notices\n\n"

    for i, notice in enumerate(notices, start=1):
        status = "🟢" if notice.get("enabled", True) else "🔴"

        text += (
            f"{i}. {status} ⏰ {notice['time']} IST\n"
            f"   {notice['message']}\n\n"
        )

    await update.message.reply_text(text)


# =========================================================
# /DELNOTICE
# =========================================================

async def delete_notice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Example:\n`/delnotice 1`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    try:
        number = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Notice number galat hai.")
        return

    if number < 1 or number > len(data["notices"]):
        await update.message.reply_text(
            "❌ Ye notice number exist nahi karta."
        )
        return

    removed = data["notices"].pop(number - 1)
    save_data(data)

    await update.message.reply_text(
        f"🗑️ Notice #{number} delete ho gaya.\n"
        f"⏰ {removed['time']}"
    )


# =========================================================
# /SETTINGS
# =========================================================

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context):
        return

    welcome_status = (
        "🟢 ON" if data["welcome_enabled"] else "🔴 OFF"
    )

    on_time = data["chat_on_time"] or "Not set"
    off_time = data["chat_off_time"] or "Not set"

    text = (
        "⚙️ BOT SETTINGS\n\n"
        f"👋 Welcome: {welcome_status}\n"
        f"🟢 Chat ON: {on_time} IST\n"
        f"🔴 Chat OFF: {off_time} IST\n"
        f"📢 Notices: {len(data['notices'])}\n\n"
        "Commands:\n"
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

    await update.message.reply_text(text)


# =========================================================
# SCHEDULER
# =========================================================

async def scheduler(application):
    last_on = None
    last_off = None
    last_notices = set()

    while True:
        try:
            now = datetime.now(IST)
            current_time = now.strftime("%H:%M")
            date_key = now.strftime("%Y-%m-%d")

            # -----------------------------
            # CHAT ON
            # -----------------------------

            if (
                data["chat_on_time"]
                and current_time == data["chat_on_time"]
            ):
                key = f"{date_key}-on"

                if key != last_on:
                    await set_chat_open(
                        application
                    )
                    last_on = key

            # -----------------------------
            # CHAT OFF
            # -----------------------------

            if (
                data["chat_off_time"]
                and current_time == data["chat_off_time"]
            ):
                key = f"{date_key}-off"

                if key != last_off:
                    await set_chat_closed(
                        application
                    )
                    last_off = key

            # -----------------------------
            # NOTICES
            # -----------------------------

            for index, notice in enumerate(data["notices"]):

                if not notice.get("enabled", True):
                    continue

                if notice["time"] != current_time:
                    continue

                key = f"{date_key}-{index}-{notice['time']}"

                if key in last_notices:
                    continue

                try:
                    await application.bot.send_message(
                        chat_id=GROUP_CHAT_ID,
                        text=notice["message"]
                    )

                    last_notices.add(key)

                except Exception as e:
                    print("Notice error:", e)

            # Old notice keys clean
            if len(last_notices) > 100:
                last_notices.clear()

        except Exception as e:
            print("Scheduler error:", e)

        await asyncio.sleep(20)


# =========================================================
# START SCHEDULER
# =========================================================

async def post_init(application):
    application.create_task(
        scheduler(application)
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:
        raise ValueError(
            "BOT_TOKEN Railway Variables me set nahi hai."
        )

    if GROUP_CHAT_ID == 0:
        raise ValueError(
            "GROUP_CHAT_ID Railway Variables me set nahi hai."
        )

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
        CommandHandler("id", get_id)
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
        CommandHandler("notice", add_notice)
    )

    application.add_handler(
        CommandHandler("notices", list_notices)
    )

    application.add_handler(
        CommandHandler("delnotice", delete_notice)
    )

    application.add_handler(
        CommandHandler("settings", settings)
    )

    # New member handler
    application.add_handler(
        ChatMemberHandler(
            new_member,
            ChatMemberHandler.CHAT_MEMBER
        )
    )

    print("🤖 Second Bot Started...")
    print("🇮🇳 Timezone: Asia/Kolkata")
    print("🆔 GROUP_CHAT_ID:", GROUP_CHAT_ID)

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
