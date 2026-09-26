import os
import json
import asyncio
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
# SECOND BOT
# Welcome + Scheduled Group ON/OFF + Automatic Notices
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "-1004318016710"))

IST = ZoneInfo("Asia/Kolkata")
DATA_FILE = "bot2_data.json"

DEFAULT_WELCOME = (
    "👋 Welcome {mention}!\n\n"
    "🎉 Welcome to the group.\n"
    "📌 Please read the group rules and stay respectful."
)

# ---------------------------------------------------------
# DATA
# ---------------------------------------------------------

def load_data():
    default = {
        "welcome_enabled": True,
        "welcome_text": DEFAULT_WELCOME,
        "on_time": None,
        "off_time": None,
        "notices": []
    }

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        for key, value in default.items():
            if key not in data:
                data[key] = value

        return data

    except (FileNotFoundError, json.JSONDecodeError):
        save_data(default)
        return default


def save_data(data):
    temp_file = DATA_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    os.replace(temp_file, DATA_FILE)


data = load_data()

# Prevent the same scheduled action/notice from running twice
last_actions = {
    "on": None,
    "off": None,
    "notices": {}
}


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def now_ist():
    return datetime.now(IST)


def today_key():
    return now_ist().strftime("%Y-%m-%d")


def is_admin(member):
    return member.status in ("administrator", "creator")


async def check_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.effective_user:
        return False

    # Commands are intended for the configured group.
    if update.effective_chat.id != GROUP_CHAT_ID:
        return False

    try:
        member = await context.bot.get_chat_member(
            GROUP_CHAT_ID,
            update.effective_user.id
        )
        return is_admin(member)

    except Exception:
        return False


def parse_time(value):
    try:
        datetime.strptime(value, "%H:%M")
        return value
    except ValueError:
        return None


def mention_html(user):
    name = user.first_name or "User"
    safe_name = (
        name.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return f'<a href="tg://user?id={user.id}">{safe_name}</a>'


def member_permissions(can_send):
    # Permissions for normal group members.
    # Admin/bot permissions are not changed by this.
    return ChatPermissions(
        can_send_messages=can_send,
        can_send_audios=can_send,
        can_send_documents=can_send,
        can_send_photos=can_send,
        can_send_videos=can_send,
        can_send_video_notes=can_send,
        can_send_voice_notes=can_send,
        can_send_polls=can_send,
        can_send_other_messages=can_send,
        can_add_web_page_previews=can_send,
        can_change_info=False,
        can_invite_users=can_send,
        can_pin_messages=False,
        can_manage_topics=can_send,
    )


async def set_group_chat(context, enabled):
    permissions = member_permissions(enabled)

    await context.bot.set_chat_permissions(
        chat_id=GROUP_CHAT_ID,
        permissions=permissions,
        use_independent_chat_permissions=True,
    )


# ---------------------------------------------------------
# /start
# ---------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_CHAT_ID:
        await update.message.reply_text(
            "⚠️ Ye bot configured group ke liye hai."
        )
        return

    await update.message.reply_text(
        "🤖 Second Bot Active!\n\n"
        "👋 New member welcome\n"
        "🔓 Scheduled Chat ON\n"
        "🔒 Scheduled Chat OFF\n"
        "📢 Automatic Notices\n\n"
        "Admin commands ke liye /help use karein."
    )


# ---------------------------------------------------------
# /help
# ---------------------------------------------------------

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, context):
        await update.message.reply_text("❌ Sirf group admins use kar sakte hain.")
        return

    await update.message.reply_text(
        "🛠️ ADMIN COMMANDS\n\n"
        "/id - Group ID\n"
        "/welcome on - Welcome ON\n"
        "/welcome off - Welcome OFF\n"
        "/setwelcome MESSAGE - Welcome message set\n\n"
        "/seton HH:MM - Chat ON time\n"
        "/setoff HH:MM - Chat OFF time\n\n"
        "/notice HH:MM MESSAGE - Automatic notice add\n"
        "/notices - Notices list\n"
        "/delnotice NUMBER - Notice delete\n\n"
        "/settings - Current settings\n\n"
        "⏰ Time format: 24-hour IST\n"
        "Example: /seton 08:00\n"
        "Example: /setoff 22:00\n"
        "Example: /notice 12:00 Lunch time notice"
    )


# ---------------------------------------------------------
# /id
# ---------------------------------------------------------

async def group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 Group Chat ID:\n`{update.effective_chat.id}`",
        parse_mode="Markdown"
    )


# ---------------------------------------------------------
# /welcome
# ---------------------------------------------------------

async def welcome_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, context):
        await update.message.reply_text("❌ Sirf group admins use kar sakte hain.")
        return

    if not context.args or context.args[0].lower() not in ("on", "off"):
        await update.message.reply_text(
            "Use:\n/welcome on\n/welcome off"
        )
        return

    enabled = context.args[0].lower() == "on"
    data["welcome_enabled"] = enabled
    save_data(data)

    await update.message.reply_text(
        f"👋 Welcome message {'ON ✅' if enabled else 'OFF ❌'}"
    )


# ---------------------------------------------------------
# /setwelcome
# ---------------------------------------------------------

async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, context):
        await update.message.reply_text("❌ Sirf group admins use kar sakte hain.")
        return

    text = " ".join(context.args).strip()

    if not text:
        await update.message.reply_text(
            "Example:\n"
            "/setwelcome 👋 Welcome {mention}!\n"
            "Please follow group rules."
        )
        return

    if "{mention}" not in text:
        text += "\n\n{mention}"

    data["welcome_text"] = text
    save_data(data)

    await update.message.reply_text(
        "✅ Welcome message save ho gaya.\n\n"
        "User name ke liye `{mention}` use hota hai."
    )


# ---------------------------------------------------------
# NEW MEMBER WELCOME
# ---------------------------------------------------------

async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat:
        return

    if update.effective_chat.id != GROUP_CHAT_ID:
        return

    if not data.get("welcome_enabled", True):
        return

    cm = update.chat_member

    if not cm:
        return

    old_status = cm.old_chat_member.status
    new_status = cm.new_chat_member.status

    # Only new joins / re-joins
    was_out = old_status in ("left", "kicked")
    is_member_now = new_status in ("member", "administrator", "creator")

    if not (was_out and is_member_now):
        return

    user = cm.new_chat_member.user
    mention = mention_html(user)

    message = data.get("welcome_text", DEFAULT_WELCOME)
    message = message.replace("{mention}", mention)

    try:
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=message,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        print("Welcome error:", e)


# ---------------------------------------------------------
# /seton
# ---------------------------------------------------------

async def set_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, context):
        await update.message.reply_text("❌ Sirf group admins use kar sakte hain.")
        return

    if not context.args:
        await update.message.reply_text("Example: /seton 08:00")
        return

    t = parse_time(context.args[0])

    if not t:
        await update.message.reply_text(
            "❌ Time galat hai.\nExample: /seton 08:00"
        )
        return

    data["on_time"] = t
    save_data(data)

    await update.message.reply_text(
        f"🔓 Chat ON time set: {t} IST"
    )


# ---------------------------------------------------------
# /setoff
# ---------------------------------------------------------

async def set_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, context):
        await update.message.reply_text("❌ Sirf group admins use kar sakte hain.")
        return

    if not context.args:
        await update.message.reply_text("Example: /setoff 22:00")
        return

    t = parse_time(context.args[0])

    if not t:
        await update.message.reply_text(
            "❌ Time galat hai.\nExample: /setoff 22:00"
        )
        return

    data["off_time"] = t
    save_data(data)

    await update.message.reply_text(
        f"🔒 Chat OFF time set: {t} IST"
    )


# ---------------------------------------------------------
# /notice
# ---------------------------------------------------------

async def add_notice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, context):
        await update.message.reply_text("❌ Sirf group admins use kar sakte hain.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Example:\n"
            "/notice 12:00 Lunch time notice 🍛"
        )
        return

    t = parse_time(context.args[0])

    if not t:
        await update.message.reply_text(
            "❌ Time galat hai.\nExample: /notice 12:00 Lunch"
        )
        return

    message = " ".join(context.args[1:]).strip()

    data.setdefault("notices", []).append({
        "time": t,
        "message": message
    })

    save_data(data)

    number = len(data["notices"])

    await update.message.reply_text(
        f"✅ Notice #{number} added.\n"
        f"⏰ Time: {t} IST\n"
        f"📢 Message: {message}"
    )


# ---------------------------------------------------------
# /notices
# ---------------------------------------------------------

async def list_notices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, context):
        await update.message.reply_text("❌ Sirf group admins use kar sakte hain.")
        return

    notices = data.get("notices", [])

    if not notices:
        await update.message.reply_text("📭 Koi automatic notice set nahi hai.")
        return

    lines = ["📢 AUTOMATIC NOTICES\n"]

    for i, item in enumerate(notices, start=1):
        lines.append(
            f"{i}. ⏰ {item['time']} IST\n"
            f"   📝 {item['message']}"
        )

    await update.message.reply_text("\n\n".join(lines))


# ---------------------------------------------------------
# /delnotice
# ---------------------------------------------------------

async def delete_notice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, context):
        await update.message.reply_text("❌ Sirf group admins use kar sakte hain.")
        return

    if not context.args:
        await update.message.reply_text("Example: /delnotice 1")
        return

    try:
        number = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Notice number galat hai.")
        return

    notices = data.get("notices", [])

    if number < 1 or number > len(notices):
        await update.message.reply_text("❌ Aisa notice number nahi hai.")
        return

    removed = notices.pop(number - 1)
    save_data(data)

    await update.message.reply_text(
        f"🗑️ Notice #{number} delete ho gaya.\n"
        f"⏰ {removed['time']} IST"
    )


# ---------------------------------------------------------
# /settings
# ---------------------------------------------------------

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, context):
        await update.message.reply_text("❌ Sirf group admins use kar sakte hain.")
        return

    notices = data.get("notices", [])

    await update.message.reply_text(
        "⚙️ CURRENT SETTINGS\n\n"
        f"👋 Welcome: {'ON ✅' if data.get('welcome_enabled') else 'OFF ❌'}\n"
        f"🔓 Chat ON: {data.get('on_time') or 'Not set'} IST\n"
        f"🔒 Chat OFF: {data.get('off_time') or 'Not set'} IST\n"
        f"📢 Notices: {len(notices)}\n"
        f"🆔 Group ID: {GROUP_CHAT_ID}\n"
        f"🇮🇳 Timezone: Asia/Kolkata"
    )


# ---------------------------------------------------------
# SCHEDULER
# ---------------------------------------------------------

async def scheduler(application: Application):
    print("⏰ Scheduler started...")

    while True:
        try:
            current = now_ist()
            current_hm = current.strftime("%H:%M")
            day = current.strftime("%Y-%m-%d")

            # CHAT ON
            if data.get("on_time") == current_hm:
                action_key = f"{day}-on"

                if last_actions["on"] != action_key:
                    try:
                        await set_group_chat(
                            type("Ctx", (), {"bot": application.bot})(),
                            True
                        )
                        last_actions["on"] = action_key
                        print(f"🔓 Chat ON at {current_hm} IST")
                    except Exception as e:
                        print("Chat ON error:", e)

            # CHAT OFF
            if data.get("off_time") == current_hm:
                action_key = f"{day}-off"

                if last_actions["off"] != action_key:
                    try:
                        await set_group_chat(
                            type("Ctx", (), {"bot": application.bot})(),
                            False
                        )
                        last_actions["off"] = action_key
                        print(f"🔒 Chat OFF at {current_hm} IST")
                    except Exception as e:
                        print("Chat OFF error:", e)

            # AUTOMATIC NOTICES
            for index, notice in enumerate(data.get("notices", [])):
                if notice.get("time") != current_hm:
                    continue

                notice_key = f"{day}-{index}-{notice.get('time')}"

                if last_actions["notices"].get(index) == notice_key:
                    continue

                try:
                    await application.bot.send_message(
                        chat_id=GROUP_CHAT_ID,
                        text=notice.get("message", ""),
                    )

                    last_actions["notices"][index] = notice_key

                    print(
                        f"📢 Notice #{index + 1} sent at {current_hm} IST"
                    )

                except Exception as e:
                    print(f"Notice #{index + 1} error:", e)

        except Exception as e:
            print("Scheduler error:", e)

        await asyncio.sleep(15)


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

async def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN Railway Variables me set nahi hai."
        )

    print("🚀 Starting Telegram polling...")
    print("🤖 Second Bot Started...")
    print(f"🆔 GROUP_CHAT_ID: {GROUP_CHAT_ID}")
    print("🇮🇳 Timezone: Asia/Kolkata")

    application = Application.builder().token(BOT_TOKEN).build()

    # COMMANDS
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("id", group_id))
    application.add_handler(CommandHandler("welcome", welcome_toggle))
    application.add_handler(CommandHandler("setwelcome", set_welcome))
    application.add_handler(CommandHandler("seton", set_on))
    application.add_handler(CommandHandler("setoff", set_off))
    application.add_handler(CommandHandler("notice", add_notice))
    application.add_handler(CommandHandler("notices", list_notices))
    application.add_handler(CommandHandler("delnotice", delete_notice))
    application.add_handler(CommandHandler("settings", settings))

    # NEW MEMBER
    application.add_handler(
        ChatMemberHandler(
            new_member,
            ChatMemberHandler.CHAT_MEMBER
        )
    )

    # Start application manually so scheduler is created only
    # after the Telegram application is running.
    await application.initialize()

    try:
        await application.start()

        # Remove any old webhook before polling.
        await application.bot.delete_webhook(drop_pending_updates=False)
        print("✅ Webhook cleared")

        await application.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False,
        )

        scheduler_task = asyncio.create_task(scheduler(application))

        print("✅ Telegram polling started.")
        print("⏰ Scheduler is running.")
        print("🤖 Bot is ready.")

        # Keep process alive.
        await asyncio.Event().wait()

    finally:
        print("🛑 Stopping bot...")

        try:
            scheduler_task.cancel()
            await scheduler_task
        except (NameError, asyncio.CancelledError):
            pass

        try:
            await application.updater.stop()
        except Exception:
            pass

        try:
            await application.stop()
        except Exception:
            pass

        try:
            await application.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
