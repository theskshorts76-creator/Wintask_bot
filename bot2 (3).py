import os
import json
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update, ChatPermissions
from telegram.ext import Application, CommandHandler, ChatMemberHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
TARGET_GROUP_ID = int(os.getenv("TARGET_GROUP_ID", "-1004318016710"))
COMMAND_GROUP_ID = int(os.getenv("COMMAND_GROUP_ID", "-1003775459183"))
IST = ZoneInfo("Asia/Kolkata")
DATA_FILE = "bot2_data.json"

DEFAULT_WELCOME = "👋 Welcome {mention}!\n\n🎉 Welcome to the group.\nPlease read the group rules and enjoy!"

def load_data():
    default = {"welcome_enabled": True, "welcome_text": DEFAULT_WELCOME, "on_time": "", "off_time": "", "notices": []}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return default
        for k, v in default.items():
            data.setdefault(k, v)
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return default

DATA = load_data()

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(DATA, f, ensure_ascii=False, indent=2)

def now_ist():
    return datetime.now(IST)

def is_command_group(update):
    return update.effective_chat is not None and update.effective_chat.id == COMMAND_GROUP_ID

async def is_admin(update, context):
    if not is_command_group(update) or update.effective_user is None:
        return False
    try:
        member = await context.bot.get_chat_member(COMMAND_GROUP_ID, update.effective_user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False

async def admin_only(update, context):
    if not await is_admin(update, context):
        if update.message:
            await update.message.reply_text("⚠️ Ye command sirf Command Group ke admins use kar sakte hain.")
        return False
    return True

def parse_hhmm(value):
    try:
        h, m = value.strip().split(":")
        h, m = int(h), int(m)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None
        return f"{h:02d}:{m:02d}"
    except Exception:
        return None

def mention_html(user):
    name = user.full_name or user.first_name or "New Member"
    name = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    return f'<a href="tg://user?id={user.id}">{name}</a>'

async def set_group_chat_on(bot):
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
        can_change_info=False,
        can_invite_users=True,
        can_pin_messages=False,
        can_manage_topics=True,
    )
    await bot.set_chat_permissions(TARGET_GROUP_ID, permissions, use_independent_chat_permissions=True)

async def set_group_chat_off(bot):
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
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )
    await bot.set_chat_permissions(TARGET_GROUP_ID, permissions, use_independent_chat_permissions=True)

async def start(update, context):
    if not is_command_group(update):
        if update.message:
            await update.message.reply_text("⚠️ Ye bot sirf configured Command Group me configure hota hai.")
        return
    await update.message.reply_text(
        "✅ Second Bot is working!\n\n"
        f"🎯 Target Group: `{TARGET_GROUP_ID}`\n"
        f"💬 Command Group: `{COMMAND_GROUP_ID}`\n\n"
        "📌 Commands:\n/id\n/settings\n/welcome on\n/welcome off\n/setwelcome MESSAGE\n"
        "/seton HH:MM\n/setoff HH:MM\n/notice HH:MM MESSAGE\n/notices\n/delnotice NUMBER",
        parse_mode="Markdown",
    )

async def show_id(update, context):
    if update.effective_chat is None or update.message is None:
        return
    await update.message.reply_text(
        f"🆔 Chat ID: `{update.effective_chat.id}`\n"
        f"💬 Type: `{update.effective_chat.type}`\n"
        f"📌 Name: {update.effective_chat.title or 'Private Chat'}",
        parse_mode="Markdown",
    )

async def welcome_command(update, context):
    if not await admin_only(update, context):
        return
    if not context.args or context.args[0].lower() not in ("on", "off"):
        await update.message.reply_text("Use:\n/welcome on\n/welcome off")
        return
    DATA["welcome_enabled"] = context.args[0].lower() == "on"
    save_data()
    await update.message.reply_text("👋 Welcome message: " + ("ON 🟢" if DATA["welcome_enabled"] else "OFF 🔴"))

async def set_welcome(update, context):
    if not await admin_only(update, context):
        return
    text = update.message.text.partition(" ")[2].strip()
    if not text:
        await update.message.reply_text("Use:\n/setwelcome Welcome {mention}! 🎉")
        return
    DATA["welcome_text"] = text
    save_data()
    await update.message.reply_text("✅ Welcome message saved. Use {mention} where the member mention should appear.")

async def new_member(update, context):
    if not update.chat_member or update.effective_chat.id != TARGET_GROUP_ID:
        return
    old_status = update.chat_member.old_chat_member.status
    new_status = update.chat_member.new_chat_member.status
    if not (new_status in ("member", "restricted") and old_status in ("left", "kicked")):
        return
    if not DATA.get("welcome_enabled", True):
        return
    user = update.chat_member.new_chat_member.user
    text = DATA.get("welcome_text", DEFAULT_WELCOME).replace("{mention}", mention_html(user))
    try:
        await context.bot.send_message(TARGET_GROUP_ID, text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        print(f"Welcome error: {e}")

async def set_on(update, context):
    if not await admin_only(update, context):
        return
    if not context.args:
        await update.message.reply_text("Use:\n/seton 09:00")
        return
    value = parse_hhmm(context.args[0])
    if value is None:
        await update.message.reply_text("❌ Time galat hai. Example: /seton 09:00")
        return
    DATA["on_time"] = value
    save_data()
    await update.message.reply_text(f"🟢 Group ON time set: {value} IST")

async def set_off(update, context):
    if not await admin_only(update, context):
        return
    if not context.args:
        await update.message.reply_text("Use:\n/setoff 22:00")
        return
    value = parse_hhmm(context.args[0])
    if value is None:
        await update.message.reply_text("❌ Time galat hai. Example: /setoff 22:00")
        return
    DATA["off_time"] = value
    save_data()
    await update.message.reply_text(f"🔴 Group OFF time set: {value} IST")

async def notice(update, context):
    if not await admin_only(update, context):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Use:\n/notice 12:30 Important meeting at 1 PM")
        return
    value = parse_hhmm(context.args[0])
    if value is None:
        await update.message.reply_text("❌ Time galat hai. Example: /notice 12:30 Message")
        return
    message = " ".join(context.args[1:]).strip()
    DATA["notices"].append({"time": value, "message": message, "last_sent": ""})
    save_data()
    await update.message.reply_text(f"✅ Notice #{len(DATA['notices'])} saved.\n⏰ {value} IST\n📢 {message}")

async def notices(update, context):
    if not await admin_only(update, context):
        return
    items = DATA.get("notices", [])
    if not items:
        await update.message.reply_text("📢 Abhi koi scheduled notice nahi hai.")
        return
    lines = ["📢 Scheduled Notices:\n"]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. ⏰ {item['time']} IST\n   📢 {item['message']}")
    await update.message.reply_text("\n".join(lines))

async def delete_notice(update, context):
    if not await admin_only(update, context):
        return
    if not context.args:
        await update.message.reply_text("Use:\n/delnotice 1")
        return
    try:
        number = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Notice number galat hai.")
        return
    items = DATA.get("notices", [])
    if not 1 <= number <= len(items):
        await update.message.reply_text("❌ Aisa notice number nahi hai.")
        return
    removed = items.pop(number - 1)
    save_data()
    await update.message.reply_text(f"🗑 Notice deleted.\n⏰ {removed['time']} IST\n📢 {removed['message']}")

async def settings(update, context):
    if not await admin_only(update, context):
        return
    await update.message.reply_text(
        "⚙️ BOT SETTINGS\n\n"
        f"👋 Welcome: {'ON 🟢' if DATA.get('welcome_enabled') else 'OFF 🔴'}\n"
        f"🟢 Group ON: {DATA.get('on_time') or 'Not set'} IST\n"
        f"🔴 Group OFF: {DATA.get('off_time') or 'Not set'} IST\n"
        f"📢 Scheduled notices: {len(DATA.get('notices', []))}\n\n"
        f"🎯 Target Group ID: {TARGET_GROUP_ID}\n"
        f"💬 Command Group ID: {COMMAND_GROUP_ID}"
    )

async def scheduler(application):
    print("⏰ Scheduler started.")
    last_minute = ""
    while True:
        try:
            current = now_ist()
            hhmm = current.strftime("%H:%M")
            today = current.strftime("%Y-%m-%d")
            minute_key = f"{today} {hhmm}"
            if minute_key != last_minute:
                last_minute = minute_key
                if DATA.get("on_time") == hhmm:
                    try:
                        await set_group_chat_on(application.bot)
                        print(f"🟢 Group ON at {hhmm} IST")
                    except Exception as e:
                        print(f"Group ON error: {e}")
                if DATA.get("off_time") == hhmm:
                    try:
                        await set_group_chat_off(application.bot)
                        print(f"🔴 Group OFF at {hhmm} IST")
                    except Exception as e:
                        print(f"Group OFF error: {e}")
                changed = False
                for item in DATA.get("notices", []):
                    if item.get("time") == hhmm and item.get("last_sent") != today:
                        try:
                            await application.bot.send_message(TARGET_GROUP_ID, f"📢 {item['message']}")
                            item["last_sent"] = today
                            changed = True
                            print(f"📢 Notice sent at {hhmm}: {item['message']}")
                        except Exception as e:
                            print(f"Notice error: {e}")
                if changed:
                    save_data()
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"Scheduler error: {e}")
            await asyncio.sleep(10)

async def post_init(application):
    try:
        await application.bot.delete_webhook(drop_pending_updates=False)
        print("✅ Webhook cleared")
    except Exception as e:
        print(f"Webhook clear warning: {e}")
    application.create_task(scheduler(application))
    print("🤖 Bot is ready")
    print("📡 Telegram polling started")
    print("⏰ Scheduler is running")
    print(f"🎯 TARGET_GROUP_ID: {TARGET_GROUP_ID}")
    print(f"💬 COMMAND_GROUP_ID: {COMMAND_GROUP_ID}")
    print("🇮🇳 Timezone: Asia/Kolkata")

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN Railway Variables me set nahi hai.")
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("id", show_id))
    application.add_handler(CommandHandler("welcome", welcome_command))
    application.add_handler(CommandHandler("setwelcome", set_welcome))
    application.add_handler(CommandHandler("seton", set_on))
    application.add_handler(CommandHandler("setoff", set_off))
    application.add_handler(CommandHandler("notice", notice))
    application.add_handler(CommandHandler("notices", notices))
    application.add_handler(CommandHandler("delnotice", delete_notice))
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(ChatMemberHandler(new_member, ChatMemberHandler.CHAT_MEMBER))
    print("🚀 Starting Telegram polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)

if __name__ == "__main__":
    main()
