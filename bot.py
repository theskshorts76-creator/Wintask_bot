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


# =========================================================
# SETTINGS
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

# TARGET GROUP
TARGET_CHAT_ID = -1004318016710

# REPORT / COMMAND GROUP
COMMAND_CHAT_ID = -1003353359019

# India time
IST = ZoneInfo("Asia/Kolkata")

DATA_FILE = "bot_data.json"


# =========================================================
# DATA
# =========================================================

def default_data():
    return {
        "joins": {},
        "leaves": {},
        "admin_links": {},
        "users": {}
    }


def load_data():
    if not os.path.exists(DATA_FILE):
        return default_data()

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        base = default_data()

        if isinstance(loaded, dict):
            for key in base:
                if key in loaded:
                    base[key] = loaded[key]

        return base

    except Exception:
        return default_data()


data = load_data()


def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )
    except Exception as e:
        print("SAVE ERROR:", e)


# =========================================================
# DATE / TIME
# =========================================================

def now_ist():
    return datetime.now(IST)


def today():
    return now_ist().strftime("%Y-%m-%d")


def yesterday():
    return (
        now_ist() - timedelta(days=1)
    ).strftime("%Y-%m-%d")


# =========================================================
# HELPERS
# =========================================================

def get_admin_info_by_link(link):
    if not link:
        return None

    return data["admin_links"].get(link)


def ensure_admin_link(
    link,
    admin_id=None,
    admin_name="Unknown Admin",
    username=""
):
    if not link:
        return

    if link not in data["admin_links"]:
        data["admin_links"][link] = {
            "admin_id": admin_id,
            "admin_name": admin_name,
            "username": username,
            "joins": 0,
            "leaves": 0,
            "daily": {}
        }

    info = data["admin_links"][link]

    if admin_id is not None:
        info["admin_id"] = admin_id

    if admin_name:
        info["admin_name"] = admin_name

    if username:
        info["username"] = username

    info.setdefault("joins", 0)
    info.setdefault("leaves", 0)
    info.setdefault("daily", {})


def ensure_daily_admin_data(link, date_string):
    info = data["admin_links"].get(link)

    if not info:
        return None

    info.setdefault("daily", {})

    if date_string not in info["daily"]:
        info["daily"][date_string] = {
            "joins": 0,
            "leaves": 0
        }

    return info["daily"][date_string]


# =========================================================
# COMMAND GROUP CHECK
# =========================================================

def is_command_group(update):
    return (
        update.effective_chat
        and update.effective_chat.id == COMMAND_CHAT_ID
    )


# =========================================================
# ADMIN CHECK
# =========================================================

async def is_admin(update, context):
    if not update.effective_chat:
        return False

    if not update.effective_user:
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

    except Exception as e:
        print("ADMIN CHECK ERROR:", e)
        return False


# =========================================================
# BOT ADMIN CHECK
# =========================================================

async def check_target_bot_admin(context):
    try:
        member = await context.bot.get_chat_member(
            TARGET_CHAT_ID,
            context.bot.id
        )

        return member.status in [
            "administrator",
            "creator"
        ]

    except Exception as e:
        print("BOT ADMIN CHECK ERROR:", e)
        return False


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "✅ Wintask Bot is working!\n\n"
        "📊 Commands:\n\n"
        "/today - आज की Joined/Left report\n"
        "/yesterday - कल की Joined/Left report\n"
        "/stats - Group statistics\n"
        "/mylink - अपना admin invite link बनाएं\n"
        "/addlink - Existing admin link add करें\n"
        "/links - Admin-wise statistics\n"
        "/id - Current chat ID"
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

    # Only target group
    if chat_member.chat.id != TARGET_CHAT_ID:
        return

    old_status = chat_member.old_chat_member.status
    new_status = chat_member.new_chat_member.status

    user = chat_member.new_chat_member.user

    user_id = user.id

    user_name = (
        user.full_name
        or user.username
        or str(user_id)
    )

    username = (
        "@" + user.username
        if user.username
        else ""
    )

    # =====================================================
    # JOIN
    # =====================================================

    if (
        new_status in ["member", "administrator"]
        and old_status in ["left", "kicked"]
    ):

        join_date = today()

        # Overall joins
        data["joins"].setdefault(
            join_date,
            0
        )

        data["joins"][join_date] += 1

        # Telegram tells us which invite link was used
        invite = chat_member.invite_link

        invite_url = None

        if invite:
            invite_url = invite.invite_link

        # Save user's latest invite/admin information
        data["users"][str(user_id)] = {
            "name": user_name,
            "username": username,
            "invite_link": invite_url,
            "last_join": join_date
        }

        # Admin-wise join
        if invite_url:

            info = get_admin_info_by_link(
                invite_url
            )

            if info:

                info["joins"] = (
                    info.get("joins", 0) + 1
                )

                daily = ensure_daily_admin_data(
                    invite_url,
                    join_date
                )

                if daily:
                    daily["joins"] += 1

        save_data()

        print(
            f"JOIN: {user_name} "
            f"({user_id}) "
            f"link={invite_url}"
        )

    # =====================================================
    # LEAVE
    # =====================================================

    elif (
        new_status in ["left", "kicked"]
        and old_status in [
            "member",
            "administrator"
        ]
    ):

        leave_date = today()

        # Overall leaves
        data["leaves"].setdefault(
            leave_date,
            0
        )

        data["leaves"][leave_date] += 1

        # Find admin from user's saved invite link
        user_info = data["users"].get(
            str(user_id)
        )

        if user_info:

            invite_url = user_info.get(
                "invite_link"
            )

            if invite_url:

                info = get_admin_info_by_link(
                    invite_url
                )

                if info:

                    info["leaves"] = (
                        info.get("leaves", 0) + 1
                    )

                    daily = ensure_daily_admin_data(
                        invite_url,
                        leave_date
                    )

                    if daily:
                        daily["leaves"] += 1

        save_data()

        print(
            f"LEAVE: {user_name} "
            f"({user_id})"
        )


# =========================================================
# DAILY REPORT
# =========================================================

async def daily_report(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    report_date=None
):

    if not is_command_group(update):

        await update.message.reply_text(
            "❌ यह command सिर्फ report वाले group में use करें."
        )
        return

    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ यह command सिर्फ admin use कर सकता है."
        )
        return

    if report_date is None:
        report_date = today()

    # Check target group
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

    # Check bot admin
    bot_is_admin = await check_target_bot_admin(
        context
    )

    if not bot_is_admin:

        await update.message.reply_text(
            "❌ Bot target group में ADMIN नहीं है.\n\n"
            "Bot को target group में ADMIN बनाएं."
        )
        return

    joined = data["joins"].get(
        report_date,
        0
    )

    left = data["leaves"].get(
        report_date,
        0
    )

    net = joined - left

    # =====================================================
    # ADMIN WISE
    # =====================================================

    admin_lines = []

    for link, info in data["admin_links"].items():

        daily = info.get(
            "daily",
            {}
        )

        day_data = daily.get(
            report_date,
            {}
        )

        admin_joined = day_data.get(
            "joins",
            0
        )

        admin_left = day_data.get(
            "leaves",
            0
        )

        admin_net = (
            admin_joined - admin_left
        )

        # Show admin even if only leave happened
        if admin_joined == 0 and admin_left == 0:
            continue

        admin_name = info.get(
            "admin_name",
            "Unknown Admin"
        )

        username = info.get(
            "username",
            ""
        )

        display_name = admin_name

        if username:
            display_name += f" {username}"

        admin_lines.append(
            "👤 "
            + display_name
            + "\n"
            + f"   🟢 Joined: {admin_joined}\n"
            + f"   🔴 Left: {admin_left}\n"
            + f"   👥 Net: {admin_net}"
        )

    # =====================================================
    # REPORT TEXT
    # =====================================================

    if report_date == today():
        title = "📊 TODAY USER STATISTICS"
    elif report_date == yesterday():
        title = "📊 YESTERDAY USER STATISTICS"
    else:
        title = "📊 USER STATISTICS"

    text = (
        f"{title}\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 Date: {report_date}\n\n"
        f"👥 Group: {target_chat.title}\n\n"
        "🟢 JOINED\n"
        f"{joined}\n\n"
        "🔴 LEFT\n"
        f"{left}\n\n"
        "👥 NET\n"
        f"{net}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👤 ADMIN-WISE\n\n"
    )

    if admin_lines:

        text += "\n\n".join(
            admin_lines
        )

    else:

        text += (
            "कोई admin-wise data नहीं है.\n\n"
            "📌 Existing users के पुराने joins "
            "retroactively track नहीं हो सकते."
        )

    text += (
        "\n\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Target Group ID:\n"
        f"{TARGET_CHAT_ID}"
    )

    await update.message.reply_text(
        text
    )


# =========================================================
# TODAY
# =========================================================

async def today_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await daily_report(
        update,
        context,
        today()
    )


# =========================================================
# YESTERDAY
# =========================================================

async def yesterday_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await daily_report(
        update,
        context,
        yesterday()
    )


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

    try:

        target_chat = await context.bot.get_chat(
            TARGET_CHAT_ID
        )

    except Exception as e:

        await update.message.reply_text(
            "❌ Target group access error!\n\n"
            f"{e}"
        )
        return

    now = now_ist()

    today_date = now.date()

    yesterday_date = (
        today_date - timedelta(days=1)
    )

    week_start = (
        today_date -
        timedelta(days=today_date.weekday())
    )

    month_start = today_date.replace(
        day=1
    )

    today_count = 0
    yesterday_count = 0
    week_count = 0
    month_count = 0
    total_count = 0

    for date_string, count in data["joins"].items():

        try:
            d = datetime.strptime(
                date_string,
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

    await update.message.reply_text(
        "📊 GROUP USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Group:\n{target_chat.title}\n\n"
        "📥 NEW USERS\n\n"
        f"🟢 Today: {today_count}\n"
        f"🟡 Yesterday: {yesterday_count}\n"
        f"🔵 This Week: {week_count}\n"
        f"🟣 This Month: {month_count}\n"
        f"⚪ Total: {total_count}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 Group ID:\n{TARGET_CHAT_ID}"
    )


# =========================================================
# MYLINK
# =========================================================

async def mylink(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_command_group(update):

        await update.message.reply_text(
            "❌ /mylink सिर्फ report वाले group में use करें."
        )
        return

    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ सिर्फ admin अपना link बना सकता है."
        )
        return

    user = update.effective_user

    try:

        invite = await context.bot.create_chat_invite_link(
            chat_id=TARGET_CHAT_ID,
            name=f"Admin - {user.full_name}"
        )

        link = invite.invite_link

        ensure_admin_link(
            link=link,
            admin_id=user.id,
            admin_name=user.full_name,
            username=(
                "@"
                + user.username
                if user.username
                else ""
            )
        )

        save_data()

        await update.message.reply_text(
            "🔗 YOUR ADMIN INVITE LINK\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Admin: {user.full_name}\n\n"
            f"🔗 Link:\n{link}\n\n"
            "📌 इस link से आने वाले users "
            "आपके नाम में count होंगे."
        )

    except Exception as e:

        await update.message.reply_text(
            "❌ Invite link नहीं बन पाया.\n\n"
            f"Error:\n{e}\n\n"
            "⚠️ Bot को target group में ADMIN बनाएं "
            "और Invite Users permission दें."
        )


# =========================================================
# ADD EXISTING LINK
#
# Usage:
# /addlink Admin Name | https://t.me/+xxxxxxxx
#
# Example:
# /addlink Sachin | https://t.me/+abc123
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
            "❌ सिर्फ admin existing link add कर सकता है."
        )
        return

    if not context.args:

        await update.message.reply_text(
            "❌ सही format:\n\n"
            "/addlink Admin Name | Invite Link\n\n"
            "Example:\n"
            "/addlink Sachin | https://t.me/+abc123"
        )
        return

    full_text = " ".join(
        context.args
    )

    if "|" not in full_text:

        await update.message.reply_text(
            "❌ Format गलत है.\n\n"
            "ऐसे भेजें:\n"
            "/addlink Admin Name | Invite Link"
        )
        return

    parts = full_text.split(
        "|",
        1
    )

    admin_name = parts[0].strip()
    link = parts[1].strip()

    if not admin_name or not link:

        await update.message.reply_text(
            "❌ Admin name और link दोनों जरूरी हैं."
        )
        return

    if not (
        link.startswith("https://t.me/")
        or link.startswith("http://t.me/")
    ):

        await update.message.reply_text(
            "❌ Telegram invite link सही नहीं है."
        )
        return

    # Existing link update / add
    ensure_admin_link(
        link=link,
        admin_id=None,
        admin_name=admin_name,
        username=""
    )

    save_data()

    await update.message.reply_text(
        "✅ ADMIN LINK ADDED\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Admin: {admin_name}\n"
        f"🔗 Link:\n{link}\n\n"
        "अब इस link से आने वाले नए users "
        "इस admin के नाम में count होंगे."
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
            "❌ /links सिर्फ report वाले group में use कर
