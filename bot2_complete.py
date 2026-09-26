import os
import json
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update, ChatPermissions
from telegram.ext import Application, CommandHandler, ChatMemberHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "0"))
IST = ZoneInfo("Asia/Kolkata")
DATA_FILE = "welcome_notice_data.json"

DEFAULT_WELCOME = (
    "👋 Welcome {mention}!\n\n"
    "🎉 Welcome to our group.\n"
    "Please follow the group rules and stay active. ❤️"
)

def load_data():
    default = {
        "welcome_enabled": True,
        "welcome_message": DEFAULT_WELCOME,
        "on_time": "09:00",
        "off_time": "22:00",
        "notices": []
    }
    if not os.path.exists(DATA_FILE):
        return default
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        for k, v in default.items():
            d.setdefault(k, v)
        return d
    except Exception:
        return default

data = load_data()

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def now_ist():
    return datetime.now(IST)

def valid_time(value):
    try:
        datetime.strptime(value, "%H:%M")
        return True
    except ValueError:
        return False

async def is_admin(update, context):
    if not update.effective_user or not update.effective_chat:
        return False
    try:
        m = await context.bot.get_chat_member(
            update.effective_chat.id, update.effective_user.id
        )
        return m.status in ("administrator", "creator")
    except Exception:
        return False

async def admin_only(update, context):
    if not await is_admin(update, context):
        if update.message:
            await update.message.reply_text("❌ Sirf group admins ye command use kar sakte hain.")
        return False
    return True

async def start(update, context):
    await update.message.reply_text(
        "🤖 Work From Home Bot\n\n"
        "👋 New member welcome\n"
        "🔓 Scheduled chat ON\n"
        "🔒 Scheduled chat OFF\n"
        "📢 Automatic notices\n\n"
        "Admin Commands:\n"
        "/id\n/welcome on|off\n/setwelcome MESSAGE\n"
        "/seton HH:MM\n/setoff HH:MM\n"
        "/notice HH:MM MESSAGE\n/notices\n/delnotice NUMBER\n/settings"
    )

async def get_id(update, context):
    await update.message.reply_text(
        f"🆔 Group Chat ID:\n<code>{update.effective_chat.id}</code>",
        parse_mode="HTML"
    )

async def welcome(update, context):
    if not await admin_only(update, context):
        return
    if not context.args:
        status = "ON ✅" if data["welcome_enabled"] else "OFF ❌"
        await update.message.reply_text(
            f"👋 Welcome: <b>{status}</b>\n\n/welcome on\n/welcome off",
            parse_mode="HTML"
        )
        return
    value = context.args[0].lower()
    if value == "on":
        data["welcome_enabled"] = True
    elif value == "off":
        data["welcome_enabled"] = False
    else:
        await update.message.reply_text("Use: /welcome on or /welcome off")
        return
    save_data()
    await update.message.reply_text("👋 Welcome message: " + ("ON ✅" if data["welcome_enabled"] else "OFF ❌"))

async def set_welcome(update, context):
    if not await admin_only(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "Example:\n/setwelcome 👋 Welcome {mention} to our group!"
        )
        return
    msg = " ".join(context.args)
    if "{mention}" not in msg:
        msg += "\n\n{mention}"
    data["welcome_message"] = msg
    save_data()
    await update.message.reply_text("✅ Welcome message save ho gaya.")

async def new_member(update, context):
    if not update.chat_member or update.chat_member.chat.id != GROUP_CHAT_ID:
        return
    old_status = update.chat_member.old_chat_member.status
    new_status = update.chat_member.new_chat_member.status
    joined = {"member", "administrator", "creator"}
    if new_status not in joined or old_status in joined:
        return
    user = update.chat_member.new_chat_member.user
    if user.is_bot or not data.get("welcome_enabled", True):
        return
    text = data.get("welcome_message", DEFAULT_WELCOME).replace(
        "{mention}", user.mention_html()
    )
    try:
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID, text=text, parse_mode="HTML"
        )
    except Exception as e:
        print("Welcome error:", repr(e))

async def set_on(update, context):
    if not await admin_only(update, context):
        return
    if not context.args or not valid_time(context.args[0]):
        await update.message.reply_text("❌ Example: /seton 09:00")
        return
    data["on_time"] = context.args[0]
    save_data()
    await update.message.reply_text(f"🔓 Chat ON time: {data['on_time']} IST")

async def set_off(update, context):
    if not await admin_only(update, context):
        return
    if not context.args or not valid_time(context.args[0]):
        await update.message.reply_text("❌ Example: /setoff 22:00")
        return
    data["off_time"] = context.args[0]
    save_data()
    await update.message.reply_text(f"🔒 Chat OFF time: {data['off_time']} IST")

def chat_on_permissions():
    return ChatPermissions(
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

def chat_off_permissions():
    return ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_add_web_page_previews=False,
        can_invite_users=False
    )

async def set_group_permissions(application, allow):
    try:
        await application.bot.set_chat_permissions(
            chat_id=GROUP_CHAT_ID,
            permissions=chat_on_permissions() if allow else chat_off_permissions(),
            use_independent_chat_permissions=True
        )
        print("GROUP CHAT:", "ON" if allow else "OFF", now_ist().strftime("%Y-%m-%d %H:%M:%S"))
    except Exception as e:
        print("Permission change error:", repr(e))

async def notice(update, context):
    if not await admin_only(update, context):
        return
    if len(context.args) < 2 or not valid_time(context.args[0]):
        await update.message.reply_text(
            "❌ Example:\n/notice 20:00 📢 Important notice"
        )
        return
    t = context.args[0]
    msg = " ".join(context.args[1:])
    data["notices"].append({"time": t, "message": msg})
    save_data()
    await update.message.reply_text(f"✅ Notice #{len(data['notices'])} added. {t} IST")

async def notices(update, context):
    if not await admin_only(update, context):
        return
    if not data["notices"]:
        await update.message.reply_text("📢 Abhi koi notice set nahi hai.")
        return
    lines = ["📢 Scheduled Notices\n"]
    for i, item in enumerate(data["notices"], 1):
        lines.append(f"#{i}  🕐 {item['time']} IST\n📢 {item['message']}\n")
    await update.message.reply_text("\n".join(lines))

async def delete_notice(update, context):
    if not await admin_only(update, context):
        return
    if not context.args:
        await update.message.reply_text("❌ Example: /delnotice 1")
        return
    try:
        n = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Number galat hai.")
        return
    if n < 1 or n > len(data["notices"]):
        await update.message.reply_text("❌ Aisa notice number nahi hai.")
        return
    removed = data["notices"].pop(n - 1)
    save_data()
    await update.message.reply_text(f"🗑 Notice #{n} delete ho gaya.\n{removed['message']}")

async def settings(update, context):
    if not await admin_only(update, context):
        return
    await update.message.reply_text(
        "⚙️ Bot Settings\n\n"
        f"👋 Welcome: {'ON ✅' if data['welcome_enabled'] else 'OFF ❌'}\n"
        f"🔓 Chat ON: {data['on_time']} IST\n"
        f"🔒 Chat OFF: {data['off_time']} IST\n"
        f"📢 Notices: {len(data['notices'])}\n"
        f"🆔 Group ID: {GROUP_CHAT_ID}"
    )

async def scheduler(application):
    last_on = None
    last_off = None
    sent = set()
    while True:
        try:
            cur = now_ist()
            tm = cur.strftime("%H:%M")
            day = cur.strftime("%Y-%m-%d")

            if tm == data["on_time"] and last_on != day:
                await set_group_permissions(application, True)
                last_on = day

            if tm == data["off_time"] and last_off != day:
                await set_group_permissions(application, False)
                last_off = day

            for i, item in enumerate(data.get("notices", [])):
                key = f"{day}:{i}:{item['time']}:{item['message']}"
                if tm == item["time"] and key not in sent:
                    await application.bot.send_message(
                        chat_id=GROUP_CHAT_ID, text=item["message"]
                    )
                    sent.add(key)

            if len(sent) > 1000:
                sent = {x for x in sent if x.startswith(day + ":")}

        except Exception as e:
            print("Scheduler error:", repr(e))

        await asyncio.sleep(20)

async def post_init(application):
    print("🤖 Second Bot Started...")
    print("🆔 GROUP_CHAT_ID:", GROUP_CHAT_ID)
    print("🇮🇳 Timezone: Asia/Kolkata")
    try:
        await application.bot.delete_webhook(drop_pending_updates=False)
        print("✅ Webhook cleared")
    except Exception as e:
        print("Webhook clear:", repr(e))
    application.create_task(scheduler(application))

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN Railway Variables me set nahi hai.")
    if GROUP_CHAT_ID == 0:
        raise RuntimeError("GROUP_CHAT_ID Railway Variables me set nahi hai.")

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("id", get_id))
    application.add_handler(CommandHandler("welcome", welcome))
    application.add_handler(CommandHandler("setwelcome", set_welcome))
    application.add_handler(CommandHandler("seton", set_on))
    application.add_handler(CommandHandler("setoff", set_off))
    application.add_handler(CommandHandler("notice", notice))
    application.add_handler(CommandHandler("notices", notices))
    application.add_handler(CommandHandler("delnotice", delete_notice))
    application.add_handler(CommandHandler("settings", settings))

    application.add_handler(
        ChatMemberHandler(new_member, ChatMemberHandler.CHAT_MEMBER)
    )

    print("🚀 Starting Telegram polling...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False
    )

if __name__ == "__main__":
    main()
