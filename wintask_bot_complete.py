import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ChatMemberHandler,
    ContextTypes,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
TARGET_CHAT_ID = -100431801670
COMMAND_CHAT_ID = int(os.getenv("COMMAND_CHAT_ID", str(TARGET_CHAT_ID)))
IST = ZoneInfo("Asia/Kolkata")
DATA_FILE = "bot_data.json"


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN Railway Variables me set nahi hai.")


def empty_data():
    return {
        "joins": {},
        "leaves": {},
        "admin_links": {},
        "user_links": {},
    }


def load_data():
    if not os.path.exists(DATA_FILE):
        return empty_data()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        for key in empty_data():
            d.setdefault(key, {})
        return d
    except Exception as e:
        print(f"Data load error: {e}", flush=True)
        return empty_data()


data = load_data()


def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def today_key():
    return datetime.now(IST).strftime("%Y-%m-%d")


def is_command_group(update):
    return bool(
        update.effective_chat
        and update.effective_chat.id == COMMAND_CHAT_ID
    )


async def is_admin(update, context):
    if not update.effective_chat or not update.effective_user:
        return False
    try:
        m = await context.bot.get_chat_member(
            update.effective_chat.id,
            update.effective_user.id,
        )
        return m.status in ("administrator", "creator")
    except Exception:
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(
        "✅ Wintask Bot is working!\n\n"
        "📌 Commands:\n"
        "/id - Chat ID\n"
        "/stats - Complete statistics\n"
        "/today - Today's statistics\n"
        "/yesterday - Yesterday's statistics\n"
        "/addlink NAME - New admin invite link\n"
        "/addlink NAME LINK - Add existing link\n"
        "/mylink - Your links\n"
        "/links - All admin/link statistics"
    )


async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return
    c = update.effective_chat
    await update.message.reply_text(
        f"🆔 Chat ID: {c.id}\n"
        f"💬 Type: {c.type}\n"
        f"📌 Name: {c.title or 'Private Chat'}"
    )


async def member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member
    if not cm or cm.chat.id != TARGET_CHAT_ID:
        return

    old = cm.old_chat_member.status
    new = cm.new_chat_member.status
    user = cm.new_chat_member.user
    uid = str(user.id)
    day = today_key()

    joined_states = ("member", "administrator", "creator")
    left_states = ("left", "kicked")

    if new in joined_states and old in left_states:
        data["joins"][day] = data["joins"].get(day, 0) + 1

        invite = cm.invite_link
        if invite:
            url = invite.invite_link
            info = data["admin_links"].get(url)
            if info:
                info["joins"] = info.get("joins", 0) + 1
                info.setdefault("daily", {})
                info["daily"][day] = info["daily"].get(day, 0) + 1
                info.setdefault("users", {})[uid] = {
                    "name": user.full_name,
                    "username": (
                        "@" + user.username if user.username else ""
                    ),
                }
                data["user_links"][uid] = url
        save_data()

    elif new in left_states and old in joined_states:
        data["leaves"][day] = data["leaves"].get(day, 0) + 1

        url = data["user_links"].get(uid)
        info = data["admin_links"].get(url) if url else None

        if info:
            info["leaves"] = info.get("leaves", 0) + 1
            info.setdefault("daily_leaves", {})
            info["daily_leaves"][day] = (
                info["daily_leaves"].get(day, 0) + 1
            )
        save_data()


async def today_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_command_group(update):
        await update.message.reply_text("❌ Is chat me commands allowed nahi hain.")
        return
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Ye command sirf admin use kar sakta hai.")
        return

    day = today_key()
    joins = data["joins"].get(day, 0)
    leaves = data["leaves"].get(day, 0)

    text = f"🟢 TODAY USER STATISTICS\n━━━━━━━━━━━━━━━━━━━━\n📅 Date: {day}\n\n"

    found = False
    for url, info in data["admin_links"].items():
        j = info.get("daily", {}).get(day, 0)
        l = info.get("daily_leaves", {}).get(day, 0)
        if j == 0 and l == 0:
            continue
        found = True
        text += (
            f"👤 Admin: {info.get('admin_name', 'Unknown')}\n"
            f"🔗 Link Name: {info.get('link_name', 'Unnamed Link')}\n"
            f"🟢 Joined: {j}\n"
            f"🔴 Left: {l}\n"
            f"👥 Net: {j-l}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
        )

    if not found:
        text += "ℹ️ Aaj admin links se koi record nahi mila.\n\n"

    text += (
        f"📊 TOTAL\n"
        f"🟢 New Users: {joins}\n"
        f"🔴 Left Users: {leaves}\n"
        f"👥 Net Users: {joins-leaves}"
    )
    await update.message.reply_text(text)


async def yesterday_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_command_group(update):
        await update.message.reply_text("❌ Is chat me commands allowed nahi hain.")
        return
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Ye command sirf admin use kar sakta hai.")
        return

    day = (datetime.now(IST).date() - timedelta(days=1)).strftime("%Y-%m-%d")
    joins = data["joins"].get(day, 0)
    leaves = data["leaves"].get(day, 0)

    text = f"🟡 YESTERDAY USER STATISTICS\n━━━━━━━━━━━━━━━━━━━━\n📅 Date: {day}\n\n"

    found = False
    for url, info in data["admin_links"].items():
        j = info.get("daily", {}).get(day, 0)
        l = info.get("daily_leaves", {}).get(day, 0)
        if j == 0 and l == 0:
            continue
        found = True
        text += (
            f"👤 Admin: {info.get('admin_name', 'Unknown')}\n"
            f"🔗 Link Name: {info.get('link_name', 'Unnamed Link')}\n"
            f"🟢 Joined: {j}\n"
            f"🔴 Left: {l}\n"
            f"👥 Net: {j-l}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
        )

    if not found:
        text += "ℹ️ Kal admin links se koi record nahi mila.\n\n"

    text += (
        f"📊 TOTAL\n"
        f"🟢 New Users: {joins}\n"
        f"🔴 Left Users: {leaves}\n"
        f"👥 Net Users: {joins-leaves}"
    )
    await update.message.reply_text(text)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_command_group(update):
        await update.message.reply_text("❌ Is chat me commands allowed nahi hain.")
        return
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Ye command sirf admin use kar sakta hai.")
        return

    now = datetime.now(IST).date()
    yesterday = now - timedelta(days=1)
    week_start = now - timedelta(days=now.weekday())
    month_start = now.replace(day=1)

    tj = tl = yj = yl = wj = wl = mj = ml = totalj = totall = 0

    for k, n in data["joins"].items():
        try:
            d = datetime.strptime(k, "%Y-%m-%d").date()
        except ValueError:
            continue
        totalj += n
        if d == now: tj += n
        if d == yesterday: yj += n
        if week_start <= d <= now: wj += n
        if month_start <= d <= now: mj += n

    for k, n in data["leaves"].items():
        try:
            d = datetime.strptime(k, "%Y-%m-%d").date()
        except ValueError:
            continue
        totall += n
        if d == now: tl += n
        if d == yesterday: yl += n
        if week_start <= d <= now: wl += n
        if month_start <= d <= now: ml += n

    await update.message.reply_text(
        "📊 GROUP USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 TODAY\n🟢 Joined: {tj}\n🔴 Left: {tl}\n👥 Net: {tj-tl}\n\n"
        f"📅 YESTERDAY\n🟢 Joined: {yj}\n🔴 Left: {yl}\n👥 Net: {yj-yl}\n\n"
        f"📅 THIS WEEK\n🟢 Joined: {wj}\n🔴 Left: {wl}\n👥 Net: {wj-wl}\n\n"
        f"📅 THIS MONTH\n🟢 Joined: {mj}\n🔴 Left: {ml}\n👥 Net: {mj-ml}\n\n"
        f"📊 TOTAL\n🟢 Joined: {totalj}\n🔴 Left: {totall}\n👥 Net: {totalj-totall}\n\n"
        f"🆔 Group ID: {TARGET_CHAT_ID}"
    )


async def addlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_command_group(update):
        await update.message.reply_text("❌ Is chat me commands allowed nahi hain.")
        return
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Sirf group admin ye command use kar sakta hai.")
        return

    if not context.args:
        await update.message.reply_text(
            "❌ Link name dein.\n\n"
            "Naya link:\n/addlink Sachin\n\n"
            "Existing link:\n/addlink Sachin https://t.me/+XXXX"
        )
        return

    name = context.args[0].strip()
    user = update.effective_user

    if len(context.args) >= 2:
        link = context.args[1].strip()
        if not link.startswith(("https://t.me/", "http://t.me/")):
            await update.message.reply_text(
                "❌ Sahi Telegram invite link dein."
            )
            return
        if link in data["admin_links"]:
            await update.message.reply_text("❌ Ye link pehle se added hai.")
            return
    else:
        try:
            invite = await context.bot.create_chat_invite_link(
                chat_id=TARGET_CHAT_ID,
                name=name,
            )
            link = invite.invite_link
        except Exception as e:
            await update.message.reply_text(
                "❌ Invite link nahi ban paya.\n\n"
                f"Error:\n{e}\n\n"
                "⚠️ Bot group me ADMIN hona chahiye aur Invite Users permission honi chahiye."
            )
            return

    data["admin_links"][link] = {
        "admin_id": user.id,
        "admin_name": user.full_name,
        "username": "@" + user.username if user.username else "",
        "link_name": name,
        "joins": 0,
        "leaves": 0,
        "daily": {},
        "daily_leaves": {},
        "users": {},
    }
    save_data()

    await update.message.reply_text(
        "🔗 ADMIN INVITE LINK\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Admin: {user.full_name}\n"
        f"🔗 Link Name: {name}\n"
        f"🔗 Link:\n{link}\n\n"
        "📊 Joined: 0\n"
        "🔴 Left: 0\n"
        "👥 Net: 0"
    )


async def mylink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_command_group(update):
        await update.message.reply_text("❌ Is chat me commands allowed nahi hain.")
        return
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Ye command sirf admin use kar sakta hai.")
        return

    uid = update.effective_user.id
    text = "🔗 YOUR ADMIN LINKS\n━━━━━━━━━━━━━━━━━━━━\n\n"
    found = False

    for url, info in data["admin_links"].items():
        if info.get("admin_id") != uid:
            continue
        found = True
        j = info.get("joins", 0)
        l = info.get("leaves", 0)
        text += (
            f"🔗 Link Name: {info.get('link_name', 'Unnamed Link')}\n"
            f"🟢 Joined: {j}\n"
            f"🔴 Left: {l}\n"
            f"👥 Net: {j-l}\n"
            f"🔗 {url}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
        )

    if not found:
        text += "ℹ️ Aapka koi admin invite link nahi hai.\n\n/addlink NAME"

    await update.message.reply_text(text)


async def links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_command_group(update):
        await update.message.reply_text("❌ Is chat me commands allowed nahi hain.")
        return
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Ye command sirf admin use kar sakta hai.")
        return

    if not data["admin_links"]:
        await update.message.reply_text("ℹ️ Abhi koi admin invite link added nahi hai.")
        return

    text = "📊 ADMIN / LINK STATISTICS\n━━━━━━━━━━━━━━━━━━━━\n\n"

    for url, info in data["admin_links"].items():
        j = info.get("joins", 0)
        l = info.get("leaves", 0)
        text += (
            f"👤 Admin: {info.get('admin_name', 'Unknown')}\n"
            f"🔗 Link Name: {info.get('link_name', 'Unnamed Link')}\n"
            f"🟢 Joined: {j}\n"
            f"🔴 Left: {l}\n"
            f"👥 Net: {j-l}\n"
            f"🔗 {url}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
        )

    await update.message.reply_text(text)


async def error_handler(update, context):
    print(f"BOT ERROR: {context.error}", flush=True)


async def post_init(application):
    try:
        me = await application.bot.get_me()
        print("========================================", flush=True)
        print("WINTASK BOT STARTED", flush=True)
        print(f"Bot: @{me.username}", flush=True)
        print(f"Target Group: {TARGET_CHAT_ID}", flush=True)
        print(f"Command Group: {COMMAND_CHAT_ID}", flush=True)
        print("========================================", flush=True)
    except Exception as e:
        print(f"Startup error: {e}", flush=True)


def main():
    print("Starting Wintask Bot...", flush=True)

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", chat_id))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("today", today_stats))
    app.add_handler(CommandHandler("yesterday", yesterday_stats))
    app.add_handler(CommandHandler("addlink", addlink))
    app.add_handler(CommandHandler("mylink", mylink))
    app.add_handler(CommandHandler("links", links))

    app.add_handler(
        ChatMemberHandler(
            member_update,
            ChatMemberHandler.CHAT_MEMBER,
        )
    )

    app.add_error_handler(error_handler)

    print("Bot polling started...", flush=True)

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
