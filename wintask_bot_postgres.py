import os
import json
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

import psycopg
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ChatMemberHandler,
    ContextTypes,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

TARGET_CHAT_ID = -1004318016710
COMMAND_CHAT_ID = -1003353359019
IST = ZoneInfo("Asia/Kolkata")
DATA_FILE = "bot_data.json"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN Railway Variables me set nahi hai.")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL Railway Variables me set nahi hai.")


# ============================================================
# DATABASE
# ============================================================

def db():
    return psycopg.connect(DATABASE_URL)


def init_db():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS migration_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS invite_links (
                    invite_link TEXT PRIMARY KEY,
                    admin_name TEXT NOT NULL,
                    link_name TEXT NOT NULL,
                    joins BIGINT NOT NULL DEFAULT 0,
                    leaves BIGINT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_totals (
                    event_date DATE PRIMARY KEY,
                    joins BIGINT NOT NULL DEFAULT 0,
                    leaves BIGINT NOT NULL DEFAULT 0
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS invite_link_daily (
                    invite_link TEXT NOT NULL REFERENCES invite_links(invite_link)
                        ON DELETE CASCADE,
                    event_date DATE NOT NULL,
                    joins BIGINT NOT NULL DEFAULT 0,
                    leaves BIGINT NOT NULL DEFAULT 0,
                    PRIMARY KEY (invite_link, event_date)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_attribution (
                    user_id TEXT PRIMARY KEY,
                    invite_link TEXT,
                    user_name TEXT,
                    username TEXT,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)


def migration_done():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM migration_state WHERE key = 'json_migrated'"
            )
            row = cur.fetchone()
            return bool(row and row[0] == "1")


def mark_migration_done():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO migration_state(key, value)
                VALUES ('json_migrated', '1')
                ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
            """)


def migrate_old_json():
    """
    First deployment par purane bot_data.json ko PostgreSQL me copy karta hai.
    Migration sirf ek baar hoti hai.
    Purani JSON file delete nahi hoti.
    """
    if migration_done():
        return

    if not os.path.exists(DATA_FILE):
        mark_migration_done()
        print("No old bot_data.json found. Starting with empty PostgreSQL data.", flush=True)
        return

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            old = json.load(f)
    except Exception as e:
        print(f"Old JSON read error: {e}", flush=True)
        return

    joins = old.get("joins", {}) if isinstance(old.get("joins"), dict) else {}
    leaves = old.get("leaves", {}) if isinstance(old.get("leaves"), dict) else {}
    links = old.get("admin_links", {}) if isinstance(old.get("admin_links"), dict) else {}
    user_links = old.get("user_links", {}) if isinstance(old.get("user_links"), dict) else {}

    try:
        with db() as conn:
            with conn.cursor() as cur:

                # Import overall daily totals.
                for day_text, count in joins.items():
                    try:
                        d = date.fromisoformat(str(day_text))
                        j = int(count or 0)
                    except Exception:
                        continue

                    cur.execute("""
                        INSERT INTO daily_totals(event_date, joins, leaves)
                        VALUES (%s, %s, 0)
                        ON CONFLICT(event_date)
                        DO UPDATE SET joins = daily_totals.joins + EXCLUDED.joins
                    """, (d, j))

                for day_text, count in leaves.items():
                    try:
                        d = date.fromisoformat(str(day_text))
                        l = int(count or 0)
                    except Exception:
                        continue

                    cur.execute("""
                        INSERT INTO daily_totals(event_date, joins, leaves)
                        VALUES (%s, 0, %s)
                        ON CONFLICT(event_date)
                        DO UPDATE SET leaves = daily_totals.leaves + EXCLUDED.leaves
                    """, (d, l))

                # Import registered invite links and their historical counts.
                for url, info in links.items():
                    if not isinstance(info, dict):
                        continue

                    admin_name = str(
                        info.get("admin_name")
                        or info.get("link_name")
                        or "Unknown"
                    )
                    link_name = str(
                        info.get("link_name")
                        or info.get("admin_name")
                        or "Unnamed"
                    )
                    total_joins = int(info.get("joins", 0) or 0)
                    total_leaves = int(info.get("leaves", 0) or 0)

                    cur.execute("""
                        INSERT INTO invite_links(
                            invite_link, admin_name, link_name, joins, leaves
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT(invite_link) DO NOTHING
                    """, (
                        str(url),
                        admin_name,
                        link_name,
                        total_joins,
                        total_leaves,
                    ))

                    daily_joins = info.get("daily_joins")
                    if not isinstance(daily_joins, dict):
                        daily_joins = info.get("daily", {})
                    if not isinstance(daily_joins, dict):
                        daily_joins = {}

                    daily_leaves = info.get("daily_leaves", {})
                    if not isinstance(daily_leaves, dict):
                        daily_leaves = {}

                    for day_text, count in daily_joins.items():
                        try:
                            d = date.fromisoformat(str(day_text))
                            j = int(count or 0)
                        except Exception:
                            continue

                        cur.execute("""
                            INSERT INTO invite_link_daily(
                                invite_link, event_date, joins, leaves
                            )
                            VALUES (%s, %s, %s, 0)
                            ON CONFLICT(invite_link, event_date)
                            DO UPDATE SET joins =
                                invite_link_daily.joins + EXCLUDED.joins
                        """, (str(url), d, j))

                    for day_text, count in daily_leaves.items():
                        try:
                            d = date.fromisoformat(str(day_text))
                            l = int(count or 0)
                        except Exception:
                            continue

                        cur.execute("""
                            INSERT INTO invite_link_daily(
                                invite_link, event_date, joins, leaves
                            )
                            VALUES (%s, %s, 0, %s)
                            ON CONFLICT(invite_link, event_date)
                            DO UPDATE SET leaves =
                                invite_link_daily.leaves + EXCLUDED.leaves
                        """, (str(url), d, l))

                # Import old user -> invite attribution.
                for uid, url in user_links.items():
                    cur.execute("""
                        SELECT admin_name
                        FROM invite_links
                        WHERE invite_link = %s
                    """, (str(url),))
                    row = cur.fetchone()
                    admin_name = row[0] if row else ""

                    cur.execute("""
                        INSERT INTO user_attribution(
                            user_id, invite_link, user_name, username
                        )
                        VALUES (%s, %s, '', '')
                        ON CONFLICT(user_id) DO UPDATE SET
                            invite_link = EXCLUDED.invite_link,
                            updated_at = NOW()
                    """, (str(uid), str(url)))

                cur.execute("""
                    INSERT INTO migration_state(key, value)
                    VALUES ('json_migrated', '1')
                    ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
                """)

        print("SUCCESS: old bot_data.json data migrated to PostgreSQL.", flush=True)

    except Exception as e:
        print(f"POSTGRES MIGRATION ERROR: {e}", flush=True)
        raise


# ============================================================
# DATE / ACCESS HELPERS
# ============================================================

def today_date():
    return datetime.now(IST).date()


def day_key(days_ago=0):
    return (today_date() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def command_group(update):
    return bool(
        update.effective_chat
        and update.effective_chat.id == COMMAND_CHAT_ID
    )


async def is_admin(update, context):
    if not update.effective_chat or not update.effective_user:
        return False

    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id,
            update.effective_user.id,
        )
        return member.status in ("administrator", "creator")
    except Exception as e:
        print(f"Admin check error: {e}", flush=True)
        return False


async def check_access(update, context):
    if not update.message:
        return False

    if not command_group(update):
        await update.message.reply_text(
            "❌ Is chat me commands allowed nahi hain."
        )
        return False

    if not await is_admin(update, context):
        await update.message.reply_text(
            "❌ Ye command sirf admin use kar sakta hai."
        )
        return False

    return True


# ============================================================
# DATABASE WRITE HELPERS
# ============================================================

def add_daily_total(event_date, joins=0, leaves=0):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO daily_totals(event_date, joins, leaves)
                VALUES (%s, %s, %s)
                ON CONFLICT(event_date)
                DO UPDATE SET
                    joins = daily_totals.joins + EXCLUDED.joins,
                    leaves = daily_totals.leaves + EXCLUDED.leaves
            """, (event_date, joins, leaves))


def add_link_event(url, event_date, joins=0, leaves=0):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO invite_link_daily(
                    invite_link, event_date, joins, leaves
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT(invite_link, event_date)
                DO UPDATE SET
                    joins = invite_link_daily.joins + EXCLUDED.joins,
                    leaves = invite_link_daily.leaves + EXCLUDED.leaves
            """, (url, event_date, joins, leaves))

            cur.execute("""
                UPDATE invite_links
                SET joins = joins + %s,
                    leaves = leaves + %s
                WHERE invite_link = %s
            """, (joins, leaves, url))


def save_user_attribution(user_id, url, user_name, username):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO user_attribution(
                    user_id, invite_link, user_name, username
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT(user_id)
                DO UPDATE SET
                    invite_link = EXCLUDED.invite_link,
                    user_name = EXCLUDED.user_name,
                    username = EXCLUDED.username,
                    updated_at = NOW()
            """, (str(user_id), url, user_name, username))


def get_user_attribution(user_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT invite_link
                FROM user_attribution
                WHERE user_id = %s
            """, (str(user_id),))
            row = cur.fetchone()
            return row[0] if row else None


# ============================================================
# FORMATTING
# ============================================================

def format_link_block(admin_name, link_name, url, joins, leaves):
    return (
        f"👤 Agent: {admin_name}\n"
        f"🔗 Link Name: {link_name}\n"
        f"🟢 Joined: {joins}\n"
        f"🔴 Left: {leaves}\n"
        f"👥 Net: {joins - leaves}\n"
        f"🔗 {url}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    )


# ============================================================
# COMMANDS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "✅ Wintask Bot is working!\n\n"
            "📌 Commands:\n"
            "/id\n"
            "/stats\n"
            "/today\n"
            "/yesterday\n"
            "/addlink NAME LINK  ← existing link only\n"
            "/mylink\n"
            "/links"
        )


async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.effective_chat:
        c = update.effective_chat
        await update.message.reply_text(
            f"🆔 Chat ID: {c.id}\n"
            f"💬 Type: {c.type}\n"
            f"📌 Name: {c.title or 'Private Chat'}"
        )


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    d = today_date()

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT joins, leaves
                FROM daily_totals
                WHERE event_date = %s
            """, (d,))
            total = cur.fetchone() or (0, 0)

            cur.execute("""
                SELECT
                    l.admin_name,
                    l.link_name,
                    l.invite_link,
                    COALESCE(d.joins, 0),
                    COALESCE(d.leaves, 0)
                FROM invite_links l
                LEFT JOIN invite_link_daily d
                    ON d.invite_link = l.invite_link
                    AND d.event_date = %s
                WHERE COALESCE(d.joins, 0) > 0
                   OR COALESCE(d.leaves, 0) > 0
                ORDER BY COALESCE(d.joins, 0) DESC, l.admin_name
            """, (d,))
            rows = cur.fetchall()

    tj, tl = int(total[0]), int(total[1])

    text = (
        "🟢 TODAY USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 Date: {d}\n\n"
    )

    if rows:
        for row in rows:
            text += format_link_block(
                row[0], row[1], row[2], int(row[3]), int(row[4])
            )
    else:
        text += "ℹ️ Aaj kisi registered agent link se record nahi mila.\n\n"

    text += (
        f"📊 TOTAL\n"
        f"🟢 New Users: {tj}\n"
        f"🔴 Left Users: {tl}\n"
        f"👥 Net Users: {tj - tl}"
    )

    await update.message.reply_text(text)


async def yesterday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    d = today_date() - timedelta(days=1)

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT joins, leaves
                FROM daily_totals
                WHERE event_date = %s
            """, (d,))
            total = cur.fetchone() or (0, 0)

            cur.execute("""
                SELECT
                    l.admin_name,
                    l.link_name,
                    l.invite_link,
                    COALESCE(x.joins, 0),
                    COALESCE(x.leaves, 0)
                FROM invite_links l
                LEFT JOIN invite_link_daily x
                    ON x.invite_link = l.invite_link
                    AND x.event_date = %s
                WHERE COALESCE(x.joins, 0) > 0
                   OR COALESCE(x.leaves, 0) > 0
                ORDER BY COALESCE(x.joins, 0) DESC, l.admin_name
            """, (d,))
            rows = cur.fetchall()

    yj, yl = int(total[0]), int(total[1])

    text = (
        "🟡 YESTERDAY USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 Date: {d}\n\n"
    )

    if rows:
        for row in rows:
            text += format_link_block(
                row[0], row[1], row[2], int(row[3]), int(row[4])
            )
    else:
        text += "ℹ️ Kal kisi registered agent link se record nahi mila.\n\n"

    text += (
        f"📊 TOTAL\n"
        f"🟢 New Users: {yj}\n"
        f"🔴 Left Users: {yl}\n"
        f"👥 Net Users: {yj - yl}"
    )

    await update.message.reply_text(text)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    now = today_date()
    yesterday_d = now - timedelta(days=1)
    week_start = now - timedelta(days=now.weekday())
    month_start = now.replace(day=1)

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN event_date = %s THEN joins ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN event_date = %s THEN leaves ELSE 0 END), 0),

                    COALESCE(SUM(CASE WHEN event_date = %s THEN joins ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN event_date = %s THEN leaves ELSE 0 END), 0),

                    COALESCE(SUM(CASE
                        WHEN event_date BETWEEN %s AND %s THEN joins ELSE 0 END), 0),
                    COALESCE(SUM(CASE
                        WHEN event_date BETWEEN %s AND %s THEN leaves ELSE 0 END), 0),

                    COALESCE(SUM(CASE
                        WHEN event_date BETWEEN %s AND %s THEN joins ELSE 0 END), 0),
                    COALESCE(SUM(CASE
                        WHEN event_date BETWEEN %s AND %s THEN leaves ELSE 0 END), 0),

                    COALESCE(SUM(joins), 0),
                    COALESCE(SUM(leaves), 0)
                FROM daily_totals
            """, (
                now, now,
                yesterday_d, yesterday_d,
                week_start, now,
                week_start, now,
                month_start, now,
                month_start, now,
            ))
            r = cur.fetchone()

    vals = {
        "today": (int(r[0]), int(r[1])),
        "yesterday": (int(r[2]), int(r[3])),
        "week": (int(r[4]), int(r[5])),
        "month": (int(r[6]), int(r[7])),
        "total": (int(r[8]), int(r[9])),
    }

    def row(title, values):
        return (
            f"📅 {title}\n"
            f"🟢 Joined: {values[0]}\n"
            f"🔴 Left: {values[1]}\n"
            f"👥 Net: {values[0] - values[1]}\n\n"
        )

    await update.message.reply_text(
        "📊 GROUP USER STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        + row("TODAY", vals["today"])
        + row("YESTERDAY", vals["yesterday"])
        + row("THIS WEEK", vals["week"])
        + row("THIS MONTH", vals["month"])
        + row("TOTAL", vals["total"])
        + f"🎯 Target Group: {TARGET_CHAT_ID}"
    )


async def addlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Existing link aur agent name dein.\n\n"
            "/addlink Sachin https://t.me/+XXXX"
        )
        return

    name = context.args[0].strip()
    url = " ".join(context.args[1:]).strip()

    if not url.startswith(("https://t.me/", "http://t.me/")):
        await update.message.reply_text(
            "❌ Sahi Telegram invite link dein."
        )
        return

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT joins, leaves
                FROM invite_links
                WHERE invite_link = %s
            """, (url,))
            old = cur.fetchone()

            if old:
                cur.execute("""
                    UPDATE invite_links
                    SET admin_name = %s,
                        link_name = %s
                    WHERE invite_link = %s
                """, (name, name, url))

                await update.message.reply_text(
                    f"✅ Link updated.\n"
                    f"👤 Agent: {name}\n"
                    f"🔗 {url}\n"
                    f"📊 Purane counts safe hain.\n"
                    f"🟢 Joined: {old[0]}\n"
                    f"🔴 Left: {old[1]}"
                )
                return

            cur.execute("""
                INSERT INTO invite_links(
                    invite_link, admin_name, link_name, joins, leaves
                )
                VALUES (%s, %s, %s, 0, 0)
            """, (url, name, name))

    await update.message.reply_text(
        f"✅ EXISTING LINK ADDED\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Agent: {name}\n"
        f"🔗 {url}\n"
        f"🟢 Joined: 0\n"
        f"🔴 Left: 0\n"
        f"👥 Net: 0\n\n"
        f"⚠️ Is link se aane wale NEW users {name} ke naam par count honge."
    )


async def links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT admin_name, link_name, invite_link, joins, leaves
                FROM invite_links
                ORDER BY admin_name
            """)
            rows = cur.fetchall()

    if not rows:
        await update.message.reply_text(
            "ℹ️ Abhi koi existing agent link register nahi hai."
        )
        return

    text = "📊 AGENT-WISE USER STATISTICS\n━━━━━━━━━━━━━━━━━━━━\n\n"

    for row in rows:
        text += format_link_block(
            row[0], row[1], row[2], int(row[3]), int(row[4])
        )

    await update.message.reply_text(text)


async def mylink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT admin_name, link_name, invite_link, joins, leaves
                FROM invite_links
                ORDER BY admin_name
            """)
            rows = cur.fetchall()

    if not rows:
        await update.message.reply_text(
            "ℹ️ Abhi koi existing agent link register nahi hai."
        )
        return

    text = "🔗 REGISTERED AGENT LINKS\n━━━━━━━━━━━━━━━━━━━━\n\n"

    for row in rows:
        text += format_link_block(
            row[0], row[1], row[2], int(row[3]), int(row[4])
        )

    await update.message.reply_text(text)


# ============================================================
# TARGET GROUP JOIN / LEAVE TRACKING
# ============================================================

async def member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member

    if not cm or cm.chat.id != TARGET_CHAT_ID:
        return

    old = cm.old_chat_member.status
    new = cm.new_chat_member.status
    user = cm.new_chat_member.user

    uid = str(user.id)

    joined_states = ("member", "administrator", "creator")
    left_states = ("left", "kicked")

    is_join = new in joined_states and old in left_states
    is_leave = new in left_states and old in joined_states

    if not (is_join or is_leave):
        return

    event_date = today_date()

    if is_join:
        invite_url = None

        # Telegram gives the invite link responsible for the join
        # when the update contains invite attribution.
        if cm.invite_link:
            invite_url = cm.invite_link.invite_link

        add_daily_total(event_date, joins=1)

        if invite_url:
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT admin_name
                        FROM invite_links
                        WHERE invite_link = %s
                    """, (invite_url,))
                    link_row = cur.fetchone()

            if link_row:
                add_link_event(
                    invite_url,
                    event_date,
                    joins=1,
                )

                save_user_attribution(
                    uid,
                    invite_url,
                    user.full_name,
                    f"@{user.username}" if user.username else "",
                )

                print(
                    f"JOIN {user.full_name} -> {link_row[0]}",
                    flush=True,
                )
            else:
                print(
                    f"JOIN unknown/unregistered link: {invite_url}",
                    flush=True,
                )
        else:
            print(
                f"JOIN without invite attribution: {user.full_name}",
                flush=True,
            )

    elif is_leave:
        add_daily_total(event_date, leaves=1)

        old_url = get_user_attribution(uid)

        if old_url:
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT admin_name
                        FROM invite_links
                        WHERE invite_link = %s
                    """, (old_url,))
                    link_row = cur.fetchone()

            if link_row:
                add_link_event(
                    old_url,
                    event_date,
                    leaves=1,
                )

                print(
                    f"LEAVE {user.full_name} -> {link_row[0]}",
                    flush=True,
                )
            else:
                print(
                    f"LEAVE: saved link is no longer registered: {old_url}",
                    flush=True,
                )
        else:
            print(
                f"LEAVE without saved attribution: {user.full_name}",
                flush=True,
            )


# ============================================================
# STARTUP
# ============================================================

async def error_handler(update, context):
    print(f"BOT ERROR: {context.error}", flush=True)


async def post_init(application):
    # DB first. This is safe to call on every restart.
    init_db()
    migrate_old_json()

    me = await application.bot.get_me()

    print("========================================", flush=True)
    print("WINTASK BOT STARTED", flush=True)
    print(f"Bot: @{me.username}", flush=True)
    print(f"Target Group: {TARGET_CHAT_ID}", flush=True)
    print(f"Command Group: {COMMAND_CHAT_ID}", flush=True)
    print("PostgreSQL: ON", flush=True)
    print("Existing-link mode: ON", flush=True)
    print("New-link creation: OFF", flush=True)
    print("========================================", flush=True)


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", chat_id))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("yesterday", yesterday))
    app.add_handler(CommandHandler("addlink", addlink))
    app.add_handler(CommandHandler("links", links))
    app.add_handler(CommandHandler("mylink", mylink))

    app.add_handler(
        ChatMemberHandler(
            member_update,
            ChatMemberHandler.CHAT_MEMBER,
        )
    )

    app.add_error_handler(error_handler)

    print("Bot polling started...", flush=True)

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
