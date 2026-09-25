import os
import json
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ChatMemberHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
TARGET_CHAT_ID = -100431801671
COMMAND_CHAT_ID = int(os.getenv("COMMAND_CHAT_ID", "0"))
DATA_FILE = "bot_data.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"joins": {}, "leaves": {}, "admin_links": {}, "user_links": {}}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("joins", {})
        data.setdefault("leaves", {})
        data.setdefault("admin_links", {})
        data.setdefault("user_links", {})
        return data
    except Exception:
        return {"joins": {}, "leaves": {}, "admin_links": {}, "user_links": {}}

data = load_data()

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def today():
    return datetime.now().strftime("%Y-%m-%d")

def date_string(d):
    return d.strftime("%Y-%m-%d")

async def is_admin(update, context):
    if not update.effective_chat or not update.effective_user:
        return False
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False

def is_command_group(update):
    if not update.effective_chat:
        return False
    return COMMAND_CHAT_ID == 0 or update.effective_chat.id == COMMAND_CHAT_ID

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ Wintask Bot is working!\n\n"
        "Commands:\n"
        "/id - Current chat ID\n"
        "/stats - Complete statistics\n"
        "/today - Today's users\n"
        "/yesterday - Yesterday's users\n"
        "/mylink - Link command help\n"
        "/addlink NAME - Create named admin link\n"
        "/links - Admin/link-wise statistics"
    )

async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat:
        return
    name = "Private Chat" if chat.type == "private" else (chat.title or "Unknown")
    await update.message.reply_text(
        "🆔 CHAT INFORMATION\n\n"
        f"📌 Name: {name}\n"
        f"💬 Type: {chat.type}\n"
        f"🆔 Chat ID: {chat.id}"
    )

async def member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member
    if not cm or cm.chat.id != TARGET_CHAT_ID:
        return
    old = cm.old_chat_member.status
    new = cm.new_chat_member.status
    user = cm.new_chat_member.user
    uid = str(user.id)

    if new in ("member", "administrator") and old in ("left", "kicked"):
        d = today()
        data["joins"][d] = data["joins"].get(d, 0) + 1
        invite = cm.invite_link
        if invite and invite.invite_link in data["admin_links"]:
            url = invite.invite_link
            info = data["admin_links"][url]
            info["joins"] = info.get("joins", 0) + 1
            info.setdefault("daily", {})[d] = info.setdefault("daily", {}).get(d, 0) + 1
            data["user_links"][uid] = url
            info.setdefault("users", {})[uid] = {
                "name": user.full_name,
                "username": "@" + user.username if user.username else ""
            }
        save_data()
        return

    if new in ("left", "kicked") and old in ("member", "administrator"):
        d = today()
        data["leaves"][d] = data["leaves"].get(d, 0) + 1
        url = data["user_links"].get(uid)
        if url and url in data["admin_links"]:
            info = data["admin_links"][url]
            info["leaves"] = info.get("leaves", 0) + 1
            info.setdefault("daily_leaves", {})[d] = info.setdefault("daily_leaves", {}).get(d, 0) + 1
        save_data()

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_command_group(update):
        await update.message.reply_text("❌ इस chat में commands allowed नहीं हैं.")
        return
    if not await is_admin(update, context):
        await update.message.reply_text("❌ यह command सिर्फ admin use कर सकता है.")
        return
    try:
        target = await context.bot.get_chat(TARGET_CHAT_ID)
        bot_member = await context.bot.get_chat_member(TARGET_CHAT_ID, context.bot.id)
        if bot_member.status not in ("administrator", "creator"):
            await update.message.reply_text("❌ Bot target group में ADMIN नहीं है.")
            return
    except Exception as e:
        await update.message.reply_text(f"❌ Target group error:\n{e}")
        return

    td = datetime.now().date()
    yd = td - timedelta(days=1)
    ws = td - timedelta(days=td.weekday())
    ms = td.replace(day=1)
    tj = yj = wj = mj = totalj = 0
    tl = yl = wl = ml = totall = 0
    for k, c in data["joins"].items():
        try: d = datetime.strptime(k, "%Y-%m-%d").date()
        except Exception: continue
        totalj += c
        if d == td: tj += c
        if d == yd: yj += c
        if ws <= d <= td: wj += c
        if ms <= d <= td: mj += c
    for k, c in data["leaves"].items():
        try: d = datetime.strptime(k, "%Y-%m-%d").date()
        except Exception: continue
        totall += c
        if d == td: tl += c
        if d == yd: yl += c
        if ws <= d <= td: wl += c
        if ms <= d <= td: ml += c
    await update.message.reply_text(
        "📊 GROUP USER STATISTICS\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Group:\n{target.title}\n\n"
        f"📅 TODAY\n🟢 Joined: {tj}\n🔴 Left: {tl}\n⚪ Net: {tj-tl}\n\n"
        f"📅 YESTERDAY\n🟢 Joined: {yj}\n🔴 Left: {yl}\n⚪ Net: {yj-yl}\n\n"
        f"📅 THIS WEEK\n🟢 Joined: {wj}\n🔴 Left: {wl}\n⚪ Net: {wj-wl}\n\n"
        f"📅 THIS MONTH\n🟢 Joined: {mj}\n🔴 Left: {ml}\n⚪ Net: {mj-ml}\n\n"
        f"📊 TOTAL\n🟢 Joined: {totalj}\n🔴 Left: {totall}\n⚪ Net: {totalj-totall}\n\n"
        f"🆔 Group ID:\n{TARGET_CHAT_ID}"
    )

async def today_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_command_group(update):
        await update.message.reply_text("❌ इस chat में commands allowed नहीं हैं."); return
    if not await is_admin(update, context):
        await update.message.reply_text("❌ यह command सिर्फ admin use कर सकता है."); return
    d = datetime.now().date(); k = date_string(d)
    j = data["joins"].get(k, 0); l = data["leaves"].get(k, 0)
    await update.message.reply_text(
        "🟢 TODAY USER STATISTICS\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 Date: {d.strftime('%d-%m-%Y')}\n\n"
        f"🟢 New Users: {j}\n🔴 Left Users: {l}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n👥 Net Users: {j-l}"
    )

async def yesterday_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_command_group(update):
        await update.message.reply_text("❌ इस chat में commands allowed नहीं हैं."); return
    if not await is_admin(update, context):
        await update.message.reply_text("❌ यह command सिर्फ admin use कर सकता है."); return
    d = datetime.now().date() - timedelta(days=1); k = date_string(d)
    j = data["joins"].get(k, 0); l = data["leaves"].get(k, 0)
    await update.message.reply_text(
        "🟡 YESTERDAY USER STATISTICS\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 Date: {d.strftime('%d-%m-%Y')}\n\n"
        f"🟢 New Users: {j}\n🔴 Left Users: {l}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n👥 Net Users: {j-l}"
    )

async def addlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_command_group(update):
        await update.message.reply_text("❌ इस chat में commands allowed नहीं हैं."); return
    if not await is_admin(update, context):
        await update.message.reply_text("❌ सिर्फ admin नया invite link बना सकता है."); return
    if not context.args:
        await update.message.reply_text("❌ Link का नाम दें.\n\nExample:\n/addlink Jaipur Team"); return
    name = " ".join(context.args).strip()
    if not name:
        await update.message.reply_text("❌ Link name खाली नहीं हो सकता."); return
    user = update.effective_user
    try:
        invite = await context.bot.create_chat_invite_link(chat_id=TARGET_CHAT_ID, name=name)
        link = invite.invite_link
        data["admin_links"][link] = {
            "admin_id": user.id,
            "admin_name": user.full_name,
            "username": "@" + user.username if user.username else "",
            "link_name": name,
            "joins": 0,
            "leaves": 0,
            "daily": {},
            "daily_leaves": {},
            "users": {}
        }
        save_data()
        await update.message.reply_text(
            "🔗 NEW ADMIN INVITE LINK\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Admin:\n{user.full_name}\n\n"
            f"🏷 Link Name:\n{name}\n\n"
            f"🔗 Link:\n{link}\n\n"
            "📊 Statistics:\n🟢 Joined: 0\n🔴 Left: 0\n⚪ Net: 0"
        )
    except Exception as e:
        await update.message.reply_text(
            "❌ Invite link नहीं बन पाया.\n\n"
            f"Error:\n{e}\n\n"
            "⚠️ Bot को target group में ADMIN बनाएं और Invite Users permission दें."
        )

async def mylink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ नया named link बनाने के लिए:\n\n"
        "/addlink LINK_NAME\n\nExample:\n/addlink Jaipur Team"
    )

async def links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_command_group(update):
        await update.message.reply_text("❌ इस chat में commands allowed नहीं हैं."); return
    if not await is_admin(update, context):
        await update.message.reply_text("❌ सिर्फ admin यह report देख सकता है."); return
    if not data["admin_links"]:
        await update.message.reply_text("📊 ADMIN / LINK-WISE STATISTICS\n\nअभी कोई admin invite link नहीं बना है."); return
    text = "📊 ADMIN / LINK-WISE STATISTICS\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, (link, info) in enumerate(data["admin_links"].items(), 1):
        admin = info.get("admin_name", "Unknown Admin")
        username = info.get("username", "")
        name = info.get("link_name", "Unnamed Link")
        joins = info.get("joins", 0)
        leaves = info.get("leaves", 0)
        text += f"👤 {i}. {admin}\n"
        if username: text += f"🔹 {username}\n"
        text += (
            f"🏷 Link Name: {name}\n\n"
            f"🟢 Joined: {joins}\n"
            f"🔴 Left: {leaves}\n"
            f"⚪ Net: {joins-leaves}\n\n"
            f"🔗 {link}\n\n━━━━━━━━━━━━━━━━━━━━\n\n"
        )
    text += "📌 Joined = इस link से आने वाले users\n📌 Left = इस link से आए users में से leave करने वाले\n📌 Net = Joined - Left"
    await update.message.reply_text(text)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("ERROR:", context.error)

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN variable missing!")
    print("🤖 Bot started...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", chat_id))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("today", today_stats))
    app.add_handler(CommandHandler("yesterday", yesterday_stats))
    app.add_handler(CommandHandler("mylink", mylink))
    app.add_handler(CommandHandler("addlink", addlink))
    app.add_handler(CommandHandler("links", links))
    app.add_handler(ChatMemberHandler(member_update, ChatMemberHandler.CHAT_MEMBER))
    app.add_error_handler(error_handler)
    print(f"🎯 Target Group: {TARGET_CHAT_ID}")
    print(f"💬 Command Group: {COMMAND_CHAT_ID if COMMAND_CHAT_ID else 'admin-only in any chat'}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
