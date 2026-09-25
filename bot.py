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

# Jis group ke users track karne hain
TARGET_CHAT_ID = -1004318016710

# Agar COMMAND_CHAT_ID Railway Variables me nahi hai,
# to commands TARGET_CHAT_ID wale group me chalengi.
COMMAND_CHAT_ID = int(
    os.getenv("COMMAND_CHAT_ID", str(TARGET_CHAT_ID))
)

# India time
IST = ZoneInfo("Asia/Kolkata")

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

def now_ist():
    return datetime.now(IST)


def today():
    return now_ist().strftime("%Y-%m-%d")


def date_string(d):
    return d.strftime("%Y-%m-%d")


# =========================================================
# ADMIN CHECK
# =========================================================

async def is_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

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

def is_command_group(update: Update):

    if not update.effective_chat:
        return False

    return (
        COMMAND_CHAT_ID == 0
        or update.effective_chat.id == COMMAND_CHAT_ID
    )


# =========================================================
# /start
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "✅ Wintask Bot is working!\n\n"
        "📌 Commands:\n\n"
        "/id - Current Chat ID\n"
        "/stats - Complete statistics\n"
        "/today - Today's statistics\n"
        "/yesterday - Yesterday's statistics\n"
        "/addlink NAME - Create new admin link\n"
        "/addlink NAME LINK - Add existing link\n"
        "/mylink - Your admin links\n"
        "/links - Admin-wise statistics"
    )


# =========================================================
# /id
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
# MEMBER TRACKING
# =========================================================

async def member_update(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    cm = update.chat_member

    if not cm:
        return

    # Sirf target group track hoga
    if cm.chat.id != TARGET_CHAT_ID:
        return

    old = cm.old_chat_member.status
    new = cm.new_chat_member.status

    user = cm.new_chat_member.user
    uid = str(user.id)

    # =====================================================
    # USER JOINED
    # =====================================================

    if new in (
        "member",
        "administrator"
    ) and old in (
        "left",
        "kicked"
    ):

        d = today()

        # Overall join count
        data["joins"][d] = (
            data["joins"].get(d, 0) + 1
        )

        # Invite link used by user
        invite = cm.invite_link

        if invite:

            url = invite.invite_link

            if url in data["admin_links"]:

                info = data["admin_links"][url]

                # Total joins
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

                users[uid] = {
                    "name": user.full_name,
                    "username": (
                        "@" + user.username
                        if user.username
                        else ""
                    )
                }

                # Remember user's link
                data["user_links"][uid] = url

        save_data()

    # =====================================================
    # USER LEFT
    # =====================================================

    elif new in (
        "left",
        "kicked"
    ) and old in (
        "member",
        "administrator"
    ):

        d = today()

        # Overall leave count
        data["leaves"][d] = (
            data["leaves"].get(d, 0) + 1
        )

        # Previous invite link
        url = data["user_links"].get(uid)

        if url and url in data["admin_links"]:

            info = data["admin_links"][url]

            info["leaves"] = (
                info.get("leaves", 0) + 1
            )

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
            "❌ Is chat me commands allowed nahi hain."
        )
        return

    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ Ye command sirf admin use kar sakta hai."
        )
        return

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
            f"❌ Target group error:\n{e}"
        )
        return

    td = now_ist().date()

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

    # =====================================================
    # JOINS
    # =====================================================

    for k, count in data["joins"].items():

        try:
            d = datetime.strptime(
                k,
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

    # =====================================================
    # LEAVES
    # =====================================================

    for k, count in data["leaves"].items():

        try:
            d = datetime.strptime(
                k,
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

    # =====================================================
    # REPORT
    # =====================================================

    text = (
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

        f"🆔 Group ID: {TARGET_CHAT_ID}"
    )

    await update.message.reply_text(text)


# =========================================================
# /today
# =========================================================

async def today_stats(
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

    d = now_ist().date()

    k = date_string(d)

    total_joined = data["joins"].get(k, 0)
    total_left = data["leaves"].get(k, 0)

    text = (
        "🟢 TODAY USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 Date: {k}\n\n"
    )

    found = False

    for url, info in data["admin_links"].items():

        daily = info.get("daily", {})

        daily_leaves = info.get(
            "daily_leaves",
            {}
        )

        joined = daily.get(k, 0)
        left = daily_leaves.get(k, 0)

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
            f"🔗 Link: {link_name}\n"
            f"🟢 Joined: {joined}\n"
            f"🔴 Left: {left}\n"
            f"👥 Net: {joined - left}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
        )

    if not found:

        text += (
            "ℹ️ Aaj kisi admin link se "
            "koi Join/Left record nahi mila.\n\n"
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
            "❌ Is chat me commands allowed nahi hain."
        )
        return

    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ Ye command sirf admin use kar sakta hai."
        )
        return

    d = now_ist().date() - timedelta(days=1)

    k = date_string(d)

    total_joined = data["joins"].get(k, 0)
    total_left = data["leaves"].get(k, 0)

    text = (
        "🟡 YESTERDAY USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 Date: {k}\n\n"
    )

    found = False

    for url, info in data["admin_links"].items():

        daily = info.get("daily", {})

        daily_leaves = info.get(
            "daily_leaves",
            {}
        )

        joined = daily.get(k, 0)
        left = daily_leaves.get(k, 0)

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
            f"🔗 Link: {link_name}\n"
            f"🟢 Joined: {joined}\n"
            f"🔴 Left: {left}\n"
            f"👥 Net: {joined - left}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
        )

    if not found:

        text += (
            "ℹ️ Kal kisi admin link se "
            "koi Join/Left record nahi mila.\n\n"
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
            "❌ Is chat me commands allowed nahi hain."
        )
        return

    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ Sirf group admin naya invite link add kar sakta hai."
        )
        return

    if not context.args:

        await update.message.reply_text(
            "❌ Link ka naam den.\n\n"
            "Naya link:\n"
            "/addlink Sachin\n\n"
            "Existing link:\n"
            "/addlink Sachin https://t.me/+XXXX"
        )
        return

    name = context.args[0].strip()

    if not name:

        await update.message.reply_text(
            "❌ Link name khali nahi ho sakta."
        )
        return

    user = update.effective_user

    # =====================================================
    # EXISTING LINK
    # =====================================================

    if len(context.args) >= 2:

        link = context.args[1].strip()

        if not (
            link.startswith("https://t.me/")
            or link.startswith("http://t.me/")
        ):

            await update.message.reply_text(
                "❌ Sahi Telegram invite link dein.\n\n"
                "Example:\n"
                "/addlink Sachin https://t.me/+XXXX"
            )
            return

        if link in data["admin_links"]:

            await update.message.reply_text(
                "❌ Ye link pehle se added hai."
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
            f"👤 Admin: {user.full_name}\n"
            f"🔗 Link Name: {name}\n"
            f"🔗 Link: {link}\n\n"
            "Ab is link se aane wale users "
            "ka Join/Leave record rakha jayega."
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
            f"👤 Admin: {user.full_name}\n"
            f"🔗 Link Name: {name}\n"
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
            "⚠️ Bot target group me ADMIN hona chahiye "
            "aur Invite Users permission honi chahiye."
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
            "❌ Is chat me commands allowed nahi hain."
        )
        return

    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ Ye command sirf admin use kar sakta hai."
        )
        return

    uid = update.effective_user.id

    found = False

    text = (
        "🔗 YOUR ADMIN LINKS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    for url, info in data["admin_links"].items():

        if info.get("admin_id") != uid:
            continue

        found = True

        joined = info.get
