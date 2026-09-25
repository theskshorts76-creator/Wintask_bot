import os
import sqlite3
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

# YOUR TARGET GROUP
TARGET_CHAT_ID = -1004318016710

# India Time
IST = ZoneInfo("Asia/Kolkata")

# Database file
DB_FILE = "bot_data.db"


# =========================================================
# DATABASE
# =========================================================

def db_connect():
    return sqlite3.connect(DB_FILE)


def init_db():

    conn = db_connect()
    cur = conn.cursor()

    # All joins
    cur.execute("""
        CREATE TABLE IF NOT EXISTS joins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT,
            joined_at TEXT,
            invite_link TEXT,
            admin_id INTEGER,
            admin_name TEXT
        )
    """)

    # Admin invite links
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER UNIQUE,
            admin_name TEXT,
            invite_link TEXT
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# TIME
# =========================================================

def now_ist():
    return datetime.now(IST)


def today_date():
    return now_ist().date()


def start_of_today():
    n = now_ist()
    return n.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )


def start_of_yesterday():

    return start_of_today() - timedelta(days=1)


def end_of_yesterday():

    return start_of_today()


def start_of_week():

    n = start_of_today()

    # Monday = 0
    return n - timedelta(days=n.weekday())


def start_of_month():

    n = now_ist()

    return n.replace(
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

        return member.status in [
            "administrator",
            "creator"
        ]

    except Exception as e:

        print("ADMIN CHECK ERROR:", e)

        return False


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "✅ Wintask Bot is working!\n\n"
        "Commands:\n"
        "/id - Current chat ID\n"
        "/stats - Full statistics\n"
        "/mylink - Create your admin invite link\n"
        "/links - Admin-wise statistics"
    )


# =========================================================
# ID COMMAND
# =========================================================

async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat = update.effective_chat

    if not chat:
        return

    chat_type = chat.type

    await update.message.reply_text(
        "🆔 CHAT INFORMATION\n\n"
        f"📌 Name: {chat.title or 'Private Chat'}\n"
        f"💬 Type: {chat_type}\n"
        f"🆔 Chat ID: {chat.id}"
    )


# =========================================================
# CREATE ADMIN INVITE LINK
# =========================================================

async def mylink(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.effective_chat:
        return

    # Only target group
    if update.effective_chat.id != TARGET_CHAT_ID:

        await update.message.reply_text(
            "❌ Ye command sirf target group me use karein."
        )

        return

    # Only admins
    if not await is_admin(update, context):

        await update.message.reply_text(
            "❌ Sirf group admins ye command use kar sakte hain."
        )

        return

    admin = update.effective_user

    admin_id = admin.id

    admin_name = (
        admin.full_name
        or admin.username
        or str(admin_id)
    )

    conn = db_connect()
    cur = conn.cursor()

    # Check existing link
    cur.execute(
        """
        SELECT invite_link
        FROM admin_links
        WHERE admin_id = ?
        """,
        (admin_id,)
    )

    existing = cur.fetchone()

    if existing:

        conn.close()

        await update.message.reply_text(
            "🔗 Aapki invite link already bani hui hai.\n\n"
            f"👤 Admin: {admin_name}\n\n"
            f"🔗 {existing[0]}\n\n"
            "Isi link ko users ke saath share karein."
        )

        return

    # Create unique invite link
    try:

        invite = await context.bot.create_chat_invite_link(
            chat_id=TARGET_CHAT_ID,
            name=admin_name[:32],
            creates_join_request=False
        )

    except Exception as e:

        conn.close()

        await update.message.reply_text(
            "❌ Invite link create nahi ho paayi.\n\n"
            f"Error: {type(e).__name__}\n"
            f"{e}\n\n"
            "⚠️ Bot ko group me invite users permission wala ADMIN hona chahiye."
        )

        return

    invite_link = invite.invite_link

    # Save link
    cur.execute(
        """
        INSERT OR REPLACE INTO admin_links
        (admin_id, admin_name, invite_link)
        VALUES (?, ?, ?)
        """,
        (
            admin_id,
            admin_name,
            invite_link
        )
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ ADMIN INVITE LINK CREATED\n\n"
        f"👤 Admin: {admin_name}\n"
        f"🆔 Admin ID: {admin_id}\n\n"
        f"🔗 {invite_link}\n\n"
        "📌 Is link ko users ke saath share karein.\n"
        "Is link se join hone wale users aapke naam ke neeche count honge."
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

    old_status = chat_member.old_chat_member.status
    new_status = chat_member.new_chat_member.status

    # JOIN
    if (
        new_status in ["member", "administrator"]
        and old_status in ["left", "kicked"]
    ):

        user = chat_member.new_chat_member.user

        user_id = user.id

        user_name = (
            user.full_name
            or user.username
            or str(user_id)
        )

        joined_at = now_ist().isoformat()

        # Telegram gives the invite link used for this join
        invite_link = None
        admin_id = None
        admin_name = None

        if chat_member.invite_link:

            invite_link = chat_member.invite_link.invite_link

            conn = db_connect()
            cur = conn.cursor()

            cur.execute(
                """
                SELECT admin_id, admin_name
                FROM admin_links
                WHERE invite_link = ?
                """,
                (invite_link,)
            )

            result = cur.fetchone()

            conn.close()

            if result:

                admin_id = result[0]
                admin_name = result[1]

        # Save join
        conn = db_connect()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO joins
            (
                user_id,
                user_name,
                joined_at,
                invite_link,
                admin_id,
                admin_name
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                user_name,
                joined_at,
                invite_link,
                admin_id,
                admin_name
            )
        )

        conn.commit()
        conn.close()

        print(
            f"JOIN: {user_name} | "
            f"Admin: {admin_name} | "
            f"Link: {invite_link}"
        )


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
# STATS COMMAND
# =========================================================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update, context):
        return

    if update.effective_chat.id != TARGET_CHAT_ID:

        await update.message.reply_text(
            "❌ /stats target group me use karein."
        )

        return

    today_start = start_of_today()

    yesterday_start = start_of_yesterday()
    yesterday_end = end_of_yesterday()

    week_start = start_of_week()

    month_start = start_of_month()

    today_count = count_joins(today_start)

    yesterday_count = count_joins(
        yesterday_start,
        yesterday_end
    )

    week_count = count_joins(week_start)

    month_count = count_joins(month_start)

    total_count = count_joins(
        datetime.min.replace(tzinfo=IST)
    )

    try:

        target_chat = await context.bot.get_chat(
            TARGET_CHAT_ID
        )

        group_name = target_chat.title

    except Exception:

        group_name = "Target Group"

    text = (
        "📊 GROUP USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"👥 Group:\n"
        f"{group_name}\n\n"

        "📥 NEW USERS\n\n"

        f"🟢 Today: {today_count}\n"
        f"🟡 Yesterday: {yesterday_count}\n"
        f"🔵 This Week: {week_count}\n"
        f"🟣 This Month: {month_count}\n"
        f"⚪ Total: {total_count}\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Group ID:\n{TARGET_CHAT_ID}"
    )

    await update.message.reply_text(text)


# =========================================================
# ADMIN-WISE LINKS STATISTICS
# =========================================================

async def links(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update, context):
        return

    if update.effective_chat.id != TARGET_CHAT_ID:

        await update.message.reply_text(
            "❌ /links target group me use karein."
        )

        return

    today_start = start_of_today()

    yesterday_start = start_of_yesterday()
    yesterday_end = end_of_yesterday()

    week_start = start_of_week()

    month_start = start_of_month()

    conn = db_connect()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            admin_id,
            admin_name,
            invite_link
        FROM admin_links
        ORDER BY admin_name
        """
    )

    admins = cur.fetchall()

    if not admins:

        conn.close()

        await update.message.reply_text(
            "❌ Abhi kisi admin ne /mylink se link nahi banayi.\n\n"
            "Har admin target group me /mylink bheje."
        )

        return

    text = "🔗 ADMIN LINK STATISTICS\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"

    for admin_id, admin_name, invite_link in admins:

        # Today
        cur.execute(
            """
            SELECT COUNT(*)
            FROM joins
            WHERE admin_id = ?
            AND joined_at >= ?
            """,
            (
                admin_id,
                today_start.isoformat()
            )
        )

        today_count = cur.fetchone()[0]

        # Yesterday
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
                yesterday_start.isoformat(),
                yesterday_end.isoformat()
            )
        )

        yesterday_count = cur.fetchone()[0]

        # Week
        cur.execute(
            """
            SELECT COUNT(*)
            FROM joins
            WHERE admin_id = ?
            AND joined_at >= ?
            """,
            (
                admin_id,
                week_start.isoformat()
            )
        )

        week_count = cur.fetchone()[0]

        # Month
        cur.execute(
            """
            SELECT COUNT(*)
            FROM joins
            WHERE admin_id = ?
            AND joined_at >= ?
            """,
            (
                admin_id,
                month_start.isoformat()
            )
        )

        month_count = cur.fetchone()[0]

        # Total
        cur.execute(
            """
            SELECT COUNT(*)
            FROM joins
            WHERE admin_id = ?
            """,
            (admin_id,)
        )

        total_count = cur.fetchone()[0]

        text += (
            f"👤 {admin_name}\n"
            f"🔗 {invite_link}\n\n"
            f"🟢 Today: {today_count}\n"
            f"🟡 Yesterday: {yesterday_count}\n"
            f"🔵 Week: {week_count}\n"
            f"🟣 Month: {month_count}\n"
            f"⚪ Total: {total_count}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
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

    print("🤖 Bot started...")

    # Database
    init_db()

    # Telegram application
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
        CommandHandler("mylink", mylink)
    )

    app.add_handler(
        CommandHandler("links", links)
    )

    # Member tracking
    app.add_handler(
        ChatMemberHandler(
            member_update,
            ChatMemberHandler.CHAT_MEMBER
        )
    )

    # Error handler
    app.add_error_handler(error_handler)

    # Start
    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
