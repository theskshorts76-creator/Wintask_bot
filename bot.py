import os
import json
from datetime import datetime, timedelta
from collections import defaultdict

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

# DATA FILE
DATA_FILE = "bot_data.json"


# =========================================================
# DATA
# =========================================================

data = {
    "users": {},
    "admin_links": {}
}


# =========================================================
# LOAD DATA
# =========================================================

def load_data():
    global data

    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)

                if isinstance(loaded, dict):
                    data.update(loaded)

    except Exception as e:
        print("LOAD ERROR:", e)


# =========================================================
# SAVE DATA
# =========================================================

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
# TIME
# =========================================================

def now():
    return datetime.now()


def date_string(dt):
    return dt.strftime("%Y-%m-%d")


def today():
    return date_string(now())


def yesterday():
    return date_string(
        now() - timedelta(days=1)
    )


def week_start():
    n = now()

    return (
        n - timedelta(days=n.weekday())
    ).date()


def month_start():
    n = now()

    return n.replace(
        day=1
    ).date()


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

        return member.status in [
            "administrator",
            "creator"
        ]

    except Exception as e:

        print(
            "ADMIN CHECK ERROR:",
            e
        )

        return False


# =========================================================
# TARGET GROUP CHECK
# =========================================================

def is_target_group(update: Update):

    if not update.effective_chat:
        return False

    return (
        update.effective_chat.id
        == TARGET_CHAT_ID
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

        "📊 STATISTICS\n"
        "/today - Today's new users\n"
        "/yesterday - Yesterday's new users\n"
        "/week - This week's new users\n"
        "/month - This month's new users\n"
        "/stats - Complete statistics\n\n"

        "🔗 ADMIN LINKS\n"
        "/mylink - Create your admin invite link\n"
        "/addlink - Create a NEW admin invite link\n"
        "/links - Admin-wise link statistics\n\n"

        "ℹ️ OTHER\n"
        "/id - Current chat ID"
    )


# =========================================================
# CHAT ID
# =========================================================

async def chat_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    chat = update.effective_chat

    await update.message.reply_text(

        "🆔 CHAT INFORMATION\n\n"

        f"📌 Name: "
        f"{chat.title or 'Private Chat'}\n"

        f"💬 Type: "
        f"{chat.type}\n"

        f"🆔 Chat ID: "
        f"{chat.id}"
    )


# =========================================================
# MEMBER JOIN TRACKING
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

    old_status = (
        chat_member
        .old_chat_member
        .status
    )

    new_status = (
        chat_member
        .new_chat_member
        .status
    )

    # =====================================================
    # NEW USER JOINED
    # =====================================================

    if (
        new_status in [
            "member",
            "administrator"
        ]
        and
        old_status in [
            "left",
            "kicked"
        ]
    ):

        user = (
            chat_member
            .new_chat_member
            .user
        )

        user_id = str(user.id)

        join_time = now()

        join_date = date_string(
            join_time
        )

        # =================================================
        # INVITE LINK
        # =================================================

        invite_link = (
            chat_member.invite_link
        )

        admin_id = None
        admin_name = None
        saved_link = ""

        if invite_link:

            saved_link = (
                invite_link.invite_link
            )

            if (
                saved_link
                in data["admin_links"]
            ):

                admin_id = (
                    data["admin_links"]
                    [saved_link]
                    ["admin_id"]
                )

                admin_name = (
                    data["admin_links"]
                    [saved_link]
                    ["admin_name"]
                )

        # =================================================
        # SAVE USER
        # =================================================

        data["users"][user_id] = {

            "user_id": user.id,

            "name": user.full_name,

            "username":
                user.username or "",

            "joined_at":
                join_time.isoformat(),

            "date":
                join_date,

            "admin_id":
                admin_id,

            "admin_name":
                admin_name,

            "invite_link":
                saved_link
        }

        save_data()

        print(
            "NEW USER:",
            user.full_name,
            "| ADMIN:",
            admin_name,
            "| DATE:",
            join_date
        )


# =========================================================
# GET USERS
# =========================================================

def get_users():

    return list(
        data
        .get("users", {})
        .values()
    )


# =========================================================
# TODAY
# =========================================================

def count_today():

    d = today()

    return sum(

        1

        for user in get_users()

        if user.get("date") == d
    )


# =========================================================
# YESTERDAY
# =========================================================

def count_yesterday():

    d = yesterday()

    return sum(

        1

        for user in get_users()

        if user.get("date") == d
    )


# =========================================================
# WEEK
# =========================================================

def count_week():

    start = week_start()

    total = 0

    for user in get_users():

        try:

            d = datetime.strptime(

                user.get(
                    "date",
                    ""
                ),

                "%Y-%m-%d"

            ).date()

            if d >= start:
                total += 1

        except Exception:
            pass

    return total


# =========================================================
# MONTH
# =========================================================

def count_month():

    start = month_start()

    total = 0

    for user in get_users():

        try:

            d = datetime.strptime(

                user.get(
                    "date",
                    ""
                ),

                "%Y-%m-%d"

            ).date()

            if d >= start:
                total += 1

        except Exception:
            pass

    return total


# =========================================================
# TODAY COMMAND
# =========================================================

async def today_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_target_group(update):

        await update.message.reply_text(
            "❌ Ye command sirf target group "
            "me use karein."
        )

        return

    if not await is_admin(
        update,
        context
    ):
        return

    await update.message.reply_text(

        "📅 TODAY USER STATISTICS\n\n"

        f"🟢 Today: {count_today()}"
    )


# =========================================================
# YESTERDAY COMMAND
# =========================================================

async def yesterday_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_target_group(update):

        await update.message.reply_text(
            "❌ Ye command sirf target group "
            "me use karein."
        )

        return

    if not await is_admin(
        update,
        context
    ):
        return

    await update.message.reply_text(

        "📅 YESTERDAY USER STATISTICS\n\n"

        f"🟡 Yesterday: "
        f"{count_yesterday()}"
    )


# =========================================================
# WEEK COMMAND
# =========================================================

async def week_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_target_group(update):

        await update.message.reply_text(
            "❌ Ye command sirf target group "
            "me use karein."
        )

        return

    if not await is_admin(
        update,
        context
    ):
        return

    await update.message.reply_text(

        "📅 WEEKLY USER STATISTICS\n\n"

        f"🔵 This Week: "
        f"{count_week()}"
    )


# =========================================================
# MONTH COMMAND
# =========================================================

async def month_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_target_group(update):

        await update.message.reply_text(
            "❌ Ye command sirf target group "
            "me use karein."
        )

        return

    if not await is_admin(
        update,
        context
    ):
        return

    await update.message.reply_text(

        "📅 MONTHLY USER STATISTICS\n\n"

        f"🟣 This Month: "
        f"{count_month()}"
    )


# =========================================================
# COMPLETE STATS
# =========================================================

async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_target_group(update):

        await update.message.reply_text(
            "❌ /stats sirf target group "
            "me use karein."
        )

        return

    if not await is_admin(
        update,
        context
    ):
        return

    try:

        target_chat = (
            await context.bot.get_chat(
                TARGET_CHAT_ID
            )
        )

        group_name = (
            target_chat.title
        )

    except Exception:

        group_name = "Target Group"

    await update.message.reply_text(

        "📊 GROUP USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"👥 Group:\n"
        f"{group_name}\n\n"

        "📥 NEW USERS\n\n"

        f"🟢 Today: "
        f"{count_today()}\n"

        f"🟡 Yesterday: "
        f"{count_yesterday()}\n"

        f"🔵 This Week: "
        f"{count_week()}\n"

        f"🟣 This Month: "
        f"{count_month()}\n"

        f"⚪ Total: "
        f"{len(get_users())}\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        f"🆔 Group ID:\n"
        f"{TARGET_CHAT_ID}"
    )


# =========================================================
# CREATE ADMIN LINK FUNCTION
# =========================================================

async def create_admin_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_target_group(update):

        await update.message.reply_text(
            "❌ Ye command sirf target group "
            "me use karein."
        )

        return

    if not await is_admin(
        update,
        context
    ):

        await update.message.reply_text(
            "❌ Sirf group admins "
            "ye command use kar sakte hain."
        )

        return

    admin = update.effective_user

    admin_id = str(admin.id)

    admin_name = admin.full_name

    try:

        # =================================================
        # CREATE NEW UNIQUE INVITE LINK
        # =================================================

        invite = (
            await context.bot
            .create_chat_invite_link(

                chat_id=TARGET_CHAT_ID,

                name=(
                    f"{admin_name}"
                ),

                creates_join_request=False
            )
        )

        link = invite.invite_link

        # =================================================
        # SAVE ADMIN LINK
        # =================================================

        data["admin_links"][link] = {

            "admin_id":
                admin_id,

            "admin_name":
                admin_name,

            "created_at":
                now().isoformat()
        }

        save_data()

        await update.message.reply_text(

            "🔗 NEW ADMIN INVITE LINK\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"

            f"👤 Admin:\n"
            f"{admin_name}\n\n"

            f"🆔 Admin ID:\n"
            f"{admin.id}\n\n"

            "🔗 Invite Link:\n"
            f"{link}\n\n"

            "👥 Is link se jo users "
            "join karenge wo isi admin "
            "ke naam par count honge.\n\n"

            "📊 Users dekhne ke liye:\n"
            "/links"
        )

    except Exception as e:

        await update.message.reply_text(

            "❌ New admin link create "
            "nahi ho payi.\n\n"

            f"Error: "
            f"{type(e).__name__}\n"

            f"Details: {e}\n\n"

            "⚠️ Bot target group me ADMIN "
            "hona chahiye aur invite "
            "users permission honi chahiye."
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
# ADMIN-WISE LINKS
# =========================================================

async def links(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_target_group(update):

        await update.message.reply_text(
            "❌ /links sirf target group "
            "me use karein."
        )

        return

    if not await is_admin(
        update,
        context
    ):
        return

    admin_stats = defaultdict(
        lambda: {
            "name": "",
            "count": 0
        }
    )

    # =====================================================
    # COUNT USERS BY ADMIN
    # =====================================================

    for user in get_users():

        admin_id = user.get(
            "admin_id"
        )

        if not admin_id:
            continue

        admin_name = user.get(
            "admin_name",
            "Unknown Admin"
        )

        admin_stats[
            admin_id
        ]["name"] = admin_name

        admin_stats[
            admin_id
        ]["count"] += 1

    # =====================================================
    # RESULT
    # =====================================================

    text = (
        "🔗 ADMIN-WISE USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    if not admin_stats:

        text += (
            "❌ Abhi kisi admin ki link "
            "se koi user track nahi hua."
        )

    else:

        number = 1

        for admin_id, info in (
            admin_stats.items()
        ):

            text += (

                f"{number}. 👤 "
                f"{info['name']}\n"

                f"   🆔 Admin ID: "
                f"{admin_id}\n"

                f"   👥 Users: "
                f"{info['count']}\n\n"
            )

            number += 1

    text += (
        "━━━━━━━━━━━━━━━━━━━━\n"

        f"📊 Total tracked users: "
        f"{len(get_users())}"
    )

    await update.message.reply_text(
        text
    )


# =========================================================
# ERROR HANDLER
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
        "🤖 Wintask Bot started..."
    )

    load_data()

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # =====================================================
    # COMMANDS
    # =====================================================

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "id",
            chat_id
        )
    )

    app.add_handler(
        CommandHandler(
            "today",
            today_command
        )
    )

    app.add_handler(
        CommandHandler(
            "yesterday",
            yesterday_command
        )
    )

    app.add_handler(
        CommandHandler(
            "week",
            week_command
        )
    )

    app.add_handler(
        CommandHandler(
            "month",
            month_command
        )
    )

    app.add_handler(
        CommandHandler(
            "stats",
            stats
        )
    )

    app.add_handler(
        CommandHandler(
            "mylink",
            mylink
        )
    )

    app.add_handler(
        CommandHandler(
            "addlink",
            addlink
        )
    )

    app.add_handler(
        CommandHandler(
            "links",
            links
        )
    )

    # =====================================================
    # MEMBER TRACKING
    # =====================================================

    app.add_handler(
        ChatMemberHandler(
            member_update,
            ChatMemberHandl
