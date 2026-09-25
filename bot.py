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

# जिस GROUP के users track करने हैं
TARGET_CHAT_ID = -1004318016710

# जिस GROUP में commands/reports दिखानी हैं
COMMAND_CHAT_ID = -1003353359019

DATA_FILE = "bot_data.json"


# =========================================================
# DATA
# =========================================================

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
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


# =========================================================
# DATE
# =========================================================

def today():
    return datetime.now().strftime("%Y-%m-%d")


def date_string(date_value):
    return date_value.strftime("%Y-%m-%d")


# =========================================================
# ADMIN CHECK
# =========================================================

async def is_admin(update, context):

    if not update.effective_chat or not update.effective_user:
        return False

    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id,
            update.effective_user.id
        )

        return member.status in [
            "administrator",
            "creator"
        ]

    except Exception:
        return False


# =========================================================
# COMMAND GROUP CHECK
# =========================================================

def is_command_group(update):

    return (
        update.effective_chat
        and update.effective_chat.id == COMMAND_CHAT_ID
    )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

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


# =========================================================
# ID
# =========================================================

async def chat_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat

    if not chat:
        return

    name = (
        "Private Chat"
        if chat.type == "private"
        else chat.title or "Unknown"
    )

    await update.message.reply_text(
        "🆔 CHAT INFORMATION\n\n"
        f"📌 Name: {name}\n"
        f"💬 Type: {chat.type}\n"
        f"🆔 Chat ID: {chat.id}"
    )


# =========================================================
# MEMBER TRACKING
# =========================================================

async def member_update(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_member = update.chat_member

    if not chat_member:
        return

    # केवल target group
    if chat_member.chat.id != TARGET_CHAT_ID:
        return

    old_status = chat_member.old_chat_member.status
    new_status = chat_member.new_chat_member.status

    user = chat_member.new_chat_member.user
    user_id = str(user.id)

    # =====================================================
    # JOIN
    # =====================================================

    if (
        new_status in ["member", "administrator"]
        and
        old_status in ["left", "kicked"]
    ):

        join_date = today()

        # Overall join count
        data["joins"].setdefault(
            join_date,
            0
        )

        data["joins"][join_date] += 1

        # Telegram invite link
        invite = chat_member.invite_link

        if invite:

            invite_url = invite.invite_link

            if invite_url in data["admin_links"]:

                admin_info = data["admin_links"][invite_url]

                # Link total joins
                admin_info["joins"] = (
                    admin_info.get("joins", 0) + 1
                )

                # Link daily joins
                admin_info.setdefault(
                    "daily",
                    {}
                )

                admin_info["daily"].setdefault(
                    join_date,
                    0
                )

                admin_info["daily"][join_date] += 1

                # User किस link से आया
                data["user_links"][user_id] = invite_url

                # User information
                admin_info.setdefault(
                    "users",
                    {}
                )

                admin_info["users"][user_id] = {
                    "name": user.full_name,
                    "username": (
                        "@" + user.username
                        if user.username
                        else ""
                    )
                }

        save_data()

    # =====================================================
    # LEAVE
    # =====================================================

    elif (
        new_status in ["left", "kicked"]
        and
        old_status in ["member", "administrator"]
    ):

        leave_date = today()

        # Overall leave count
        data["leaves"].setdefault(
            leave_date,
            0
        )

        data["leaves"][leave_date] += 1

        # User किस link से आया था
        invite_url = data["user_links"].get(
            user_id
        )

        if invite_url:

            if invite_url in data["admin_links"]:

                admin_info = data["admin_links"][invite_url]

                # Link total leaves
                admin_info["leaves"] = (
                    admin_info.get("leaves", 0) + 1
                )

                # Link daily leaves
                admin_info.setdefault(
                    "daily_leaves",
                    {}
                )

                admin_info["daily_leaves"].setdefault(
                    leave_date,
                    0
                )

                admin_info["daily_leaves"][leave_date] += 1

        save_data()


# =========================================================
# STATS
# =========================================================

async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_command_group(update):

        await update.message.reply_text(
            "❌ /stats सिर्फ report वाले group में use करें."
        )
        return

    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ यह command सिर्फ admin use कर सकता है."
        )
        return

    # Target group
    try:

        target_chat = await context.bot.get_chat(
            TARGET_CHAT_ID
        )

    except Exception as e:

        await update.message.reply_text(
            "❌ Target group access error!\n\n"
            f"{e}\n\n"
            f"Target ID: {TARGET_CHAT_ID}"
        )
        return

    # Bot admin check
    try:

        bot_member = await context.bot.get_chat_member(
            TARGET_CHAT_ID,
            context.bot.id
        )

        if bot_member.status not in [
            "administrator",
            "creator"
        ]:

            await update.message.reply_text(
                "❌ Bot target group में ADMIN नहीं है.\n\n"
                "Bot को target group में ADMIN बनाएं."
            )
            return

    except Exception as e:

        await update.message.reply_text(
            f"❌ Target group error:\n{e}"
        )
        return

    # =====================================================
    # DATES
    # =====================================================

    today_date = datetime.now().date()

    yesterday_date = (
        today_date - timedelta(days=1)
    )

    week_start = (
        today_date -
        timedelta(days=today_date.weekday())
    )

    month_start = today_date.replace(day=1)

    today_joins = 0
    yesterday_joins = 0
    week_joins = 0
    month_joins = 0
    total_joins = 0

    today_leaves = 0
    yesterday_leaves = 0
    week_leaves = 0
    month_leaves = 0
    total_leaves = 0

    # =====================================================
    # JOINS
    # =====================================================

    for date_key, count in data["joins"].items():

        try:
            d = datetime.strptime(
                date_key,
                "%Y-%m-%d"
            ).date()
        except Exception:
            continue

        total_joins += count

        if d == today_date:
            today_joins += count

        if d == yesterday_date:
            yesterday_joins += count

        if week_start <= d <= today_date:
            week_joins += count

        if month_start <= d <= today_date:
            month_joins += count

    # =====================================================
    # LEAVES
    # =====================================================

    for date_key, count in data["leaves"].items():

        try:
            d = datetime.strptime(
                date_key,
                "%Y-%m-%d"
            ).date()
        except Exception:
            continue

        total_leaves += count

        if d == today_date:
            today_leaves += count

        if d == yesterday_date:
            yesterday_leaves += count

        if week_start <= d <= today_date:
            week_leaves += count

        if month_start <= d <= today_date:
            month_leaves += count

    # =====================================================
    # REPORT
    # =====================================================

    text = (
        "📊 GROUP USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"👥 Group:\n"
        f"{target_chat.title}\n\n"

        "📅 TODAY\n"
        f"🟢 Joined: {today_joins}\n"
        f"🔴 Left: {today_leaves}\n"
        f"⚪ Net: {today_joins - today_leaves}\n\n"

        "📅 YESTERDAY\n"
        f"🟢 Joined: {yesterday_joins}\n"
        f"🔴 Left: {yesterday_leaves}\n"
        f"⚪ Net: {yesterday_joins - yesterday_leaves}\n\n"

        "📅 THIS WEEK\n"
        f"🟢 Joined: {week_joins}\n"
        f"🔴 Left: {week_leaves}\n"
        f"⚪ Net: {week_joins - week_leaves}\n\n"

        "📅 THIS MONTH\n"
        f"🟢 Joined: {month_joins}\n"
        f"🔴 Left: {month_leaves}\n"
        f"⚪ Net: {month_joins - month_leaves}\n\n"

        "📊 TOTAL\n"
        f"🟢 Joined: {total_joins}\n"
        f"🔴 Left: {total_leaves}\n"
        f"⚪ Net: {total_joins - total_leaves}\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"🆔 Group ID:\n"
        f"{TARGET_CHAT_ID}"
    )

    await update.message.reply_text(text)


# =========================================================
# TODAY
# =========================================================

async def today_stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_command_group(update):

        await update.message.reply_text(
            "❌ /today सिर्फ report वाले group में use करें."
        )
        return

    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ यह command सिर्फ admin use कर सकता है."
        )
        return

    today_date = datetime.now().date()

    key = date_string(today_date)

    new_users = data["joins"].get(
        key,
        0
    )

    left_users = data["leaves"].get(
        key,
        0
    )

    await update.message.reply_text(
        "🟢 TODAY USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"📅 Date: {today_date.strftime('%d-%m-%Y')}\n\n"

        f"🟢 New Users: {new_users}\n"
        f"🔴 Left Users: {left_users}\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        f"👥 Net Users: {new_users - left_users}"
    )


# =========================================================
# YESTERDAY
# =========================================================

async def yesterday_stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_command_group(update):

        await update.message.reply_text(
            "❌ /yesterday सिर्फ report वाले group में use करें."
        )
        return

    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ यह command सिर्फ admin use कर सकता है."
        )
        return

    yesterday_date = (
        datetime.now().date() -
        timedelta(days=1)
    )

    key = date_string(
        yesterday_date
    )

    new_users = data["joins"].get(
        key,
        0
    )

    left_users = data["leaves"].get(
        key,
        0
    )

    await update.message.reply_text(
        "🟡 YESTERDAY USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"📅 Date: {yesterday_date.strftime('%d-%m-%Y')}\n\n"

        f"🟢 New Users: {new_users}\n"
        f"🔴 Left Users: {left_users}\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        f"👥 Net Users: {new_users - left_users}"
    )


# =========================================================
# ADD LINK
# =========================================================

async def addlink(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_command_group(update):

        await update.message.reply_text(
            "❌ /addlink सिर्फ report वाले group में use करें."
        )
        return

    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ सिर्फ admin नया invite link बना सकता है."
        )
        return

    # =====================================================
    # LINK NAME
    # =====================================================

    if not context.args:

        await update.message.reply_text(
            "❌ Link का नाम देना जरूरी है.\n\n"

            "Example:\n"
            "/addlink Jaipur Team\n\n"

            "या:\n"
            "/addlink Delhi Team"
        )
        return

    link_name = " ".join(
        context.args
    ).strip()

    if not link_name:

        await update.message.reply_text(
            "❌ Link name खाली नहीं हो सकता."
        )
        return

    user = update.effective_user

    try:

        # =================================================
        # CREATE TELEGRAM INVITE LINK
        # =================================================

        invite = await context.bot.create_chat_invite_link(
            chat_id=TARGET_CHAT_ID,
            name=link_name
        )

        link = invite.invite_link

        # =================================================
        # SAVE LINK
        # =================================================

        data["admin_links"][link] = {

            "admin_id": user.id,

            "admin_name": user.full_name,

            "username": (
                "@" + user.username
                if user.username
                else ""
            ),

            "link_name": link_name,

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

            f"👤 Admin:\n"
            f"{user.full_name}\n\n"

            f"🏷 Link Name:\n"
            f"{link_name}\n\n"

            f"🔗 Link:\n"
            f"{link}\n\n"

            "📊 Statistics:\n"
            "🟢 Joined: 0\n"
            "🔴 Left: 0\n"
            "⚪ Net: 0\n\n"

            "📌 इस link से आने वाले users "
            "इसी link के नाम में count होंगे."
        )

    except Exception as e:

        await update.message.reply_text(
            "❌ Invite link नहीं बन पाया.\n\n"

            f"Error:\n{e}\n\n"

            "⚠️ Bot को target group में ADMIN बनाएं "
            "और Invite Users permission दें."
        )


# =========================================================
# MYLINK
# =========================================================

async def mylink(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "ℹ️ नया named link बनाने के लिए:\n\n"

        "/addlink LINK_NAME\n\n"

        "Example:\n"
        "/addlink Jaipur Team"
    )


# =========================================================
# LINKS
# =========================================================

async def links(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_command_group(update):

        await update.message.reply_text(
            "❌ /links सिर्फ report वाले group में use करें."
        )
        return

    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ सिर्फ admin यह report देख सकता है."
        )
        return

    if not data["admin_links"]:

        await update.message.reply_text(
            "📊 ADMIN / LINK-WISE STATISTICS\n\n"
            "अभी कोई admin invite link नहीं बना है."
        )
        return

    text = (
        "📊 ADMIN / LINK-WISE STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    for index, (link, info) in enumerate(
        data["admin_links"].items(),
        start=1
    ):

        admin_name = info.get(
            "admin_name",
            "Unknown Admin"
        )

        username = info.get(
            "username",
            ""
        )

        link_name = info.get(
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
            f"👤 {index}. {admin_name}\n"
        )

        if username:
            text += (
                f"🔹 {username}\n"
            )

        text += (
            f"🏷 Link Name: {link_name}\n\n"

            f"🟢 Joined: {joins}\n"
            f"🔴 Left: {leaves}\n"
            f"⚪ Net: {net}\n\n"

            f"🔗 {link}\n\n"

            "━━━━━━━━━━━━━━━━━━━━\n\n"
        )

    text += (
        "📌 Joined = इस link से group में आने वाले users\n"
        "📌 Left = इस link से आए users में से leave करने वाले\n"
        "📌 Net = Joined - Left"
    )

    await update.message.reply_text(text)


# =========================================================
# ERROR
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    print(
        "ERROR:",
        context.error
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN variable missing!"
        )

    print(
        "🤖 Bot started..."
    )

    app = (
        Applicati
