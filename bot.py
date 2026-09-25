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

# TARGET GROUP
# Jiske users ka JOIN / LEFT track karna hai
TARGET_CHAT_ID = -1004318016710

# REPORT / COMMAND GROUP
COMMAND_CHAT_ID = -1003353359019

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
# DATE
# =========================================================

def today():
    return datetime.now().strftime("%Y-%m-%d")


def date_string(d):
    return d.strftime("%Y-%m-%d")


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

        return member.status in (
            "administrator",
            "creator"
        )

    except Exception:
        return False


# =========================================================
# COMMAND GROUP CHECK
# =========================================================

def is_command_group(update):

    if not update.effective_chat:
        return False

    return update.effective_chat.id == COMMAND_CHAT_ID


# =========================================================
# /start
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "✅ Wintask Bot is working!\n\n"
        "📌 COMMANDS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "/id - Current chat ID\n"
        "/stats - Complete statistics\n"
        "/today - Today's statistics\n"
        "/yesterday - Yesterday's statistics\n"
        "/mylink - Your admin links\n"
        "/addlink NAME - Create new link\n"
        "/addlink NAME LINK - Add existing link\n"
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
        "🆔 CHAT INFORMATION\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 Name: {name}\n"
        f"💬 Type: {chat.type}\n"
        f"🆔 Chat ID: {chat.id}"
    )


# =========================================================
# MEMBER UPDATE
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
    user_id = str(user.id)

    # =====================================================
    # JOIN
    # =====================================================

    if (
        new_status in ("member", "administrator")
        and old_status in ("left", "kicked")
    ):

        d = today()

        # Total join count
        data["joins"][d] = (
            data["joins"].get(d, 0) + 1
        )

        # Invite link used by the user
        invite = cm.invite_link

        if invite:

            url = invite.invite_link

            if url in data["admin_links"]:

                info = data["admin_links"][url]

                # Total joins for this link
                info["joins"] = (
                    info.get("joins", 0) + 1
                )

                # Daily joins
                daily = info.setdefault(
                    "daily",
                    {}
                )

                daily[d] = (
                    daily.get(d, 0) + 1
                )

                # User information
                users = info.setdefault(
                    "users",
                    {}
                )

                users[user_id] = {
                    "name": user.full_name,
                    "username": (
                        "@" + user.username
                        if user.username
                        else ""
                    )
                }

                # Remember link for future LEFT
                data["user_links"][user_id] = url

        save_data()

    # =====================================================
    # LEFT
    # =====================================================

    elif (
        new_status in ("left", "kicked")
        and old_status in ("member", "administrator")
    ):

        d = today()

        # Total leaves
        data["leaves"][d] = (
            data["leaves"].get(d, 0) + 1
        )

        # Find user's original invite link
        url = data["user_links"].get(user_id)

        if url and url in data["admin_links"]:

            info = data["admin_links"][url]

            # Total leaves for this link
            info["leaves"] = (
                info.get("leaves", 0) + 1
            )

            # Daily leaves
            daily_leaves = info.setdefault(
                "daily_leaves",
                {}
            )

            daily_leaves[d] = (
                daily_leaves.get(d, 0) + 1
            )

        save_data()


# =========================================================
# /stats
# =========================================================

async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_command_group(update):

        await update.message.reply_text(
            "❌ Ye command report group me use karein."
        )
        return

    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ Sirf admin ye report dekh sakta hai."
        )
        return

    # Target group check
    try:

        target = await context.bot.get_chat(
            TARGET_CHAT_ID
        )

        bot_member = await context.bot.get_chat_member(
            TARGET_CHAT_ID,
            context.bot.id
        )

        if bot_member.status not in (
            "administrator",
            "creator"
        ):

            await update.message.reply_text(
                "❌ Bot target group me ADMIN nahi hai."
            )
            return

    except Exception as e:

        await update.message.reply_text(
            "❌ Target group error:\n\n"
            f"{e}\n\n"
            f"Target ID: {TARGET_CHAT_ID}"
        )
        return

    td = datetime.now().date()
    yd = td - timedelta(days=1)

    week_start = (
        td - timedelta(days=td.weekday())
    )

    month_start = td.replace(day=1)

    today_join = 0
    today_left = 0

    yesterday_join = 0
    yesterday_left = 0

    week_join = 0
    week_left = 0

    month_join = 0
    month_left = 0

    total_join = 0
    total_left = 0

    # -----------------------------------------------------
    # JOINS
    # -----------------------------------------------------

    for key, count in data["joins"].items():

        try:
            d = datetime.strptime(
                key,
                "%Y-%m-%d"
            ).date()

        except Exception:
            continue

        total_join += count

        if d == td:
            today_join += count

        if d == yd:
            yesterday_join += count

        if week_start <= d <= td:
            week_join += count

        if month_start <= d <= td:
            month_join += count

    # -----------------------------------------------------
    # LEAVES
    # -----------------------------------------------------

    for key, count in data["leaves"].items():

        try:
            d = datetime.strptime(
                key,
                "%Y-%m-%d"
            ).date()

        except Exception:
            continue

        total_left += count

        if d == td:
            today_left += count

        if d == yd:
            yesterday_left += count

        if week_start <= d <= td:
            week_left += count

        if month_start <= d <= td:
            month_left += count

    await update.message.reply_text(

        "📊 GROUP USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"👥 Group:\n"
        f"{target.title}\n\n"

        "📅 TODAY\n"
        f"🟢 Joined: {today_join}\n"
        f"🔴 Left: {today_left}\n"
        f"👥 Net: {today_join - today_left}\n\n"

        "📅 YESTERDAY\n"
        f"🟢 Joined: {yesterday_join}\n"
        f"🔴 Left: {yesterday_left}\n"
        f"👥 Net: {yesterday_join - yesterday_left}\n\n"

        "📅 THIS WEEK\n"
        f"🟢 Joined: {week_join}\n"
        f"🔴 Left: {week_left}\n"
        f"👥 Net: {week_join - week_left}\n\n"

        "📅 THIS MONTH\n"
        f"🟢 Joined: {month_join}\n"
        f"🔴 Left: {month_left}\n"
        f"👥 Net: {month_join - month_left}\n\n"

        "📊 TOTAL\n"
        f"🟢 Joined: {total_join}\n"
        f"🔴 Left: {total_left}\n"
        f"👥 Net: {total_join - total_left}\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Target Group ID:\n"
        f"{TARGET_CHAT_ID}"
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
            "❌ Ye command report group me use karein."
        )
        return

    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ Sirf admin ye report dekh sakta hai."
        )
        return

    d = datetime.now().date()
    key = date_string(d)

    total_joined = data["joins"].get(
        key,
        0
    )

    total_left = data["leaves"].get(
        key,
        0
    )

    text = (
        "🟢 TODAY USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 Date: {key}\n\n"
    )

    found = False

    for url, info in data["admin_links"].items():

        daily = info.get(
            "daily",
            {}
        )

        daily_leaves = info.get(
            "daily_leaves",
            {}
        )

        joined = daily.get(
            key,
            0
        )

        left = daily_leaves.get(
            key,
            0
        )

        if joined == 0 and left == 0:
            continue

        found = True

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

        text += (
            f"👤 Admin: {admin_name}\n"
        )

        if username:
            text += (
                f"📱 Username: {username}\n"
            )

        text += (
            f"🔗 Link Name: {link_name}\n"
            f"🟢 Joined: {joined}\n"
            f"🔴 Left: {left}\n"
            f"👥 Net: {joined - left}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
        )

    if not found:

        text += (
            "ℹ️ Aaj kisi registered admin link "
            "se Join/Left record nahi mila.\n\n"
        )

    text += (
        "📊 TOTAL\n\n"
        f"🟢 New Users: {total_joined}\n"
        f"🔴 Left Users: {total_left}\n"
        f"👥 Net Users: "
        f"{total_joined - total_left}"
    )

    await update.message.reply_text(text)


# =========================================================
# /yesterday
# =========================================================

async def yesterday_stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_command_group(update):

        await update.message.reply_text(
            "❌ Ye command report group me use karein."
        )
        return

    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ Sirf admin ye report dekh sakta hai."
        )
        return

    d = (
        datetime.now().date()
        - timedelta(days=1)
    )

    key = date_string(d)

    total_joined = data["joins"].get(
        key,
        0
    )

    total_left = data["leaves"].get(
        key,
        0
    )

    text = (
        "🟡 YESTERDAY USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 Date: {key}\n\n"
    )

    found = False

    for url, info in data["admin_links"].items():

        daily = info.get(
            "daily",
            {}
        )

        daily_leaves = info.get(
            "daily_leaves",
            {}
        )

        joined = daily.get(
            key,
            0
        )

        left = daily_leaves.get(
            key,
            0
        )

        if joined == 0 and left == 0:
            continue

        found = True

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

        text += (
            f"👤 Admin: {admin_name}\n"
        )

        if username:
            text += (
                f"📱 Username: {username}\n"
            )

        text += (
            f"🔗 Link Name: {link_name}\n"
            f"🟢 Joined: {joined}\n"
            f"🔴 Left: {left}\n"
            f"👥 Net: {joined - left}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
        )

    if not found:

        text += (
            "ℹ️ Kal kisi registered admin link "
            "se Join/Left record nahi mila.\n\n"
        )

    text += (
        "📊 TOTAL\n\n"
        f"🟢 New Users: {total_joined}\n"
        f"🔴 Left Users: {total_left}\n"
        f"👥 Net Users: "
        f"{total_joined - total_left}"
    )

    await update.message.reply_text(text)


# =========================================================
# /addlink
# =========================================================

async def addlink(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_command_group(update):

        await update.message.reply_text(
            "❌ Ye command report group me use karein."
        )
        return

    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ Sirf group admin ye command use kar sakta hai."
        )
        return

    if not context.args:

        await update.message.reply_text(
            "❌ Link name den.\n\n"
            "New link:\n"
            "/addlink Sachin\n\n"
            "Existing link:\n"
            "/addlink Sachin https://t.me/+XXXX"
        )
        return

    name = context.args[0].strip()

    if not name:

        await update.message.reply_text(
            "❌ Link name empty nahi ho sakta."
        )
        return

    user = update.effective_user

    # =====================================================
    # EXISTING LINK ADD
    # =====================================================

    if len(context.args) >= 2:

        link = context.args[1].strip()

        if not (
            link.startswith("https://t.me/")
            or link.startswith("http://t.me/")
        ):

            await update.message.reply_text(
                "❌ Sahi Telegram invite link den.\n\n"
                "Example:\n"
                "/addlink Sachin https://t.me/+XXXX"
            )
            return

        if link in data["admin_links"]:

            await update.message.reply_text(
                "❌ Ye link pehle se registered hai."
            )
            return

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

            "✅ EXISTING ADMIN LINK ADDED\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"

            f"👤 Admin:\n"
            f"{user.full_name}\n\n"

            f"🏷 Link Name:\n"
            f"{name}\n\n"

            f"🔗 Link:\n"
            f"{link}\n\n"

            "📊 Statistics:\n"
            "🟢 Joined: 0\n"
            "🔴 Left: 0\n"
            "👥 Net: 0"
        )

        return

    # =====================================================
    # CREATE NEW LINK
    # =====================================================

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

            f"👤 Admin:\n"
            f"{user.full_name}\n\n"

            f"🏷 Link Name:\n"
            f"{name}\n\n"

            f"🔗 Link:\n"
            f"{link}\n\n"

            "📊 Statistics:\n"
            "🟢 Joined: 0\n"
            "🔴 Left: 0\n"
            "👥 Net: 0"
        )

    except Exception as e:

        await update.message.reply_text(

            "❌ Invite link nahi ban paya.\n\n"

            f"Error:\n{e}\n\n"

            "⚠️ Check karein ki bot target group "
            "me ADMIN hai aur Invite Users permission hai."
        )


# =========================================================
# /mylink
# =========================================================

async def mylink(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_command_group(update):

        await update.message.reply_text(
            "❌ Ye command report group me use karein."
        )
        return

    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ Sirf admin ye command use kar sakta hai."
        )
        return

   
