import os
import json
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ChatMemberHandler,
    ContextTypes,
)

# =========================
# SETTINGS
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")

# ACTUAL TARGET GROUP ID
TARGET_CHAT_ID = -1004318016710

# Optional:
# Agar command sirf ek particular group me allow karni ho
# to Railway Variables me COMMAND_CHAT_ID set karo.
# 0 = commands sabhi chats me allowed
COMMAND_CHAT_ID = int(os.getenv("COMMAND_CHAT_ID", "0"))

DATA_FILE = "bot_data.json"


# =========================
# DATA
# =========================

def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "joins": {},
            "leaves": {},
            "admin_links": {},
            "user_links": {}
        }

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        data.setdefault("joins", {})
        data.setdefault("leaves", {})
        data.setdefault("admin_links", {})
        data.setdefault("user_links", {})

        return data

    except Exception:
        return {
            "joins": {},
            "leaves": {},
            "admin_links": {},
            "user_links": {}
        }


data = load_data()


def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =========================
# DATE
# =========================

def today():
    return datetime.now().strftime("%Y-%m-%d")


def date_string(d):
    return d.strftime("%Y-%m-%d")


# =========================
# ADMIN CHECK
# =========================

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.effective_chat or not update.effective_user:
        return False

    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id,
            update.effective_user.id
        )

        return member.status in ("administrator", "creator")

    except Exception:
        return False


# =========================
# COMMAND CHAT CHECK
# =========================

def is_command_group(update: Update):

    if not update.effective_chat:
        return False

    if COMMAND_CHAT_ID == 0:
        return True

    return update.effective_chat.id == COMMAND_CHAT_ID


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "✅ WinTask Bot is working!\n\n"
        "Commands:\n"
        "/id - Current Chat ID\n"
        "/stats - Complete statistics\n"
        "/today - Today's users\n"
        "/yesterday - Yesterday's users\n"
        "/mylink - Link command help\n"
        "/addlink NAME - Create admin invite link\n"
        "/links - Admin/link-wise statistics"
    )


# =========================
# CHAT ID
# =========================

async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat = update.effective_chat

    if not chat:
        return

    if chat.type == "private":
        name = "Private Chat"
    else:
        name = chat.title or "Unknown"

    await update.message.reply_text(
        "🆔 CHAT INFORMATION\n\n"
        f"📌 Name: {name}\n"
        f"💬 Type: {chat.type}\n"
        f"🆔 Chat ID: {chat.id}"
    )


# =========================
# MEMBER JOIN / LEAVE TRACKING
# =========================

async def member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):

    cm = update.chat_member

    if not cm:
        return

    if cm.chat.id != TARGET_CHAT_ID:
        return

    old = cm.old_chat_member.status
    new = cm.new_chat_member.status

    user = cm.new_chat_member.user
    uid = str(user.id)

    # =========================
    # USER JOINED
    # =========================

    if new in ("member", "administrator") and old in (
        "left",
        "kicked",
        "restricted"
    ):

        d = today()

        data["joins"][d] = data["joins"].get(d, 0) + 1

        # Check whether this join came through one of our admin links
        invite = cm.invite_link

        if invite and invite.invite_link in data["admin_links"]:

            url = invite.invite_link
            info = data["admin_links"][url]

            info["joins"] = info.get("joins", 0) + 1

            info.setdefault("daily", {})
            info["daily"][d] = info["daily"].get(d, 0) + 1

            info.setdefault("users", {})
            info["users"][uid] = {
                "name": user.full_name,
                "username": (
                    "@" + user.username
                    if user.username
                    else ""
                )
            }

            data["user_links"][uid] = url

        save_data()
        return

    # =========================
    # USER LEFT
    # =========================

    if new in ("left", "kicked") and old in (
        "member",
        "administrator",
        "restricted"
    ):

        d = today()

        data["leaves"][d] = data["leaves"].get(d, 0) + 1

        url = data["user_links"].get(uid)

        if url and url in data["admin_links"]:

            info = data["admin_links"][url]

            info["leaves"] = info.get("leaves", 0) + 1

            info.setdefault("daily_leaves", {})
            info["daily_leaves"][d] = (
                info["daily_leaves"].get(d, 0) + 1
            )

        save_data()
        return


# =========================
# COMPLETE STATS
# =========================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_command_group(update):
        await update.message.reply_text(
            "❌ Is chat me commands allowed nahi hain."
        )
        return

    if not await is_admin(update, context):
        await update.message.reply_text(
            "❌ Ye command sirf admin use kar sakta hai."
        )
        return

    try:

        target = await context.bot.get_chat(TARGET_CHAT_ID)

        bot_member = await context.bot.get_chat_member(
            TARGET_CHAT_ID,
            context.bot.id
        )

        if bot_member.status not in ("administrator", "creator"):
            await update.message.reply_text(
                "❌ Target group me bot ADMIN nahi hai."
            )
            return

    except Exception as e:

        await update.message.reply_text(
            f"❌ Target group error:\n{e}"
        )
        return

    td = datetime.now().date()

    yd = td - timedelta(days=1)

    ws = td - timedelta(days=td.weekday())

    ms = td.replace(day=1)

    today_join = 0
    yesterday_join = 0
    week_join = 0
    month_join = 0
    total_join = 0

    today_leave = 0
    yesterday_leave = 0
    week_leave = 0
    month_leave = 0
    total_leave = 0

    # JOINS
    for k, c in data["joins"].items():

        try:
            d = datetime.strptime(k, "%Y-%m-%d").date()
        except Exception:
            continue

        total_join += c

        if d == td:
            today_join += c

        if d == yd:
            yesterday_join += c

        if ws <= d <= td:
            week_join += c

        if ms <= d <= td:
            month_join += c

    # LEAVES
    for k, c in data["leaves"].items():

        try:
            d = datetime.strptime(k, "%Y-%m-%d").date()
        except Exception:
            continue

        total_leave += c

        if d == td:
            today_leave += c

        if d == yd:
            yesterday_leave += c

        if ws <= d <= td:
            week_leave += c

        if ms <= d <= td:
            month_leave += c

    await update.message.reply_text(
        "📊 GROUP USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"👥 Group:\n{target.title}\n\n"

        f"📅 TODAY\n"
        f"🟢 Joined: {today_join}\n"
        f"🔴 Left: {today_leave}\n"
        f"👥 Net: {today_join - today_leave}\n\n"

        f"📅 YESTERDAY\n"
        f"🟢 Joined: {yesterday_join}\n"
        f"🔴 Left: {yesterday_leave}\n"
        f"👥 Net: {yesterday_join - yesterday_leave}\n\n"

        f"📅 THIS WEEK\n"
        f"🟢 Joined: {week_join}\n"
        f"🔴 Left: {week_leave}\n"
        f"👥 Net: {week_join - week_leave}\n\n"

        f"📅 THIS MONTH\n"
        f"🟢 Joined: {month_join}\n"
        f"🔴 Left: {month_leave}\n"
        f"👥 Net: {month_join - month_leave}\n\n"

        f"📊 TOTAL\n"
        f"🟢 Joined: {total_join}\n"
        f"🔴 Left: {total_leave}\n"
        f"👥 Net: {total_join - total_leave}\n\n"

        f"🆔 Group ID:\n{TARGET_CHAT_ID}"
    )


# =========================
# TODAY
# =========================

async def today_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_command_group(update):
        await update.message.reply_text(
            "❌ Is chat me commands allowed nahi hain."
        )
        return

    if not await is_admin(update, context):
        await update.message.reply_text(
            "❌ Ye command sirf admin use kar sakta hai."
        )
        return

    d = today()

    joins = data["joins"].get(d, 0)
    leaves = data["leaves"].get(d, 0)

    await update.message.reply_text(
        "🟢 TODAY USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 Date: {d}\n\n"
        f"🟢 New Users: {joins}\n"
        f"🔴 Left Users: {leaves}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Net Users: {joins - leaves}"
    )


# =========================
# YESTERDAY
# =========================

async def yesterday_stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_command_group(update):
        await update.message.reply_text(
            "❌ Is chat me commands allowed nahi hain."
        )
        return

    if not await is_admin(update, context):
        await update.message.reply_text(
            "❌ Ye command sirf admin use kar sakta hai."
        )
        return

    d = date_string(
        datetime.now().date() - timedelta(days=1)
    )

    joins = data["joins"].get(d, 0)
    leaves = data["leaves"].get(d, 0)

    await update.message.reply_text(
        "🔵 YESTERDAY USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 Date: {d}\n\n"
        f"🟢 New Users: {joins}\n"
        f"🔴 Left Users: {leaves}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Net Users: {joins - leaves}"
    )


# =========================
# MY LINK HELP
# =========================

async def mylink(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🔗 NEW ADMIN LINK\n\n"
        "Named invite link banane ke liye:\n\n"
        "/addlink LINK_NAME\n\n"
        "Example:\n"
        "/addlink Jaipur Team\n\n"
        "⚠️ Bot ko target group me ADMIN hona chahiye "
        "aur Invite Users permission honi chahiye."
    )


# =========================
# ADD LINK
# =========================

async def addlink(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_command_group(update):
        await update.message.reply_text(
            "❌ Is chat me commands allowed nahi hain."
        )
        return

    if not await is_admin(update, context):
        await update.message.reply_text(
            "❌ Sirf admin naya invite link bana sakta hai."
        )
        return

    if not context.args:

        await update.message.reply_text(
            "❌ Link ka naam dena zaroori hai.\n\n"
            "Example:\n"
            "/addlink Jaipur Team"
        )
        return

    name = " ".join(context.args).strip()

    if not name:

        await update.message.reply_text(
            "❌ Link name khaali nahi ho sakta."
        )
        return

    user = update.effective_user

    try:

        invite = await context.bot.create_chat_invite_link(
            chat_id=TARGET_CHAT_ID,
            name=name
        )

        link = invite.invite_link

        data["admin_links"][link] = {
            "admin_id": user.id,
            "admin_name": user.full_name,
            "username": (
                "@" + user.username
                if user.username
                else ""
            ),
            "link_name": name,
            "joins": 0,
            "leaves": 0,
            "daily": {},
            "daily_leaves": {},
            "users": {}
        }

        save_data()

        await update.message.reply_text(
            "🔗 NEW ADMIN INVITE LINK\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"

            f"👤 Admin: {user.full_name}\n\n"
            f"📌 Link Name: {name}\n\n"
            f"🔗 Link:\n{link}\n\n"

            "📊 Statistics:\n"
            "🟢 Joined: 0\n"
            "🔴 Left: 0\n"
            "👥 Net: 0"
        )

    except Exception as e:

        await update.message.reply_text(
            "❌ Invite link nahi ban paya.\n\n"
            f"Error:\n{e}\n\n"
            "⚠️ Check karein:\n"
            "• Bot target group me ADMIN hai\n"
            "• Bot ko Invite Users permission hai\n"
            "• TARGET_CHAT_ID sahi hai"
        )


# =========================
# LINKS STATISTICS
# =========================

async def links(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_command_group(update):
        await update.message.reply_text(
            "❌ Is chat me commands allowed nahi hain."
        )
        return

    if not await is_admin(update, context):
        await update.message.reply_text(
            "❌ Ye report sirf admin dekh sakta hai."
        )
        return

    if not data["admin_links"]:

        await update.message.reply_text(
            "📊 ADMIN / LINK-WISE STATISTICS\n\n"
            "Abhi koi admin invite link nahi bana hai."
        )
        return

    text = (
        "📊 ADMIN / LINK-WISE STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    for i, (link, info) in enumerate(
        data["admin_links"].items(),
        1
    ):

        admin = info.get(
            "admin_name",
            "Unknown Admin"
        )

        username = info.get(
            "username",
            ""
        )

        name = info.get(
            "link_name",
            "Unnamed Link"
        )

        joins = info.get(
            "joins",
            0
        )

        leaves = info.get(
            "leaves",
            0
        )

        text += f"👤 {i}. {admin}\n"

        if username:
            text += f"🆔 {username}\n"

        text += (
            f"📌 Link Name: {name}\n\n"
            f"🟢 Joined: {joins}\n"
            f"🔴 Left: {leaves}\n"
            f"👥 Net: {joins - leaves}\n"
            f"🔗 {link}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
        )

    text += (
        "📌 Joined = is link se group me aaye users\n"
        "📌 Left = is link se aaye users me se leave karne wale\n"
        "📌 Net = Joined - Left"
    )

    await update.message.reply_text(text)


# =========================
# ERROR HANDLER
# =========================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    print("ERROR:", context.error)


# =========================
# MAIN
# =========================

def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN variable missing!"
        )

    print("🤖 Starting WinTask Bot...")

    print(
        f"🎯 Target Group ID: {TARGET_CHAT_ID}"
    )

    print(
        f"💬 Command Chat ID: {COMMAND_CHAT_ID}"
    )

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

    app.add_handler(
        CommandHandler("today", today_stats)
    )

    app.add_handler(
        CommandHandler("yesterday", yesterday_stats)
    )

    app.add_handler(
        CommandHandler("mylink", mylink)
    )

    app.add_handler(
        CommandHandler("addlink", addlink)
    )

    app.add_handler(
        CommandHandler("links", links)
    )

    # Join / Leave tracking
    app.add_handler(
        ChatMemberHandler(
            member_update,
            ChatMemberHandler.CHAT_MEMBER
        )
    )

    app.add_error_handler(error_handler)

    print("✅ Bot started successfully.")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
