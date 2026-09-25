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

# =========================================================
# SETTINGS
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

# YOUR CORRECT TARGET GROUP ID
TARGET_CHAT_ID = -1004318016710

# 0 = commands can work in any chat where user is admin
# You can change this to your command-group ID if needed.
COMMAND_CHAT_ID = int(os.getenv("COMMAND_CHAT_ID", "0"))

DATA_FILE = "bot_data.json"


# =========================================================
# DATA
# =========================================================

def empty_data():
    return {
        "joins": {},
        "leaves": {},
        "admin_links": {},
        "user_links": {}
    }


def load_data():
    if not os.path.exists(DATA_FILE):
        return empty_data()

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        data.setdefault("joins", {})
        data.setdefault("leaves", {})
        data.setdefault("admin_links", {})
        data.setdefault("user_links", {})

        return data

    except Exception:
        return empty_data()


data = load_data()


def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


# =========================================================
# DATE HELPERS
# =========================================================

def today():
    return datetime.now().strftime("%Y-%m-%d")


def date_string(d):
    return d.strftime("%Y-%m-%d")


# =========================================================
# ADMIN CHECK
# =========================================================

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


# =========================================================
# COMMAND CHAT CHECK
# =========================================================

def is_command_group(update: Update):

    if not update.effective_chat:
        return False

    if COMMAND_CHAT_ID == 0:
        return True

    return update.effective_chat.id == COMMAND_CHAT_ID


# =========================================================
# /start
# =========================================================

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
        "/addlink NAME LINK - Save an existing link\n"
        "/links - Admin/link-wise statistics"
    )


# =========================================================
# /id
# =========================================================

async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat = update.effective_chat

    if not chat:
        return

    name = (
        "Private Chat"
        if chat.type == "private"
        else (chat.title or "Unknown")
    )

    await update.message.reply_text(
        "🆔 CHAT INFORMATION\n\n"
        f"📌 Name: {name}\n"
        f"💬 Type: {chat.type}\n"
        f"🆔 Chat ID: {chat.id}"
    )


# =========================================================
# MEMBER JOIN / LEAVE TRACKING
# =========================================================

async def member_update(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    cm = update.chat_member

    if not cm:
        return

    # Only target group
    if cm.chat.id != TARGET_CHAT_ID:
        return

    old_status = cm.old_chat_member.status
    new_status = cm.new_chat_member.status

    user = cm.new_chat_member.user
    uid = str(user.id)

    # -----------------------------------------------------
    # USER JOINED
    # -----------------------------------------------------

    if (
        new_status in ("member", "administrator")
        and old_status in ("left", "kicked")
    ):

        d = today()

        data["joins"][d] = data["joins"].get(d, 0) + 1

        # Telegram tells us which invite link was used
        invite = cm.invite_link

        if invite and invite.invite_link:

            url = invite.invite_link

            if url in data["admin_links"]:

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

                # Remember user's last invite link
                data["user_links"][uid] = url

        save_data()

        return

    # -----------------------------------------------------
    # USER LEFT / KICKED
    # -----------------------------------------------------

    if (
        new_status in ("left", "kicked")
        and old_status in ("member", "administrator")
    ):

        d = today()

        data["leaves"][d] = data["leaves"].get(d, 0) + 1

        # Use saved invite link of this user
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


# =========================================================
# /stats
# =========================================================

async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_command_group(update):
        await update.message.reply_text(
            "❌ इस chat में commands allowed नहीं हैं।"
        )
        return

    if not await is_admin(update, context):
        await update.message.reply_text(
            "❌ यह command सिर्फ admin use कर सकता है।"
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
                "❌ Bot target group में ADMIN नहीं है।"
            )
            return

    except Exception as e:

        await update.message.reply_text(
            f"❌ Target group error:\n{e}\n\n"
            "⚠️ Bot को target group में ADMIN बनाएं "
            "और Invite Users permission दें।"
        )

        return

    td = datetime.now().date()

    yesterday = td - timedelta(days=1)

    week_start = td - timedelta(days=td.weekday())

    month_start = td.replace(day=1)

    today_join = 0
    today_leave = 0

    yesterday_join = 0
    yesterday_leave = 0

    week_join = 0
    week_leave = 0

    month_join = 0
    month_leave = 0

    total_join = 0
    total_leave = 0

    # JOIN DATA
    for k, c in data["joins"].items():

        try:
            d = datetime.strptime(
                k,
                "%Y-%m-%d"
            ).date()

        except Exception:
            continue

        total_join += c

        if d == td:
            today_join += c

        if d == yesterday:
            yesterday_join += c

        if week_start <= d <= td:
            week_join += c

        if month_start <= d <= td:
            month_join += c

    # LEAVE DATA
    for k, c in data["leaves"].items():

        try:
            d = datetime.strptime(
                k,
                "%Y-%m-%d"
            ).date()

        except Exception:
            continue

        total_leave += c

        if d == td:
            today_leave += c

        if d == yesterday:
            yesterday_leave += c

        if week_start <= d <= td:
            week_leave += c

        if month_start <= d <= td:
            month_leave += c

    total_net = total_join - total_leave

    await update.message.reply_text(
        "📊 GROUP USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"👥 Group:\n"
        f"{target.title}\n\n"

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
        f"👥 Net: {total_net}\n\n"

        f"🆔 Group ID: {TARGET_CHAT_ID}"
    )


# =========================================================
# /today
# =========================================================

async def today_stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_command_group(update):
        await update.message.reply_text(
            "❌ इस chat में commands allowed नहीं हैं।"
        )
        return

    if not await is_admin(update, context):
        await update.message.reply_text(
            "❌ यह command सिर्फ admin use कर सकता है।"
        )
        return

    d = today()

    joins = data["joins"].get(d, 0)

    leaves = data["leaves"].get(d, 0)

    net = joins - leaves

    await update.message.reply_text(
        "🟢 TODAY USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 Date: {datetime.now().strftime('%d-%m-%Y')}\n\n"
        f"🟢 New Users: {joins}\n"
        f"🔴 Left Users: {leaves}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Net Users: {net}"
    )


# =========================================================
# /yesterday
# =========================================================

async def yesterday_stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_command_group(update):
        await update.message.reply_text(
            "❌ इस chat में commands allowed नहीं हैं।"
        )
        return

    if not await is_admin(update, context):
        await update.message.reply_text(
            "❌ यह command सिर्फ admin use कर सकता है।"
        )
        return

    d = datetime.now().date() - timedelta(days=1)

    k = date_string(d)

    joins = data["joins"].get(k, 0)

    leaves = data["leaves"].get(k, 0)

    net = joins - leaves

    await update.message.reply_text(
        "🟡 YESTERDAY USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 Date: {d.strftime('%d-%m-%Y')}\n\n"
        f"🟢 New Users: {joins}\n"
        f"🔴 Left Users: {leaves}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Net Users: {net}"
    )


# =========================================================
# /mylink
# =========================================================

async def mylink(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🔗 नया named invite link बनाने के लिए:\n\n"
        "/addlink LINK_NAME\n\n"
        "Example:\n"
        "/addlink Jaipur Team\n\n"
        "Existing Telegram link save करने के लिए:\n"
        "/addlink LINK_NAME LINK\n\n"
        "Example:\n"
        "/addlink Sachin https://t.me/+xxxxxxxx"
    )


# =========================================================
# /addlink
# =========================================================

async def addlink(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_command_group(update):

        await update.message.reply_text(
            "❌ इस chat में commands allowed नहीं हैं।"
        )

        return

    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ सिर्फ admin नया invite link बना सकता है।"
        )

        return

    if not context.args:

        await update.message.reply_text(
            "❌ Link name दें।\n\n"
            "Example:\n"
            "/addlink Jaipur Team"
        )

        return

    # =====================================================
    # EXISTING LINK MODE
    # /addlink NAME https://t.me/...
    # =====================================================

    if len(context.args) >= 2:

        possible_url = context.args[-1]

        if possible_url.startswith("https://t.me/"):

            name = " ".join(context.args[:-1]).strip()

            if not name:

                await update.message.reply_text(
                    "❌ Link name missing है।"
                )

                return

            url = possible_url

            user = update.effective_user

            data["admin_links"][url] = {

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
                "✅ LINK SAVED\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 Admin: {user.full_name}\n"
                f"🔗 Link Name: {name}\n"
                f"🔗 Link: {url}\n\n"
                "⚠️ Note: Telegram तभी इस link के joins को "
                "automatically attribute करेगा जब invite link "
                "bot द्वारा बनाया गया हो।"
            )

            return

    # =====================================================
    # CREATE NEW TELEGRAM INVITE LINK
    # =====================================================

    name = " ".join(context.args).strip()

    if not name:

        await update.message.reply_text(
            "❌ Link name खाली नहीं हो सकता।"
        )

        return

    user = update.effective_user

    try:

        # Make sure bot is admin
        bot_member = await context.bot.get_chat_member(
            TARGET_CHAT_ID,
            context.bot.id
        )

        if bot_member.status not in (
            "administrator",
            "creator"
        ):

            await update.message.reply_text(
                "❌ Bot target group में ADMIN नहीं है।\n\n"
                "Bot को ADMIN बनाएं और "
                "Invite Users permission ON करें।"
            )

            return

        # CREATE INVITE LINK
        invite = await context.bot.create_chat_invite_link(
            chat_id=TARGET_CHAT_ID,
            name=name
        )

        url = invite.invite_link

        data["admin_links"][url] = {

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
            f"🔗 Link Name: {name}\n\n"
            f"🔗 Link:\n{url}\n\n"
            "📊 Statistics:\n"
            "🟢 Joined: 0\n"
            "🔴 Left: 0\n"
            "👥 Net: 0"
        )

    except Exception as e:

        await update.message.reply_text(
            "❌ Invite link नहीं बन पाया।\n\n"
            f"Error:\n{e}\n\n"
            "⚠️ Check करें:\n"
            "1. Bot target group में ADMIN है\n"
            "2. Invite Users permission ON है\n"
            "3. Target Chat ID सही है\n\n"
            f"Target ID: {TARGET_CHAT_ID}"
        )


# =========================================================
# /links
# =========================================================

async def links(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_command_group(update):

        await update.message.reply_text(
            "❌ इस chat में commands allowed नहीं हैं।"
        )

        return

    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ यह report सिर्फ admin देख सकता है।"
        )

        return

    if not data["admin_links"]:

        await update.message.reply_text(
            "📊 ADMIN / LINK-WISE STATISTICS\n\n"
            "अभी कोई admin invite link नहीं बना है।"
        )

        return

    text = (
        "📊 ADMIN / LINK-WISE STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    for i, (url, info) in enumerate(
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

        net = joins - leaves

        text += (
            f"👤 Admin {i}: {admin}\n"
        )

        if username:
            text += f"🔹 Username: {username}\n"

        text += (
            f"🔗 Link Name: {name}\n\n"
            f"🟢 Joined: {joins}\n"
            f"🔴 Left: {leaves}\n"
            f"👥 Net: {net}\n"
            f"🔗 {url}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
        )

    await update.message.reply_text(text)


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    print("ERROR:", context.error)


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN variable missing!"
        )

    print("🤖 Starting bot...")

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

    #
