import os
import json
import asyncio
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

import psycopg
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ChatMemberHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

TARGET_CHAT_ID = -1004318016710
COMMAND_CHAT_ID = -1003353359019
# Combined bot uses the first bot's existing target and command groups.
TARGET_GROUP_ID = TARGET_CHAT_ID
COMMAND_GROUP_ID = COMMAND_CHAT_ID
IST = ZoneInfo("Asia/Kolkata")
DATA_FILE = "bot_data.json"
BOT2_DATA_FILE = "bot2_data.json"

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
                ALTER TABLE invite_links
                ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE
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

            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot2_state (
                    id INTEGER PRIMARY KEY,
                    data JSONB NOT NULL,
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
                WHERE l.is_active = TRUE
                  AND (COALESCE(d.joins, 0) > 0
                   OR COALESCE(d.leaves, 0) > 0)
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
                WHERE l.is_active = TRUE
                  AND (COALESCE(x.joins, 0) > 0
                   OR COALESCE(x.leaves, 0) > 0)
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
                        link_name = %s,
                        is_active = TRUE
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


async def newlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    name = " ".join(context.args).strip()
    if not name:
        await update.message.reply_text(
            "❌ Agent ka naam dein.\n\n"
            "Example: /newlink Sachin"
        )
        return

    name = name[:32]
    try:
        created = await context.bot.create_chat_invite_link(
            chat_id=TARGET_CHAT_ID,
            name=name,
            creates_join_request=False,
        )
        url = created.invite_link

        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO invite_links(
                        invite_link, admin_name, link_name, joins, leaves, is_active
                    )
                    VALUES (%s, %s, %s, 0, 0, TRUE)
                    ON CONFLICT(invite_link) DO UPDATE SET
                        admin_name = EXCLUDED.admin_name,
                        link_name = EXCLUDED.link_name,
                        is_active = TRUE
                """, (url, name, name))

        await update.message.reply_text(
            "✅ NAYA INVITE LINK BAN GAYA\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Agent: {name}\n"
            f"🔗 Link: {url}\n"
            "🟢 Joined: 0\n"
            "🔴 Left: 0\n\n"
            "Is link se aane wale joins track honge."
        )
    except Exception as e:
        print(f"NEWLINK ERROR: {e}", flush=True)
        await update.message.reply_text(
            "❌ Naya invite link nahi ban saka.\n"
            "Check karein: bot target group ka admin ho aur uske paas "
            "Invite Users/Add Members permission ho.\n"
            f"Error: {e}"
        )


async def deletelink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    target = " ".join(context.args).strip()
    if not target:
        await update.message.reply_text(
            "❌ Agent ka naam ya exact invite URL dein.\n\n"
            "Example: /deletelink Sachin"
        )
        return

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT invite_link, admin_name, link_name
                FROM invite_links
                WHERE is_active = TRUE
                  AND (LOWER(admin_name) = LOWER(%s)
                       OR LOWER(link_name) = LOWER(%s)
                       OR invite_link = %s)
                ORDER BY admin_name
            """, (target, target, target))
            matches = cur.fetchall()

            if len(matches) > 1:
                await update.message.reply_text(
                    "⚠️ Is naam ke multiple active links hain.\n"
                    "Galat link hatne se bachane ke liye exact invite URL dein:\n"
                    + "\n".join(row[0] for row in matches)
                )
                return

            if not matches:
                await update.message.reply_text(
                    "ℹ️ Is naam/link ka koi active tracking record nahi mila."
                )
                return

            url, admin_name, link_name = matches[0]
            cur.execute("""
                UPDATE invite_links
                SET is_active = FALSE
                WHERE invite_link = %s
            """, (url,))

    await update.message.reply_text(
        "✅ Tracking/list se link hata diya gaya.\n"
        f"👤 Agent: {admin_name}\n"
        f"🔗 {url}\n\n"
        "ℹ️ Telegram invite link revoke nahi kiya gaya; woh active rahega. "
        "Purane counts/history PostgreSQL mein safe hain."
    )


async def links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT admin_name, link_name, invite_link, joins, leaves
                FROM invite_links
                WHERE is_active = TRUE
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
                WHERE is_active = TRUE
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
# AUTOMATION / PRIVATE MENU SETTINGS (stored separately in PostgreSQL)
# ============================================================
DEFAULT_WELCOME = (
    "👋 Welcome {mention}!\n\n"
    "🎉 Welcome to the group.\n"
    "Please read the group rules and enjoy!"
)
DEFAULT_DATA = {
    "welcome_enabled": True,
    "welcome_text": DEFAULT_WELCOME,
    "on_time": "",
    "off_time": "",
    "morning_time": "",
    "morning_text": "🌞 Good Morning everyone!",
    "morning_last_sent": "",
    "night_time": "",
    "night_text": "🌙 Good Night everyone!",
    "night_last_sent": "",
    "notices": [],
    "keywords": {},
    "personal_options": {
        "Rules": "📋 Group Rules:\nPlease follow the group rules.",
        "Help": "❓ Help ke liye admin se contact karein.",
        "Group Link": "🔗 Group link admin se le sakte hain.",
        "Contact Admin": "📞 Please contact a group admin.",
    },
}
DATA = None

async def admin_only(update, context):
    return await check_access(update, context)

async def check_access(update, context):
    if not update.message or not update.effective_chat:
        return False
    # Private chat is reserved for the fixed menu; no stats/admin error replies there.
    if update.effective_chat.type == "private":
        return False
    if not command_group(update):
        # Keep ordinary target-group chat quiet; command replies are only in command group.
        return False
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Ye command sirf admin use kar sakta hai.")
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return
    if update.effective_chat.type == "private":
        await personal_start(update, context)
        return
    if not command_group(update):
        return
    if not await check_access(update, context):
        return
    await update.message.reply_text(
        "✅ Wintask Assistant is working!\n\n"
        "📊 STATS & INVITE LINKS\n"
        "/id  /stats  /today  /yesterday\n"
        "/addlink NAME LINK\n/newlink NAME\n/deletelink NAME_OR_LINK\n/links  /mylink\n\n"
        "🤖 AUTOMATION\n"
        "/welcome on|off\n/setwelcome MESSAGE\n"
        "/seton HH:MM\n/setoff HH:MM\n"
        "/setmorning HH:MM MESSAGE\n/setnight HH:MM MESSAGE\n"
        "/notice HH:MM MESSAGE\n/notices\n/delnotice NUMBER\n"
        "/addkeyword WORD REPLY\n/keywords\n/deletekeyword WORD\n"
        "/addoption NAME MESSAGE\n/options\n/deleteoption NAME\n"
        "/settings\n\n"
        "⏰ Sabhi times IST (India) ke hisaab se hain."
    )

async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.effective_chat and update.effective_chat.type != "private":
        c = update.effective_chat
        await update.message.reply_text(
            f"🆔 Chat ID: {c.id}\n"
            f"💬 Type: {c.type}\n"
            f"📌 Name: {c.title or 'Private Chat'}"
        )

def copy_default_data():
    return json.loads(json.dumps(DEFAULT_DATA, ensure_ascii=False))

def load_old_json():
    if not os.path.exists(BOT2_DATA_FILE):
        return None

    try:
        with open(BOT2_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return None

        base = copy_default_data()

        for key in base:
            if key in data:
                base[key] = data[key]

        if not isinstance(base.get("notices"), list):
            base["notices"] = []

        if not isinstance(base.get("keywords"), dict):
            base["keywords"] = {}

        if not isinstance(base.get("personal_options"), dict):
            base["personal_options"] = {}

        return base

    except Exception as e:
        print(f"Old JSON read error: {e}", flush=True)
        return None

def load_data_from_db():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT data FROM bot2_state WHERE id = 1"
            )
            row = cur.fetchone()

            if row:
                data = row[0]

                if not isinstance(data, dict):
                    return copy_default_data()

                base = copy_default_data()
                base.update(data)

                if not isinstance(base.get("notices"), list):
                    base["notices"] = []

                if not isinstance(base.get("keywords"), dict):
                    base["keywords"] = {}

                if not isinstance(base.get("personal_options"), dict):
                    base["personal_options"] = {}

                return base

    return None

def save_data(data):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bot2_state(id, data, updated_at)
                VALUES (1, %s::jsonb, NOW())
                ON CONFLICT(id)
                DO UPDATE SET
                    data = EXCLUDED.data,
                    updated_at = NOW()
            """, (json.dumps(data, ensure_ascii=False),))

def load_or_migrate_data():
    existing = load_data_from_db()

    if existing is not None:
        print("✅ PostgreSQL data loaded.", flush=True)
        return existing

    old = load_old_json()

    if old is not None:
        save_data(old)
        print(
            "✅ Old bot2_data.json migrated to PostgreSQL.",
            flush=True,
        )
        return old

    fresh = copy_default_data()
    save_data(fresh)

    print(
        "ℹ️ No old bot2_data.json found. New PostgreSQL data created.",
        flush=True,
    )

    return fresh

def now_ist():
    return datetime.now(IST)

def parse_hhmm(value):
    try:
        h, m = value.strip().split(":")
        h = int(h)
        m = int(m)

        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None

        return f"{h:02d}:{m:02d}"

    except Exception:
        return None

def mention_html(user):
    name = user.full_name or user.first_name or "New Member"

    name = (
        name.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

    return f'<a href="tg://user?id={user.id}">{name}</a>'

async def set_group_chat_on(bot):
    permissions = ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_add_web_page_previews=True,
        can_change_info=False,
        can_invite_users=True,
        can_pin_messages=False,
        can_manage_topics=True,
    )

    await bot.set_chat_permissions(
        TARGET_GROUP_ID,
        permissions,
        use_independent_chat_permissions=True,
    )

async def set_group_chat_off(bot):
    permissions = ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )

    await bot.set_chat_permissions(
        TARGET_GROUP_ID,
        permissions,
        use_independent_chat_permissions=True,
    )

def personal_keyboard():
    buttons = []

    for name in DATA.get("personal_options", {}):
        buttons.append([
            InlineKeyboardButton(
                f"📌 {name}",
                callback_data=f"popt:{name}",
            )
        ])

    return InlineKeyboardMarkup(buttons)

async def personal_start(update, context):
    await update.message.reply_text(
        "👋 Welcome to Wintask Bot!\n\n"
        "👇 Neeche se option choose karein:",
        reply_markup=personal_keyboard(),
    )

async def personal_button(update, context):
    query = update.callback_query

    await query.answer()

    if not query.data.startswith("popt:"):
        return

    name = query.data.split(":", 1)[1]

    reply = DATA.get("personal_options", {}).get(name)

    if reply is None:
        await query.message.reply_text(
            "⚠️ Ye option ab available nahi hai."
        )
        return

    await query.message.reply_text(reply)

async def add_keyword(update, context):
    if not await admin_only(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Use:\n"
            "/addkeyword payment Payment ke liye admin se contact karein."
        )
        return

    word = context.args[0].lower().strip()
    reply = " ".join(context.args[1:]).strip()

    DATA.setdefault("keywords", {})[word] = reply
    save_data(DATA)

    await update.message.reply_text(
        f"✅ Keyword added.\n\n"
        f"🔑 {word}\n"
        f"💬 {reply}"
    )

async def list_keywords(update, context):
    if not await admin_only(update, context):
        return

    items = DATA.get("keywords", {})

    if not items:
        await update.message.reply_text(
            "📭 Koi keyword set nahi hai."
        )
        return

    text = (
        "🔑 Auto Reply Keywords:\n\n"
        + "\n\n".join(
            f"• {k} → {v}"
            for k, v in items.items()
        )
    )

    await update.message.reply_text(text)

async def delete_keyword(update, context):
    if not await admin_only(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Use:\n/deletekeyword payment"
        )
        return

    word = context.args[0].lower().strip()

    if word not in DATA.get("keywords", {}):
        await update.message.reply_text(
            "❌ Ye keyword nahi mila."
        )
        return

    del DATA["keywords"][word]
    save_data(DATA)

    await update.message.reply_text(
        f"🗑 Keyword deleted: {word}"
    )

async def add_option(update, context):
    if not await admin_only(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Use:\n"
            "/addoption Rules Group ke rules yahan likhein."
        )
        return

    name = context.args[0].strip()
    reply = " ".join(context.args[1:]).strip()

    DATA.setdefault("personal_options", {})[name] = reply
    save_data(DATA)

    await update.message.reply_text(
        f"✅ Personal option added: {name}"
    )

async def list_options(update, context):
    if not await admin_only(update, context):
        return

    items = DATA.get("personal_options", {})

    if not items:
        await update.message.reply_text(
            "📭 Koi personal option nahi hai."
        )
        return

    await update.message.reply_text(
        "📌 Personal options:\n\n"
        + "\n".join(f"• {x}" for x in items)
    )

async def delete_option(update, context):
    if not await admin_only(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Use:\n/deleteoption Rules"
        )
        return

    name = context.args[0].strip()

    if name not in DATA.get("personal_options", {}):
        await update.message.reply_text(
            "❌ Ye option nahi mila."
        )
        return

    del DATA["personal_options"][name]
    save_data(DATA)

    await update.message.reply_text(
        f"🗑 Personal option deleted: {name}"
    )

async def group_keyword_reply(update, context):
    if (
        update.effective_chat is None
        or update.effective_chat.id != TARGET_GROUP_ID
    ):
        return

    if (
        not update.message
        or not update.message.text
        or update.message.text.startswith("/")
    ):
        return

    text = update.message.text.lower()

    for word, reply in DATA.get("keywords", {}).items():
        if word.lower() in text:
            try:
                await update.message.reply_text(reply)
            except Exception as e:
                print(
                    f"Keyword reply error: {e}",
                    flush=True,
                )
            break

async def welcome_command(update, context):
    if not await admin_only(update, context):
        return

    if (
        not context.args
        or context.args[0].lower() not in ("on", "off")
    ):
        await update.message.reply_text(
            "Use:\n/welcome on\n/welcome off"
        )
        return

    DATA["welcome_enabled"] = (
        context.args[0].lower() == "on"
    )

    save_data(DATA)

    await update.message.reply_text(
        "👋 Welcome message: "
        + (
            "ON 🟢"
            if DATA["welcome_enabled"]
            else "OFF 🔴"
        )
    )

async def set_welcome(update, context):
    if not await admin_only(update, context):
        return

    text = update.message.text.partition(" ")[2].strip()

    if not text:
        await update.message.reply_text(
            "Use:\n/setwelcome Welcome {mention}! 🎉"
        )
        return

    DATA["welcome_text"] = text
    save_data(DATA)

    await update.message.reply_text(
        "✅ Welcome message saved.\n"
        "Use {mention} where the member mention should appear."
    )

async def new_member(update, context):
    if (
        not update.chat_member
        or update.effective_chat is None
        or update.effective_chat.id != TARGET_GROUP_ID
    ):
        return

    old_status = update.chat_member.old_chat_member.status
    new_status = update.chat_member.new_chat_member.status

    if not (
        new_status in ("member", "restricted")
        and old_status in ("left", "kicked")
    ):
        return

    if not DATA.get("welcome_enabled", True):
        return

    user = update.chat_member.new_chat_member.user

    text = DATA.get(
        "welcome_text",
        DEFAULT_WELCOME,
    ).replace(
        "{mention}",
        mention_html(user),
    )

    try:
        await context.bot.send_message(
            TARGET_GROUP_ID,
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        print(
            f"Welcome error: {e}",
            flush=True,
        )

async def set_on(update, context):
    if not await admin_only(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Use:\n/seton 09:00"
        )
        return

    value = parse_hhmm(context.args[0])

    if value is None:
        await update.message.reply_text(
            "❌ Time galat hai. Example: /seton 09:00"
        )
        return

    DATA["on_time"] = value
    save_data(DATA)

    await update.message.reply_text(
        f"🟢 Group ON time set: {value} IST"
    )

async def set_off(update, context):
    if not await admin_only(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Use:\n/setoff 22:00"
        )
        return

    value = parse_hhmm(context.args[0])

    if value is None:
        await update.message.reply_text(
            "❌ Time galat hai. Example: /setoff 22:00"
        )
        return

    DATA["off_time"] = value
    save_data(DATA)

    await update.message.reply_text(
        f"🔴 Group OFF time set: {value} IST"
    )

async def notice(update, context):
    if not await admin_only(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Use:\n/notice 12:30 Important meeting at 1 PM"
        )
        return

    value = parse_hhmm(context.args[0])

    if value is None:
        await update.message.reply_text(
            "❌ Time galat hai. Example: /notice 12:30 Message"
        )
        return

    message = " ".join(context.args[1:]).strip()

    DATA.setdefault("notices", []).append({
        "time": value,
        "message": message,
        "last_sent": "",
    })

    save_data(DATA)

    await update.message.reply_text(
        f"✅ Notice #{len(DATA['notices'])} saved.\n"
        f"⏰ {value} IST\n"
        f"📢 {message}"
    )

async def notices(update, context):
    if not await admin_only(update, context):
        return

    items = DATA.get("notices", [])

    if not items:
        await update.message.reply_text(
            "📢 Abhi koi scheduled notice nahi hai."
        )
        return

    lines = ["📢 Scheduled Notices:\n"]

    for i, item in enumerate(items, 1):
        lines.append(
            f"{i}. ⏰ {item['time']} IST\n"
            f"   📢 {item['message']}"
        )

    await update.message.reply_text(
        "\n".join(lines)
    )

async def delete_notice(update, context):
    if not await admin_only(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Use:\n/delnotice 1"
        )
        return

    try:
        number = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ Notice number galat hai."
        )
        return

    items = DATA.get("notices", [])

    if not 1 <= number <= len(items):
        await update.message.reply_text(
            "❌ Aisa notice number nahi hai."
        )
        return

    removed = items.pop(number - 1)

    save_data(DATA)

    await update.message.reply_text(
        f"🗑 Notice deleted.\n"
        f"⏰ {removed['time']} IST\n"
        f"📢 {removed['message']}"
    )

async def settings(update, context):
    if not await admin_only(update, context):
        return

    await update.message.reply_text(
        "⚙️ BOT SETTINGS\n\n"
        f"👋 Welcome: "
        f"{'ON 🟢' if DATA.get('welcome_enabled') else 'OFF 🔴'}\n"
        f"🟢 Group ON: "
        f"{DATA.get('on_time') or 'Not set'} IST\n"
        f"🔴 Group OFF: "
        f"{DATA.get('off_time') or 'Not set'} IST\n"
        f"🌞 Good Morning: {DATA.get('morning_time') or 'Not set'} IST\n"
        f"🌙 Good Night: {DATA.get('night_time') or 'Not set'} IST\n"
        f"📢 Scheduled notices: "
        f"{len(DATA.get('notices', []))}\n"
        f"🔑 Keywords: "
        f"{len(DATA.get('keywords', {}))}\n"
        f"📌 Personal options: "
        f"{len(DATA.get('personal_options', {}))}\n"
        f"💾 Storage: PostgreSQL ✅\n\n"
        f"🎯 Target Group ID: {TARGET_GROUP_ID}\n"
        f"💬 Command Group ID: {COMMAND_GROUP_ID}"
    )

async def scheduler(application):
    print("⏰ Scheduler started.", flush=True)

    last_minute = ""

    while True:
        try:
            current = now_ist()
            hhmm = current.strftime("%H:%M")
            today = current.strftime("%Y-%m-%d")

            minute_key = f"{today} {hhmm}"

            if minute_key != last_minute:
                last_minute = minute_key

                if DATA.get("on_time") == hhmm:
                    try:
                        await set_group_chat_on(
                            application.bot
                        )
                        print(
                            f"🟢 Group ON at {hhmm} IST",
                            flush=True,
                        )
                    except Exception as e:
                        print(
                            f"Group ON error: {e}",
                            flush=True,
                        )

                if DATA.get("off_time") == hhmm:
                    try:
                        await set_group_chat_off(
                            application.bot
                        )
                        print(
                            f"🔴 Group OFF at {hhmm} IST",
                            flush=True,
                        )
                    except Exception as e:
                        print(
                            f"Group OFF error: {e}",
                            flush=True,
                        )

                changed = False

                if DATA.get("morning_time") == hhmm and DATA.get("morning_last_sent") != today:
                    try:
                        await application.bot.send_message(TARGET_GROUP_ID, DATA.get("morning_text") or "🌞 Good Morning!")
                        DATA["morning_last_sent"] = today
                        changed = True
                    except Exception as e:
                        print(f"Good Morning send error: {e}", flush=True)

                if DATA.get("night_time") == hhmm and DATA.get("night_last_sent") != today:
                    try:
                        await application.bot.send_message(TARGET_GROUP_ID, DATA.get("night_text") or "🌙 Good Night!")
                        DATA["night_last_sent"] = today
                        changed = True
                    except Exception as e:
                        print(f"Good Night send error: {e}", flush=True)

                for item in DATA.get("notices", []):
                    if (
                        item.get("time") == hhmm
                        and item.get("last_sent") != today
                    ):
                        try:
                            await application.bot.send_message(
                                TARGET_GROUP_ID,
                                f"📢 {item['message']}",
                            )

                            item["last_sent"] = today
                            changed = True

                            print(
                                f"📢 Notice sent at {hhmm}: "
                                f"{item['message']}",
                                flush=True,
                            )

                        except Exception as e:
                            print(
                                f"Notice error: {e}",
                                flush=True,
                            )

                if changed:
                    save_data(DATA)

            await asyncio.sleep(10)

        except asyncio.CancelledError:
            raise

        except Exception as e:
            print(
                f"Scheduler error: {e}",
                flush=True,
            )
            await asyncio.sleep(10)

async def set_morning(update, context):
    if not await admin_only(update, context):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Use: /setmorning 07:00 Good Morning everyone!")
        return
    value = parse_hhmm(context.args[0])
    message = " ".join(context.args[1:]).strip()
    if value is None or not message:
        await update.message.reply_text("❌ Time HH:MM format mein dein. Example: /setmorning 07:00 Good Morning!")
        return
    DATA["morning_time"] = value
    DATA["morning_text"] = message
    DATA["morning_last_sent"] = ""
    save_data(DATA)
    await update.message.reply_text(f"✅ Good Morning message set: {value} IST\n{message}")

async def set_night(update, context):
    if not await admin_only(update, context):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Use: /setnight 22:00 Good Night everyone!")
        return
    value = parse_hhmm(context.args[0])
    message = " ".join(context.args[1:]).strip()
    if value is None or not message:
        await update.message.reply_text("❌ Time HH:MM format mein dein. Example: /setnight 22:00 Good Night!")
        return
    DATA["night_time"] = value
    DATA["night_text"] = message
    DATA["night_last_sent"] = ""
    save_data(DATA)
    await update.message.reply_text(f"✅ Good Night message set: {value} IST\n{message}")



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
                          AND is_active = TRUE
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
                          AND is_active = TRUE
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

# ============================================================
# COMBINED STARTUP / MAIN
# ============================================================
async def post_init(application):
    global DATA
    init_db()
    migrate_old_json()
    DATA = load_or_migrate_data()
    try:
        await application.bot.delete_webhook(drop_pending_updates=False)
    except Exception as e:
        print(f"Webhook clear warning: {e}", flush=True)
    me = await application.bot.get_me()
    application.create_task(scheduler(application))
    print("========================================", flush=True)
    print(f"WINTASK COMBINED BOT STARTED: @{me.username}", flush=True)
    print(f"Target Group: {TARGET_CHAT_ID}", flush=True)
    print(f"Command Group: {COMMAND_CHAT_ID}", flush=True)
    print("PostgreSQL: ON; invite tracking data preserved", flush=True)
    print("Welcome / schedule / keywords / private menu: ON", flush=True)
    print("Timezone: Asia/Kolkata", flush=True)
    print("========================================", flush=True)

async def error_handler(update, context):
    print(f"BOT ERROR: {context.error}", flush=True)

def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    # Stats and invite tracking commands (command group admins only).
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", chat_id))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("yesterday", yesterday))
    app.add_handler(CommandHandler("addlink", addlink))
    app.add_handler(CommandHandler("newlink", newlink))
    app.add_handler(CommandHandler("deletelink", deletelink))
    app.add_handler(CommandHandler("links", links))
    app.add_handler(CommandHandler("mylink", mylink))

    # Group automation and scheduled messages.
    app.add_handler(CommandHandler("welcome", welcome_command))
    app.add_handler(CommandHandler("setwelcome", set_welcome))
    app.add_handler(CommandHandler("seton", set_on))
    app.add_handler(CommandHandler("setoff", set_off))
    app.add_handler(CommandHandler("setmorning", set_morning))
    app.add_handler(CommandHandler("setnight", set_night))
    app.add_handler(CommandHandler("notice", notice))
    app.add_handler(CommandHandler("notices", notices))
    app.add_handler(CommandHandler("delnotice", delete_notice))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CommandHandler("addkeyword", add_keyword))
    app.add_handler(CommandHandler("keywords", list_keywords))
    app.add_handler(CommandHandler("deletekeyword", delete_keyword))
    app.add_handler(CommandHandler("addoption", add_option))
    app.add_handler(CommandHandler("options", list_options))
    app.add_handler(CommandHandler("deleteoption", delete_option))

    app.add_handler(CallbackQueryHandler(personal_button))
    # Different handler groups ensure both join-welcome and invite attribution run.
    app.add_handler(ChatMemberHandler(member_update, ChatMemberHandler.CHAT_MEMBER), group=0)
    app.add_handler(ChatMemberHandler(new_member, ChatMemberHandler.CHAT_MEMBER), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, group_keyword_reply))
    app.add_error_handler(error_handler)
    print("Bot polling started...", flush=True)
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)

if __name__ == "__main__":
    main()
