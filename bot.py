import os
import sqlite3
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

# आपका TARGET GROUP
TARGET_CHAT_ID = -1004318016710

DB_FILE = "bot_data.db"


# =========================================================
# DATABASE
# =========================================================

def db_connect():
    return sqlite3.connect(DB_FILE)


def init_db():
    conn = db_connect()
    cur = conn.cursor()

    # Users / joins
    cur.execute("""
        CREATE TABLE IF NOT EXISTS joins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            admin_id INTEGER,
            admin_name TEXT,
            invite_link TEXT,
            joined_at TEXT
        )
    """)

    # Admin invite links
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            admin_name TEXT,
            invite_link TEXT UNIQUE,
            created_at TEXT
        )
    """)

    # Leaves
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leaves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            left_at TEXT
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# TIME
# =========================================================

def now():
    return datetime.now()


def today_start():
    n = now()
    return n.replace(hour=0, minute=0, second=0, microsecond=0)


def yesterday_start():
    return today_start() - timedelta(days=1)


def week_start():
    n = now()
    start = today_start()
    return start - timedelta(days=n.weekday())


def month_start():
    n = now()
    return start_of_month(n)


def start_of_month(dt):
    return dt.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )


# =========================================================
# ADMIN CHECK
# =========================================================

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.effective_chat:
        return False

    if not update.effective_user:
        return False

    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id,
            update.effective_user.id
        )

        return member.status in ["administrator", "creator"]

    except Exception:
        return False


# =========================================================
# TARGET GROUP CHECK
# =========================================================

async def check_target_group(update: Update):

    if not update.effective_chat:
        return False

    if update.effective_chat.id != TARGET_CHAT_ID:

        if update.message:
            await update.message.reply_text(
                "❌ यह command सिर्फ TARGET GROUP में use करें।\n\n"
                f"Target Group ID:\n{TARGET_CHAT_ID}"
            )

        return False

    return True


# =========================================================
# BOT ADMIN CHECK
# =========================================================

async def bot_is_admin(context):

    try:

        me = await context.bot.get_me()

        member = await context.bot.get_chat_member(
            TARGET_CHAT_ID,
            me.id
        )

        return member.status in ["administrator", "creator"]

    except Exception:

        return False


# =========================================================
# /START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "✅ Wintask Bot is working!\n\n"

        "Commands:\n"
        "/id - Current chat ID\n"
        "/today - Today's users\n"
        "/yesterday - Yesterday's users\n"
        "/week - This week's users\n"
        "/month - This month's users\n"
        "/stats - Complete statistics\n"
        "/addlink - Create admin invite link\n"
        "/links - Admin-wise statistics\n\n"

        "⚠️ Statistics commands TARGET GROUP में use करें।"
    )


# =========================================================
# /ID
# =========================================================

async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    chat = update.effective_chat

    await update.message.reply_text(
        "🆔 CHAT INFORMATION\n\n"
        f"📌 Name: {chat.title or 'Private Chat'}\n"
        f"💬 Type: {chat.type}\n"
        f"🆔 Chat ID: {chat.id}"
    )


# =========================================================
# MEMBER JOIN / LEAVE
# =========================================================

async def member_update(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_member = update.chat_member

    if not chat_member:
        return

    # केवल TARGET GROUP
    if chat_member.chat.id != TARGET_CHAT_ID:
        return

    old_status = chat_member.old_chat_member.status
    new_status = chat_member.new_chat_member.status

    user = chat_member.new_chat_member.user

    # =====================================================
    # JOIN
    # =====================================================

    if (
        new_status in ["member", "administrator"]
        and old_status in ["left", "kicked"]
    ):

        invite_link = None

        try:
            invite_link = chat_member.invite_link

        except Exception:
            invite_link = None

        admin_id = None
        admin_name = "Unknown"

        # Invite link किस admin की है?
        if invite_link:

            conn = db_connect()
            cur = conn.cursor()

            cur.execute(
                """
                SELECT admin_id, admin_name
                FROM admin_links
                WHERE invite_link = ?
                """,
                (invite_link.invite_link,)
            )

            row = cur.fetchone()

            conn.close()

            if row:

                admin_id = row[0]
                admin_name = row[1]

        conn = db_connect()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO joins
            (
                user_id,
                username,
                full_name,
                admin_id,
                admin_name,
                invite_link,
                joined_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user.id,
                user.username or "",
                user.full_name,
                admin_id,
                admin_name,
                invite_link.invite_link if invite_link else None,
                now().isoformat()
            )
        )

        conn.commit()
        conn.close()

    # =====================================================
    # LEAVE
    # =====================================================

    elif (
        new_status in ["left", "kicked"]
        and old_status in ["member", "administrator"]
    ):

        conn = db_connect()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO leaves
            (
                user_id,
                username,
                full_name,
                left_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                user.id,
                user.username or "",
                user.full_name,
                now().isoformat()
            )
        )

        conn.commit()
        conn.close()


# =========================================================
# COUNT JOINS
# =========================================================

def count_joins(start_time, end_time=None):

    conn = db_connect()
    cur = conn.cursor()

    if end_time:

        cur.execute(
            """
            SELECT COUNT(*)
            FROM joins
            WHERE joined_at >= ?
            AND joined_at < ?
            """,
            (
                start_time.isoformat(),
                end_time.isoformat()
            )
        )

    else:

        cur.execute(
            """
            SELECT COUNT(*)
            FROM joins
            WHERE joined_at >= ?
            """,
            (start_time.isoformat(),)
        )

    result = cur.fetchone()[0]

    conn.close()

    return result


# =========================================================
# COUNT LEAVES
# =========================================================

def count_leaves(start_time, end_time=None):

    conn = db_connect()
    cur = conn.cursor()

    if end_time:

        cur.execute(
            """
            SELECT COUNT(*)
            FROM leaves
            WHERE left_at >= ?
            AND left_at < ?
            """,
            (
                start_time.isoformat(),
                end_time.isoformat()
            )
        )

    else:

        cur.execute(
            """
            SELECT COUNT(*)
            FROM leaves
            WHERE left_at >= ?
            """,
            (start_time.isoformat(),)
        )

    result = cur.fetchone()[0]

    conn.close()

    return result


# =========================================================
# /TODAY
# =========================================================

async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await check_target_group(update):
        return

    if not await is_admin(update, context):
        return

    start = today_start()

    joins = count_joins(start)
    leaves = count_leaves(start)

    await update.message.reply_text(
        "🟢 TODAY STATISTICS\n\n"
        f"📥 New Users: {joins}\n"
        f"📤 Leaves: {leaves}\n\n"
        f"🆔 Group ID: {TARGET_CHAT_ID}"
    )


# =========================================================
# /YESTERDAY
# =========================================================

async def yesterday_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not await check_target_group(update):
        return

    if not await is_admin(update, context):
        return

    start = yesterday_start()
    end = today_start()

    joins = count_joins(start, end)
    leaves = count_leaves(start, end)

    await update.message.reply_text(
        "🟡 YESTERDAY STATISTICS\n\n"
        f"📥 New Users: {joins}\n"
        f"📤 Leaves: {leaves}\n\n"
        f"🆔 Group ID: {TARGET_CHAT_ID}"
    )


# =========================================================
# /WEEK
# =========================================================

async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await check_target_group(update):
        return

    if not await is_admin(update, context):
        return

    start = week_start()

    joins = count_joins(start)
    leaves = count_leaves(start)

    await update.message.reply_text(
        "🔵 THIS WEEK STATISTICS\n\n"
        f"📥 New Users: {joins}\n"
        f"📤 Leaves: {leaves}\n\n"
        f"🗓️ Week started: {start.strftime('%d-%m-%Y')}"
    )


# =========================================================
# /MONTH
# =========================================================

async def month_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not await check_target_group(update):
        return

    if not await is_admin(update, context):
        return

    start = month_start()

    joins = count_joins(start)
    leaves = count_leaves(start)

    await update.message.reply_text(
        "🟣 THIS MONTH STATISTICS\n\n"
        f"📥 New Users: {joins}\n"
        f"📤 Leaves: {leaves}\n\n"
        f"🗓️ Month: {now().strftime('%B %Y')}"
    )


# =========================================================
# /STATS
# =========================================================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await check_target_group(update):
        return

    if not await is_admin(update, context):
        return

    try:

        target_chat = await context.bot.get_chat(TARGET_CHAT_ID)

    except Exception as e:

        await update.message.reply_text(
            "❌ Target group access error!\n\n"
            f"{e}"
        )

        return

    if not await bot_is_admin(context):

        await update.message.reply_text(
            "❌ Bot target group में ADMIN नहीं है।\n\n"
            "Bot को group में ADMIN बनाइए।"
        )

        return

    today = count_joins(today_start())

    yesterday = count_joins(
        yesterday_start(),
        today_start()
    )

    week = count_joins(week_start())

    month = count_joins(month_start())

    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM joins")
    total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM leaves")
    total_leaves = cur.fetchone()[0]

    conn.close()

    await update.message.reply_text(

        "📊 GROUP USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"👥 Group:\n"
        f"{target_chat.title}\n\n"

        "📥 NEW USERS\n\n"

        f"🟢 Today: {today}\n"
        f"🟡 Yesterday: {yesterday}\n"
        f"🔵 This Week: {week}\n"
        f"🟣 This Month: {month}\n"
        f"⚪ Total: {total}\n\n"

        "📤 LEAVES\n"
        f"Total Leaves: {total_leaves}\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Group ID:\n{TARGET_CHAT_ID}"
    )


# =========================================================
# /ADDLINK
# =========================================================

async def addlink(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not await check_target_group(update):
        return

    if not await is_admin(update, context):
        await update.message.reply_text(
            "❌ यह command सिर्फ group admins use कर सकते हैं।"
        )
        return

    if not await bot_is_admin(context):

        await update.message.reply_text(
            "❌ पहले bot को target group में ADMIN बनाइए।"
        )

        return

    admin = update.effective_user

    try:

        # Admin के नाम से unique invite link
        link = await context.bot.create_chat_invite_link(
            chat_id=TARGET_CHAT_ID,
            name=admin.full_name[:32],
            creates_join_request=False
        )

        conn = db_connect()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT OR REPLACE INTO admin_links
            (
                admin_id,
                admin_name,
                invite_link,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                admin.id,
                admin.full_name,
                link.invite_link,
                now().isoformat()
            )
        )

        conn.commit()
        conn.close()

        await update.message.reply_text(
            "✅ ADMIN LINK CREATED\n\n"
            f"👤 Admin: {admin.full_name}\n\n"
            f"🔗 Invite Link:\n{link.invite_link}\n\n"
            "⚠️ इस link से आने वाले users इसी admin के नाम पर count होंगे."
        )

    except Exception as e:

        await update.message.reply_text(
            "❌ Link create नहीं हो पाई.\n\n"
            f"Error: {type(e).__name__}\n"
            f"Details: {e}\n\n"
            "Bot को group में invite users की permission वाला ADMIN बनाइए."
        )


# =========================================================
# /LINKS
# =========================================================

async def links(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await check_target_group(update):
        return

    if not await is_admin(update, context):
        return

    conn = db_connect()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            admin_id,
            admin_name,
            invite_link
        FROM admin_links
        ORDER BY id DESC
        """
    )

    admin_links = cur.fetchall()

    if not admin_links:

        conn.close()

        await update.message.reply_text(
            "📊 ADMIN LINKS\n\n"
            "अभी कोई admin link नहीं बनी है.\n\n"
            "नई link बनाने के लिए:\n"
            "/addlink"
        )

        return

    text = "📊 ADMIN-WISE STATISTICS\n"
    text += "━━━━━━━━━━━━━━━━━━\n\n"

    for admin_id, admin_name, invite_link in admin_links:

        cur.execute(
            """
            SELECT COUNT(*)
            FROM joins
            WHERE admin_id = ?
            """,
            (admin_id,)
        )

        total = cur.fetchone()[0]

        cur.execute(
            """
            SELECT COUNT(*)
            FROM joins
            WHERE admin_id = ?
            AND joined_at >= ?
            """,
            (
                admin_id,
                today_start().isoformat()
            )
        )

        today_count = cur.fetchone()[0]

        cur.execute(
            """
            SELECT COUNT(*)
            FROM joins
            WHERE admin_id = ?
            AND joined_at >= ?
            AND joined_at < ?
            """,
            (
                admin_id,
                yesterday_start().isoformat(),
                today_start().isoformat()
            )
        )

        yesterday_count = cur.fetchone()[0]

        cur.execute(
            """
            SELECT COUNT(*)
            FROM joins
            WHERE admin_id = ?
            AND joined_at >= ?
            """,
            (
                admin_id,
                week_start().isoformat()
            )
        )

        week_count = cur.fetchone()[0]

        cur.execute(
            """
            SELECT COUNT(*)
            FROM joins
            WHERE admin_id = ?
            AND joined_at >= ?
            """,
            (
                admin_id,
                month_start().isoformat()
            )
        )

        month_count = cur.fetchone()[0]

        text += (
            f"👤 {admin_name}\n"
            f"🆔 Admin ID: {admin_id}\n\n"
            f"🟢 Today: {today_count}\n"
            f"🟡 Yesterday: {yesterday_count}\n"
            f"🔵 This Week: {week_count}\n"
            f"🟣 This Month: {month_count}\n"
            f"⚪ Total: {total}\n\n"
            f"🔗 {invite_link}\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
        )

    conn.close()

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

    # Database बनाओ
    init_db()

    print("🤖 Wintask Bot started...")

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
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("id", chat_id)
    )

    app.add_handler(
        CommandHandler("stats", stats)
    )

    app.add_handler(
        CommandHandler("today", today_command)
    )

    app.add_handler(
        CommandHandler("yesterday", yesterday_comm
