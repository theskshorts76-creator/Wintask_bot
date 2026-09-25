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

# जिस GROUP में reports/commands दिखानी हैं
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
            "admin_links": {}
        }

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        return {
            "joins": {},
            "leaves": {},
            "admin_links": {}
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "✅ Wintask Bot is working!\n\n"
        "Commands:\n"
        "/id - Current chat ID\n"
        "/stats - Complete statistics\n"
        "/today - Today's users\n"
        "/yesterday - Yesterday's users\n"
        "/mylink - Create admin invite link\n"
        "/addlink - Create NEW admin invite link\n"
        "/links - Admin-wise statistics"
    )


# =========================================================
# ID
# =========================================================

async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):

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
# GET DATE COUNTS
# =========================================================

def get_join_count(date_value):

    date_key = date_string(date_value)

    return data["joins"].get(date_key, 0)


def get_period_counts():

    now = datetime.now()

    today_date = now.date()

    yesterday_date = today_date - timedelta(days=1)

    week_start = (
        today_date -
        timedelta(days=today_date.weekday())
    )

    month_start = today_date.replace(day=1)

    today_count = 0
    yesterday_count = 0
    week_count = 0
    month_count = 0
    total_count = 0

    for date_key, count in data["joins"].items():

        try:

            d = datetime.strptime(
                date_key,
                "%Y-%m-%d"
            ).date()

        except Exception:

            continue

        total_count += count

        if d == today_date:
            today_count += count

        if d == yesterday_date:
            yesterday_count += count

        if week_start <= d <= today_date:
            week_count += count

        if month_start <= d <= today_date:
            month_count += count

    return (
        today_count,
        yesterday_count,
        week_count,
        month_count,
        total_count
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

    # सिर्फ target group
    if chat_member.chat.id != TARGET_CHAT_ID:
        return

    old_status = chat_member.old_chat_member.status
    new_status = chat_member.new_chat_member.status

    # =====================================================
    # JOIN
    # =====================================================

    if (
        new_status in ["member", "administrator"]
        and
        old_status in ["left", "kicked"]
    ):

        join_date = today()

        data["joins"].setdefault(
            join_date,
            0
        )

        data["joins"][join_date] += 1

        # Admin invite link
        invite = chat_member.invite_link

        if invite:

            invite_url = invite.invite_link

            if invite_url in data["admin_links"]:

                admin_info = data["admin_links"][invite_url]

                admin_info["joins"] = (
                    admin_info.get("joins", 0) + 1
                )

                admin_info.setdefault(
                    "daily",
                    {}
                )

                admin_info["daily"].setdefault(
                    join_date,
                    0
                )

                admin_info["daily"][join_date] += 1

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

        data["leaves"].setdefault(
            leave_date,
            0
        )

        data["leaves"][leave_date] += 1

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

    (
        today_count,
        yesterday_count,
        week_count,
        month_count,
        total_count
    ) = get_period_counts()

    text = (
        "📊 GROUP USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"👥 Group:\n"
        f"{target_chat.title}\n\n"

        "📥 NEW USERS\n\n"

        f"🟢 Today: {today_count}\n"
        f"🟡 Yesterday: {yesterday_count}\n"
        f"🔵 This Week: {week_count}\n"
        f"🟣 This Month: {month_count}\n"
        f"⚪ Total: {total_count}\n\n"

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

    count = get_join_count(today_date)

    await update.message.reply_text(
        "🟢 TODAY USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 Date: {today_date.strftime('%d-%m-%Y')}\n\n"
        f"👥 New Users: {count}"
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

    count = get_join_count(yesterday_date)

    await update.message.reply_text(
        "🟡 YESTERDAY USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 Date: {yesterday_date.strftime('%d-%m-%Y')}\n\n"
        f"👥 New Users: {count}"
    )


# =========================================================
# CREATE ADMIN LINK
# =========================================================

async def create_admin_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_command_group(update):

        await update.message.reply_text(
            "❌ यह command सिर्फ report वाले group में use करें."
        )

        return

    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ सिर्फ admin नया invite link बना सकता है."
        )

        return

    user = update.effective_user

    try:

        invite = await context.bot.create_chat_invite_link(
            chat_id=TARGET_CHAT_ID,
            name=f"Admin - {user.full_name}"
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
            "joins": 0,
            "daily": {}
        }

        save_data()

        await update.message.reply_text(
            "🔗 NEW ADMIN INVITE LINK\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"

            f"👤 Admin: {user.full_name}\n\n"

            f"🔗 Link:\n{link}\n\n"

            "📌 इस link से आने वाले users "
            "आपके नाम में count होंगे.\n\n"

            "⚠️ नया link चाहिए तो /addlink फिर से use करें."
        )

    except Exception as e:

        await update.message.reply_text(
            "❌ Invite link नहीं बन पाया.\n\n"
            f"Error: {e}\n\n"
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

    await create_admin_link(
        update,
        context
    )


# =========================================================
# ADDLINK
# =========================================================

async def addlink(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await create_admin_link(
        update,
        context
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
            "📊 ADMIN-WISE USER STATISTICS\n\n"
            "अभी किसी admin ने /mylink या /addlink "
            "से link नहीं बनाया है."
        )

        return

    now = datetime.now()

    today_date = now.date()

    week_start = (
        today_date -
        timedelta(days=today_date.weekday())
    )

    month_start = today_date.replace(day=1)

    text = (
        "📊 ADMIN-WISE USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    for index, (link, info) in enumerate(
        data["admin_links"].items(),
        start=1
    ):

        daily = info.get(
            "daily",
            {}
        )

        today_count = 0
        week_count = 0
        month_count = 0

        for date_key, count in daily.items():

            try:

                d = datetime.strptime(
                    date_key,
                    "%Y-%m-%d"
                ).date()

            except Exception:

                continue

            if d == today_date:
                today_count += count

            if week_start <= d <= today_date:
                week_count += count

            if month_start <= d <= today_date:
                month_count += count

        admin_name = info.get(
            "admin_name",
            "Unknown Admin"
        )

        username = info.get(
            "username",
            ""
        )

        total = info.get(
            "joins",
            0
        )

        text += (
            f"👤 {index}. {admin_name}\n"
        )

        if username:
            text += f"🔹 {username}\n"

        text += (
            f"🟢 Today: {today_count}\n"
            f"🔵 Week: {week_count}\n"
            f"🟣 Month: {month_count}\n"
            f"⚪ Total: {total}\n\n"
        )

    text += (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📌 Admin-wise count उनके invite link "
        "से आने वाले users का है."
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
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # /start
    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    # /id
    app.add_handler(
        CommandHandler(
            "id",
            chat_id
        )
    )

    # /stats
    app.add_handler(
        CommandHandler(
            "stats",
            stats
        )
    )

    # /today
    app.add_handler(
        CommandHandler(
            "today",
            today_stats
        )
    )

    # /yesterday
    app.add_handler(
        CommandHandler(
            "yesterday",
            yesterday_stats
        )
    )

    # /mylink
    app.add_handler(
        CommandHandler(
            "mylink",
            mylink
        )
    )

    # /addlink
    app.add_handler(
        CommandHandler(
            "addlink",
            addlink
        )
    )

    # /links
    app.add_handler(
        CommandHandler(
            "links",
            links
        )
    )

    # Member tracking
    app.add_handler(
        ChatMemberHandler(
            member_update,
            ChatMemberHandler.CHAT_MEMBER
        )
    )

    # Error handler
    app.add_error_handler(
        error_handler
    )

    print(
        f"🎯 Target Group: {TARGET_CHAT_ID}"
    )

    print(
        f"💬 Command Group: {COMMAND_CHAT_ID}"
    )

    # Start bot
    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
