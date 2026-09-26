import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import Application, CommandHandler, ChatMemberHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
TARGET_CHAT_ID = -1004318016710
COMMAND_CHAT_ID = -1003353359019
IST = ZoneInfo("Asia/Kolkata")
DATA_FILE = "bot_data.json"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN Railway Variables me set nahi hai.")


def empty_data():
    return {"joins": {}, "leaves": {}, "admin_links": {}, "user_links": {}}


def load_data():
    if not os.path.exists(DATA_FILE):
        return empty_data()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        base = empty_data()
        for k in base:
            if isinstance(d.get(k), dict):
                base[k] = d[k]
        # Migrate old link records to the new daily field names.
        for url, info in base["admin_links"].items():
            info.setdefault("admin_name", info.get("link_name", "Unknown"))
            info.setdefault("link_name", info.get("admin_name", "Unnamed"))
            info.setdefault("joins", 0)
            info.setdefault("leaves", 0)
            info.setdefault("daily_joins", info.get("daily", {}))
            info.setdefault("daily_leaves", {})
            info.setdefault("users", {})
        return base
    except Exception as e:
        print(f"Data load error: {e}", flush=True)
        return empty_data()


data = load_data()


def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def day_key(days_ago=0):
    return (datetime.now(IST).date() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def command_group(update):
    return bool(update.effective_chat and update.effective_chat.id == COMMAND_CHAT_ID)


async def is_admin(update, context):
    if not update.effective_chat or not update.effective_user:
        return False
    try:
        m = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        return m.status in ("administrator", "creator")
    except Exception as e:
        print(f"Admin check error: {e}", flush=True)
        return False


def ensure(info):
    info.setdefault("admin_name", info.get("link_name", "Unknown"))
    info.setdefault("link_name", info.get("admin_name", "Unnamed"))
    info.setdefault("joins", 0)
    info.setdefault("leaves", 0)
    info.setdefault("daily_joins", info.get("daily", {}))
    info.setdefault("daily_leaves", {})
    info.setdefault("users", {})


def block(info, url, day=None):
    ensure(info)
    if day:
        j = int(info["daily_joins"].get(day, 0))
        l = int(info["daily_leaves"].get(day, 0))
    else:
        j = int(info["joins"])
        l = int(info["leaves"])
    return (f"👤 Agent: {info['admin_name']}\n"
            f"🔗 Link Name: {info['link_name']}\n"
            f"🟢 Joined: {j}\n"
            f"🔴 Left: {l}\n"
            f"👥 Net: {j-l}\n"
            f"🔗 {url}\n"
            "━━━━━━━━━━━━━━━━━━━━\n")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "✅ Wintask Bot is working!\n\n"
            "📌 Commands:\n"
            "/id\n/stats\n/today\n/yesterday\n"
            "/addlink NAME LINK  ← existing link only\n"
            "/mylink\n/links"
        )


async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.effective_chat:
        c = update.effective_chat
        await update.message.reply_text(
            f"🆔 Chat ID: {c.id}\n💬 Type: {c.type}\n📌 Name: {c.title or 'Private Chat'}"
        )


async def member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member
    if not cm or cm.chat.id != TARGET_CHAT_ID:
        return
    old = cm.old_chat_member.status
    new = cm.new_chat_member.status
    user = cm.new_chat_member.user
    uid = str(user.id)
    day = day_key()
    joined_states = ("member", "administrator", "creator")
    left_states = ("left", "kicked")

    if new in joined_states and old in left_states:
        data["joins"][day] = data["joins"].get(day, 0) + 1
        invite = cm.invite_link
        if invite and invite.invite_link:
            url = invite.invite_link
            info = data["admin_links"].get(url)
            if info:
                ensure(info)
                info["joins"] += 1
                info["daily_joins"][day] = info["daily_joins"].get(day, 0) + 1
                info["users"][uid] = {"name": user.full_name, "username": f"@{user.username}" if user.username else ""}
                data["user_links"][uid] = url
                print(f"JOIN {user.full_name} -> {info['admin_name']}", flush=True)
            else:
                print(f"JOIN unknown link: {url}", flush=True)
        else:
            print(f"JOIN without invite attribution: {user.full_name}", flush=True)
        save_data()

    elif new in left_states and old in joined_states:
        data["leaves"][day] = data["leaves"].get(day, 0) + 1
        url = data["user_links"].get(uid)
        info = data["admin_links"].get(url) if url else None
        if info:
            ensure(info)
            info["leaves"] += 1
            info["daily_leaves"][day] = info["daily_leaves"].get(day, 0) + 1
            print(f"LEAVE {user.full_name} -> {info['admin_name']}", flush=True)
        else:
            print(f"LEAVE without saved attribution: {user.full_name}", flush=True)
        save_data()


async def check_access(update, context):
    if not command_group(update):
        await update.message.reply_text("❌ Is chat me commands allowed nahi hain.")
        return False
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Ye command sirf admin use kar sakta hai.")
        return False
    return True


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_access(update, context): return
    day = day_key()
    tj, tl = int(data["joins"].get(day, 0)), int(data["leaves"].get(day, 0))
    text = f"🟢 TODAY USER STATISTICS\n━━━━━━━━━━━━━━━━━━━━\n📅 Date: {day}\n\n"
    found = False
    for url, info in data["admin_links"].items():
        ensure(info); j = int(info["daily_joins"].get(day, 0)); l = int(info["daily_leaves"].get(day, 0))
        if j or l:
            found = True; text += block(info, url, day)
    if not found: text += "ℹ️ Aaj kisi registered agent link se record nahi mila.\n\n"
    text += f"📊 TOTAL\n🟢 New Users: {tj}\n🔴 Left Users: {tl}\n👥 Net Users: {tj-tl}"
    await update.message.reply_text(text)


async def yesterday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_access(update, context): return
    day = day_key(1)
    yj, yl = int(data["joins"].get(day, 0)), int(data["leaves"].get(day, 0))
    text = f"🟡 YESTERDAY USER STATISTICS\n━━━━━━━━━━━━━━━━━━━━\n📅 Date: {day}\n\n"
    found = False
    for url, info in data["admin_links"].items():
        ensure(info); j = int(info["daily_joins"].get(day, 0)); l = int(info["daily_leaves"].get(day, 0))
        if j or l:
            found = True; text += block(info, url, day)
    if not found: text += "ℹ️ Kal kisi registered agent link se record nahi mila.\n\n"
    text += f"📊 TOTAL\n🟢 New Users: {yj}\n🔴 Left Users: {yl}\n👥 Net Users: {yj-yl}"
    await update.message.reply_text(text)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_access(update, context): return
    now = datetime.now(IST).date(); yesterday_d = now - timedelta(days=1)
    week = now - timedelta(days=now.weekday()); month = now.replace(day=1)
    vals = {"today": [0,0], "yesterday": [0,0], "week": [0,0], "month": [0,0], "total": [0,0]}
    for k,v in data["joins"].items():
        try: d=datetime.strptime(k,"%Y-%m-%d").date(); n=int(v)
        except: continue
        vals["total"][0]+=n
        if d==now: vals["today"][0]+=n
        if d==yesterday_d: vals["yesterday"][0]+=n
        if week<=d<=now: vals["week"][0]+=n
        if month<=d<=now: vals["month"][0]+=n
    for k,v in data["leaves"].items():
        try: d=datetime.strptime(k,"%Y-%m-%d").date(); n=int(v)
        except: continue
        vals["total"][1]+=n
        if d==now: vals["today"][1]+=n
        if d==yesterday_d: vals["yesterday"][1]+=n
        if week<=d<=now: vals["week"][1]+=n
        if month<=d<=now: vals["month"][1]+=n
    def row(title, x): return f"📅 {title}\n🟢 Joined: {x[0]}\n🔴 Left: {x[1]}\n👥 Net: {x[0]-x[1]}\n\n"
    await update.message.reply_text("📊 GROUP USER STATISTICS\n━━━━━━━━━━━━━━━━━━━━\n\n" + row("TODAY",vals["today"])+row("YESTERDAY",vals["yesterday"])+row("THIS WEEK",vals["week"])+row("THIS MONTH",vals["month"])+row("TOTAL",vals["total"])+f"🎯 Target Group: {TARGET_CHAT_ID}")


async def addlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_access(update, context): return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Existing link aur agent name dein.\n\n/addlink Sachin https://t.me/+XXXX")
        return
    name = context.args[0].strip(); url = " ".join(context.args[1:]).strip()
    if not url.startswith(("https://t.me/", "http://t.me/")):
        await update.message.reply_text("❌ Sahi Telegram invite link dein.")
        return
    if url in data["admin_links"]:
        info=data["admin_links"][url]; ensure(info); info["admin_name"]=name; info["link_name"]=name; save_data()
        await update.message.reply_text(f"✅ Link updated.\n👤 Agent: {name}\n🔗 {url}\n📊 Purane counts safe hain.")
        return
    data["admin_links"][url] = {"admin_name":name,"link_name":name,"joins":0,"leaves":0,"daily_joins":{},"daily_leaves":{},"users":{}}
    save_data()
    await update.message.reply_text(f"✅ EXISTING LINK ADDED\n━━━━━━━━━━━━━━━━━━━━\n👤 Agent: {name}\n🔗 {url}\n🟢 Joined: 0\n🔴 Left: 0\n👥 Net: 0\n\n⚠️ Is link se aane wale NEW users {name} ke naam par count honge.")


async def links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_access(update, context): return
    if not data["admin_links"]:
        await update.message.reply_text("ℹ️ Abhi koi existing agent link register nahi hai.")
        return
    text="📊 AGENT-WISE USER STATISTICS\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for url,info in data["admin_links"].items(): text += block(info,url)
    await update.message.reply_text(text)


async def mylink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_access(update, context): return
    if not data["admin_links"]:
        await update.message.reply_text("ℹ️ Abhi koi existing agent link register nahi hai.")
        return
    text="🔗 REGISTERED AGENT LINKS\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for url,info in data["admin_links"].items(): text += block(info,url)
    await update.message.reply_text(text)


async def error_handler(update, context):
    print(f"BOT ERROR: {context.error}", flush=True)


async def post_init(application):
    me=await application.bot.get_me()
    print("========================================",flush=True)
    print("WINTASK BOT STARTED",flush=True)
    print(f"Bot: @{me.username}",flush=True)
    print(f"Target Group: {TARGET_CHAT_ID}",flush=True)
    print(f"Command Group: {COMMAND_CHAT_ID}",flush=True)
    print("Existing-link mode: ON",flush=True)
    print("New-link creation: OFF",flush=True)
    print("========================================",flush=True)


def main():
    app=Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("id",chat_id))
    app.add_handler(CommandHandler("stats",stats))
    app.add_handler(CommandHandler("today",today))
    app.add_handler(CommandHandler("yesterday",yesterday))
    app.add_handler(CommandHandler("addlink",addlink))
    app.add_handler(CommandHandler("links",links))
    app.add_handler(CommandHandler("mylink",mylink))
    app.add_handler(ChatMemberHandler(member_update,ChatMemberHandler.CHAT_MEMBER))
    app.add_error_handler(error_handler)
    print("Bot polling started...",flush=True)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
