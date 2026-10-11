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
    ChatJoinRequestHandler,
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

            # Track whether a member's latest join happened today. This is additive
            # and does not modify or delete existing stats/invite data.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS member_current_join (
                    user_id TEXT PRIMARY KEY,
                    joined_date DATE NOT NULL,
                    is_member BOOLEAN NOT NULL DEFAULT TRUE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_join_cohort (
                    event_date DATE PRIMARY KEY,
                    joins BIGINT NOT NULL DEFAULT 0,
                    same_day_leaves BIGINT NOT NULL DEFAULT 0
                )
            """)

            # Group-specific statistics. Existing aggregate tables remain untouched.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS group_daily_totals (
                    group_id BIGINT NOT NULL,
                    event_date DATE NOT NULL,
                    joins BIGINT NOT NULL DEFAULT 0,
                    leaves BIGINT NOT NULL DEFAULT 0,
                    PRIMARY KEY (group_id, event_date)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS group_daily_join_cohort (
                    group_id BIGINT NOT NULL,
                    event_date DATE NOT NULL,
                    joins BIGINT NOT NULL DEFAULT 0,
                    same_day_leaves BIGINT NOT NULL DEFAULT 0,
                    PRIMARY KEY (group_id, event_date)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS group_member_current_join (
                    group_id BIGINT NOT NULL,
                    user_id TEXT NOT NULL,
                    joined_date DATE NOT NULL,
                    is_member BOOLEAN NOT NULL DEFAULT TRUE,
                    PRIMARY KEY (group_id, user_id)
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


def get_target_ids():
    """Return configured target group IDs, preserving the original group as fallback."""
    configured = DATA.get("target_groups", []) if isinstance(DATA, dict) else []
    result = []
    for item in configured:
        try:
            group_id = int(item)
            if group_id not in result:
                result.append(group_id)
        except (TypeError, ValueError):
            continue
    if not result:
        result = [TARGET_CHAT_ID]
    return result


def is_target_group(chat_id):
    try:
        return int(chat_id) in get_target_ids()
    except (TypeError, ValueError):
        return False


def selected_target_id():
    targets = get_target_ids()
    try:
        selected = int(DATA.get("selected_target_group", targets[0]))
    except (TypeError, ValueError):
        selected = targets[0]
    return selected if selected in targets else targets[0]


def command_group(update):
    try:
        configured_id = int(DATA.get("command_group_id", COMMAND_CHAT_ID))
    except (TypeError, ValueError):
        configured_id = COMMAND_CHAT_ID
    return bool(update.effective_chat and update.effective_chat.id == configured_id)


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
    gid = selected_target_id()
    d = today_date()
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT joins, leaves FROM group_daily_totals WHERE group_id=%s AND event_date=%s", (gid, d))
            total = cur.fetchone() or (0, 0)
            cur.execute("SELECT joins, same_day_leaves FROM group_daily_join_cohort WHERE group_id=%s AND event_date=%s", (gid, d))
            cohort = cur.fetchone() or (0, 0)
    joined, all_left = int(total[0]), int(total[1])
    today_joined, today_joiners_left = int(cohort[0]), int(cohort[1])
    try:
        chat = await context.bot.get_chat(gid)
        group_name = chat.title or str(gid)
    except Exception:
        group_name = str(gid)
    await update.message.reply_text(
        f"🟢 TODAY USER STATISTICS\n🎯 Group: {group_name}\n🆔 ID: {gid}\n📅 Date: {d}\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 Joined today: {today_joined}\n🔴 In today's joiners, left today: {today_joiners_left}\n"
        f"👥 In today's joiners, still in group: {max(0, today_joined - today_joiners_left)}\n"
        f"📊 All leaves today (any join date): {all_left}\n"
        "Use /lefttoday for all users who left today."
    )


async def lefttoday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    gid = selected_target_id()
    d = today_date()
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT leaves FROM group_daily_totals WHERE group_id=%s AND event_date=%s", (gid, d))
            row = cur.fetchone()
    total_leaves = int(row[0]) if row else 0
    try:
        chat = await context.bot.get_chat(gid)
        group_name = chat.title or str(gid)
    except Exception:
        group_name = str(gid)
    await update.message.reply_text(
        f"🔴 ALL USERS WHO LEFT TODAY\n🎯 Group: {group_name}\n🆔 ID: {gid}\n📅 Date: {d}\n"
        f"🔴 Total left today (any join date): {total_leaves}"
    )


async def yesterday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    gid = selected_target_id()
    d = today_date() - timedelta(days=1)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT joins, leaves FROM group_daily_totals WHERE group_id=%s AND event_date=%s", (gid, d))
            total = cur.fetchone() or (0, 0)
    try:
        chat = await context.bot.get_chat(gid)
        group_name = chat.title or str(gid)
    except Exception:
        group_name = str(gid)
    yj, yl = int(total[0]), int(total[1])
    await update.message.reply_text(
        f"🟡 YESTERDAY USER STATISTICS\n🎯 Group: {group_name}\n🆔 ID: {gid}\n📅 Date: {d}\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 New Users: {yj}\n🔴 Left Users: {yl}\n👥 Net Users: {yj - yl}"
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    gid = selected_target_id()
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
                    COALESCE(SUM(CASE WHEN event_date BETWEEN %s AND %s THEN joins ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN event_date BETWEEN %s AND %s THEN leaves ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN event_date BETWEEN %s AND %s THEN joins ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN event_date BETWEEN %s AND %s THEN leaves ELSE 0 END), 0),
                    COALESCE(SUM(joins), 0), COALESCE(SUM(leaves), 0)
                FROM group_daily_totals WHERE group_id = %s
            """, (now, now, yesterday_d, yesterday_d, week_start, now, week_start, now,
                  month_start, now, month_start, now, gid))
            r = cur.fetchone()
    vals = {
        "today": (int(r[0]), int(r[1])), "yesterday": (int(r[2]), int(r[3])),
        "week": (int(r[4]), int(r[5])), "month": (int(r[6]), int(r[7])),
        "total": (int(r[8]), int(r[9])),
    }
    try:
        chat = await context.bot.get_chat(gid)
        group_name = chat.title or str(gid)
    except Exception:
        group_name = str(gid)
    def row(title, values):
        return (f"📅 {title}\n🟢 Joined: {values[0]}\n🔴 Left: {values[1]}\n👥 Net: {values[0] - values[1]}\n\n")
    await update.message.reply_text(
        f"📊 GROUP USER STATISTICS\n🎯 Group: {group_name}\n🆔 ID: {gid}\n━━━━━━━━━━━━━━━━━━━━\n\n"
        + row("TODAY", vals["today"]) + row("YESTERDAY", vals["yesterday"])
        + row("THIS WEEK", vals["week"]) + row("THIS MONTH", vals["month"])
        + row("TOTAL (since group-wise tracking enabled)", vals["total"])
        + "To switch group use /selecttarget GROUP_ID."
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

    args = list(context.args)
    target_id = get_target_ids()[0]
    if args and args[-1].startswith("-100"):
        try:
            candidate_id = int(args[-1])
            if candidate_id not in get_target_ids():
                await update.message.reply_text("❌ Ye target ID configured nahi hai. Pehle /addtarget ID chalayein.")
                return
            target_id = candidate_id
            args = args[:-1]
        except ValueError:
            pass
    name = " ".join(args).strip()
    if not name:
        await update.message.reply_text(
            "❌ Agent ka naam dein.\n\n"
            "Example: /newlink Sachin\n"
            "Specific group ke liye: /newlink Sachin -1001234567890"
        )
        return

    name = name[:32]
    try:
        created = await context.bot.create_chat_invite_link(
            chat_id=target_id,
            name=name,
            creates_join_request=True,
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
            f"🎯 Target Group ID: {target_id}\n"
            f"🔗 Link: {url}\n"
            "📝 Join request link: admin approval / scheduled auto-accept\n"
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
    "target_groups": [TARGET_CHAT_ID],
    "selected_target_group": TARGET_CHAT_ID,
    "command_group_id": COMMAND_CHAT_ID,
    "welcome_enabled": True,
    "welcome_text": DEFAULT_WELCOME,
    "auto_accept_enabled": False,
    "auto_accept_start": "09:00",
    "auto_accept_end": "18:00",
    "on_time": "",
    "off_time": "",
    "morning_time": "",
    "morning_text": "🌞 Good Morning everyone!",
    "morning_photo": "",
    "morning_last_sent": "",
    "night_time": "",
    "night_text": "🌙 Good Night everyone!",
    "night_photo": "",
    "night_last_sent": "",
    "notices": [],
    "keywords": {},
    "personal_welcome_text": "👋 Welcome to Wintask Bot!\n\n👇 Neeche se option choose karein:",
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
        "/targets  /addtarget GROUP_ID  /removetarget GROUP_ID\n"
        "/selecttarget GROUP_ID  /setcommandgroup GROUP_ID\n"
        "/addlink NAME LINK\n/newlink NAME\n/deletelink NAME_OR_LINK\n/links  /mylink\n\n"
        "🤖 AUTOMATION\n"
        "/welcome on|off\n/setwelcome MESSAGE\n/getwelcome\n"
        "/setautojoin START END  (e.g. /setautojoin 09:00 18:00)\n"
        "/autojoin on|off\n"
        "/seton HH:MM\n/setoff HH:MM\n"
        "/setmorning HH:MM MESSAGE\n/setnight HH:MM MESSAGE\n"
        "/morningphoto /clearmorningphoto\n/nightphoto /clearnightphoto\n"
        "/notice HH:MM MESSAGE\n/notices\n/delnotice NUMBER\n"
        "/noticephoto NUMBER /clearnoticephoto NUMBER\n"
        "/addkeyword WORD REPLY\n/keywords\n/deletekeyword WORD\n"
        "/addoption NAME MESSAGE\n/editoption OLD_NAME NEW_NAME MESSAGE\n"
        "/setpersonalwelcome MESSAGE\n/getpersonalwelcome\n/options\n/deleteoption NAME\n"
        "/settings\n\n"
        "⏰ Sabhi times IST (India) ke hisaab se hain."
    )

async def add_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "Use: /addtarget -1001234567890\n"
            "Bot ko us group mein pehle add karke admin banayein."
        )
        return
    try:
        group_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Group ID number mein dein. Example: /addtarget -1001234567890")
        return
    try:
        chat = await context.bot.get_chat(group_id)
        bot_member = await context.bot.get_chat_member(group_id, (await context.bot.get_me()).id)
        if bot_member.status not in ("administrator", "creator"):
            await update.message.reply_text("❌ Bot is group ka admin nahi hai. Pehle bot ko admin banayein, phir /addtarget chalayein.")
            return
    except Exception as e:
        await update.message.reply_text(
            "❌ Group access nahi ho raha. Bot ko group mein add karke admin banayein aur sahi ID dein.\n"
            f"Details: {e}"
        )
        return

    targets = get_target_ids()
    if group_id in targets:
        await update.message.reply_text(f"ℹ️ {chat.title or group_id} pehle se target list mein hai.")
        return
    DATA["target_groups"] = targets + [group_id]
    save_data(DATA)
    await update.message.reply_text(
        f"✅ Target group add ho gaya!\n👥 Group: {chat.title or 'Group'}\n🆔 ID: {group_id}\n"
        "Welcome, join/leave tracking, keyword replies aur scheduled messages ab configured target groups par kaam karenge."
    )


async def remove_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not context.args:
        await update.message.reply_text("Use: /removetarget -1001234567890")
        return
    try:
        group_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Group ID number mein dein. Example: /removetarget -1001234567890")
        return
    targets = get_target_ids()
    if group_id not in targets:
        await update.message.reply_text("ℹ️ Ye ID target list mein nahi hai. /targets se list dekhein.")
        return
    remaining = [x for x in targets if x != group_id]
    # Keep the original group as fallback if the last target is removed.
    if not remaining:
        await update.message.reply_text("❌ Aakhri target group remove nahi kar sakte. Pehle doosra target /addtarget se add karein.")
        return
    DATA["target_groups"] = remaining
    save_data(DATA)
    await update.message.reply_text(f"🗑 Target group remove ho gaya: {group_id}\nBaaki groups par bot kaam karta rahega.")


async def select_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not context.args:
        await update.message.reply_text("Use: /selecttarget GROUP_ID\nPehle /targets se group IDs dekhein.")
        return
    try:
        gid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Group ID number mein dein, example: /selecttarget -1001234567890")
        return
    if gid not in get_target_ids():
        await update.message.reply_text("Ye target group configured nahi hai. Pehle /addtarget GROUP_ID karein.")
        return
    DATA["selected_target_group"] = gid
    save_data(DATA)
    try:
        chat = await context.bot.get_chat(gid)
        title = chat.title or str(gid)
    except Exception:
        title = str(gid)
    await update.message.reply_text(f"✅ Stats ke liye selected group: {title}\n🆔 {gid}\nAb /today, /yesterday, /lefttoday aur /stats isi group ka data dikhayenge.")


async def set_command_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not context.args:
        await update.message.reply_text("Use: /setcommandgroup GROUP_ID\nBot ko us group mein admin banayein.")
        return
    try:
        gid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Group ID number mein dein, example: /setcommandgroup -1001234567890")
        return
    try:
        chat = await context.bot.get_chat(gid)
        member = await context.bot.get_chat_member(gid, (await context.bot.get_me()).id)
        if member.status not in ("administrator", "creator"):
            await update.message.reply_text("Bot ko naye command group mein admin banayein pehle.")
            return
    except Exception as e:
        await update.message.reply_text(f"Group access nahi ho raha. Bot ko group mein admin banayein. Details: {e}")
        return
    DATA["command_group_id"] = gid
    save_data(DATA)
    await update.message.reply_text(f"✅ Command group set ho gaya: {chat.title or gid}\n🆔 {gid}\nAb admin commands isi group mein chalengi.")


async def list_targets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    lines = ["🎯 CONFIGURED TARGET GROUPS", "━━━━━━━━━━━━━━━━━━━━"]
    for gid in get_target_ids():
        try:
            chat = await context.bot.get_chat(gid)
            lines.append(f"\n👥 {chat.title or 'Group'}\n🆔 {gid}")
        except Exception:
            lines.append(f"\n🆔 {gid} (group details unavailable)")
    lines.append(f"\n\n⭐ Selected stats group: {selected_target_id()}")
    lines.append(f"💬 Command group ID: {DATA.get('command_group_id', COMMAND_CHAT_ID)}")
    lines.append("\n/addtarget ID — add group\n/removetarget ID — remove group\n/selecttarget ID — select group for stats\n/setcommandgroup ID — move stats commands to another group")
    await update.message.reply_text("\n".join(lines))


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

    for target_id in get_target_ids():
        await bot.set_chat_permissions(
            target_id,
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

    for target_id in get_target_ids():
        await bot.set_chat_permissions(
            target_id,
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
    greeting = DATA.get(
        "personal_welcome_text",
        "👋 Welcome to Wintask Bot!\n\n👇 Neeche se option choose karein:",
    )
    await update.message.reply_text(
        greeting,
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


async def edit_option(update, context):
    if not await admin_only(update, context):
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            "Use: /editoption OLD_NAME NEW_NAME MESSAGE\n"
            "Names mein space ki jagah underscore use karein.\n"
            "Example: /editoption Group_Link My_Group_Link Yahan naya message likhein"
        )
        return

    old_name = context.args[0].replace("_", " ").strip()
    new_name = context.args[1].replace("_", " ").strip()
    reply = " ".join(context.args[2:]).strip()
    options = DATA.setdefault("personal_options", {})

    if old_name not in options:
        await update.message.reply_text(f"❌ Purana option nahi mila: {old_name}")
        return
    if new_name != old_name and new_name in options:
        await update.message.reply_text(f"❌ Is naam ka option pehle se hai: {new_name}")
        return

    rebuilt = {}
    for key, value in options.items():
        if key == old_name:
            rebuilt[new_name] = reply
        else:
            rebuilt[key] = value
    DATA["personal_options"] = rebuilt
    save_data(DATA)
    await update.message.reply_text(
        f"✅ Personal topic update ho gaya.\n📌 Topic: {new_name}\n💬 Reply: {reply}"
    )

async def set_personal_welcome(update, context):
    if not await admin_only(update, context):
        return
    message = " ".join(context.args).strip()
    if not message:
        await update.message.reply_text(
            "Use: /setpersonalwelcome Private chat mein dikhne wala message"
        )
        return
    DATA["personal_welcome_text"] = message
    save_data(DATA)
    await update.message.reply_text("✅ Private bot welcome message update ho gaya.")

async def get_personal_welcome(update, context):
    if not await admin_only(update, context):
        return
    await update.message.reply_text(
        "📩 Private welcome message:\n\n" + DATA.get("personal_welcome_text", "")
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
        or not is_target_group(update.effective_chat.id)
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

async def get_welcome(update, context):
    if not await admin_only(update, context):
        return
    await update.message.reply_text(
        "👋 Current welcome message:\n\n"
        + str(DATA.get("welcome_text", DEFAULT_WELCOME))
        + "\n\nUse /setwelcome YOUR MESSAGE to change it.\n"
        "Use {mention} where the new member's clickable name should appear."
    )


async def autojoin_command(update, context):
    if not await admin_only(update, context):
        return
    if not context.args or context.args[0].lower() not in ("on", "off"):
        await update.message.reply_text(
            "Use:\n/autojoin on\n/autojoin off\n"
            "Time window set with /setautojoin 09:00 18:00"
        )
        return

    DATA["auto_accept_enabled"] = context.args[0].lower() == "on"
    save_data(DATA)
    if DATA["auto_accept_enabled"]:
        await update.message.reply_text(
            "✅ Auto-accept ON.\n"
            f"Requests from {DATA.get('auto_accept_start', '09:00')} to "
            f"{DATA.get('auto_accept_end', '18:00')} IST will be accepted automatically.\n"
            "Outside this time, requests will stay pending for an admin."
        )
    else:
        await update.message.reply_text(
            "🔴 Auto-accept OFF. All join requests will stay pending for admin approval."
        )


async def set_autojoin(update, context):
    if not await admin_only(update, context):
        return
    if len(context.args) != 2:
        await update.message.reply_text(
            "Use:\n/setautojoin 09:00 18:00\n"
            "Is time ke beech requests auto-accept hongi; baaki time admin approve karega."
        )
        return

    start_time = parse_hhmm(context.args[0])
    end_time = parse_hhmm(context.args[1])
    if start_time is None or end_time is None or start_time == end_time:
        await update.message.reply_text(
            "❌ Time galat hai. Example: /setautojoin 09:00 18:00. Start aur end time alag hon."
        )
        return

    DATA["auto_accept_start"] = start_time
    DATA["auto_accept_end"] = end_time
    DATA["auto_accept_enabled"] = True
    save_data(DATA)
    await update.message.reply_text(
        "✅ Auto-accept schedule saved and ON.\n"
        f"🟢 Auto accept: {start_time}–{end_time} IST\n"
        "🔒 Is window ke bahar join requests pending rahengi aur admin approval chahiye hoga.\n"
        "Band karne ke liye /autojoin off"
    )


async def join_request_handler(update, context):
    request = update.chat_join_request
    if not request or not is_target_group(request.chat.id):
        return

    if not DATA or not DATA.get("auto_accept_enabled", False):
        return  # Keep request pending; group admin must approve it.

    start_text = DATA.get("auto_accept_start", "09:00")
    end_text = DATA.get("auto_accept_end", "18:00")
    now_text = now_ist().strftime("%H:%M")

    # Inclusive start, exclusive end; supports a window that crosses midnight.
    if start_text < end_text:
        in_window = start_text <= now_text < end_text
    else:
        in_window = now_text >= start_text or now_text < end_text

    if not in_window:
        print(
            f"Join request left pending outside auto-accept window: {request.from_user.id} at {now_text} IST",
            flush=True,
        )
        return  # Manual admin approval is required outside the configured window.

    try:
        await context.bot.approve_chat_join_request(
            chat_id=request.chat.id,
            user_id=request.from_user.id,
        )
        print(
            f"Auto-approved join request: {request.from_user.id} at {now_text} IST",
            flush=True,
        )
    except Exception as e:
        print(f"Join request auto-accept error: {e}", flush=True)


async def new_member(update, context):
    if (
        not update.chat_member
        or update.effective_chat is None
        or not is_target_group(update.effective_chat.id)
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
            update.effective_chat.id,
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

    raw_parts = (update.message.text or "").strip().split(maxsplit=2)
    message = raw_parts[2].strip() if len(raw_parts) > 2 else ""
    if not message:
        await update.message.reply_text("Notice ka message bhi likhein. Example: /notice 12:30 Meeting\nPlease join on time")
        return

    DATA.setdefault("notices", []).append({
        "time": value,
        "message": message,
        "photo": (update.message.reply_to_message.photo[-1].file_id
                  if update.message.reply_to_message and update.message.reply_to_message.photo else ""),
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
        f"🎯 Target Group IDs: {', '.join(str(x) for x in get_target_ids())}\n"
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
                        for target_id in get_target_ids():
                            text = DATA.get("morning_text") or "🌞 Good Morning!"
                            photo = DATA.get("morning_photo") or ""
                            if photo:
                                await application.bot.send_photo(target_id, photo=photo, caption=text[:1024])
                            else:
                                await application.bot.send_message(target_id, text=text)
                        DATA["morning_last_sent"] = today
                        changed = True
                    except Exception as e:
                        print(f"Good Morning send error: {e}", flush=True)

                if DATA.get("night_time") == hhmm and DATA.get("night_last_sent") != today:
                    try:
                        for target_id in get_target_ids():
                            text = DATA.get("night_text") or "🌙 Good Night!"
                            photo = DATA.get("night_photo") or ""
                            if photo:
                                await application.bot.send_photo(target_id, photo=photo, caption=text[:1024])
                            else:
                                await application.bot.send_message(target_id, text=text)
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
                            for target_id in get_target_ids():
                                text = f"📢 {item['message']}"
                                photo = item.get("photo") or ""
                                if photo:
                                    await application.bot.send_photo(target_id, photo=photo, caption=text[:1024])
                                else:
                                    await application.bot.send_message(target_id, text=text)

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

def command_payload(update, command_name):
    """Return schedule time and message while preserving user line breaks."""
    raw = (update.message.text or "").strip()
    parts = raw.split(maxsplit=2)
    if len(parts) < 2:
        return None, ""
    time_value = parse_hhmm(parts[1])
    message = parts[2] if len(parts) > 2 else ""
    return time_value, message.strip()

async def set_morning(update, context):
    if not await admin_only(update, context):
        return
    value, message = command_payload(update, "setmorning")
    if value is None or not message:
        await update.message.reply_text(
            "Use: /setmorning 07:00\nGood Morning everyone!\n\n"
            "Text ki line breaks preserve rahengi. Photo ke liye photo par reply karke /morningphoto bhejein."
        )
        return
    DATA["morning_time"] = value
    DATA["morning_text"] = message
    DATA["morning_last_sent"] = ""
    save_data(DATA)
    await update.message.reply_text(f"✅ Morning message saved for {value} IST.\nPhoto: {'set' if DATA.get('morning_photo') else 'not set'}")

async def set_night(update, context):
    if not await admin_only(update, context):
        return
    value, message = command_payload(update, "setnight")
    if value is None or not message:
        await update.message.reply_text(
            "Use: /setnight 22:00\nGood Night everyone!\n\n"
            "Text ki line breaks preserve rahengi. Photo ke liye photo par reply karke /nightphoto bhejein."
        )
        return
    DATA["night_time"] = value
    DATA["night_text"] = message
    DATA["night_last_sent"] = ""
    save_data(DATA)
    await update.message.reply_text(f"✅ Night message saved for {value} IST.\nPhoto: {'set' if DATA.get('night_photo') else 'not set'}")

async def set_morning_photo(update, context):
    if not await admin_only(update, context): return
    reply = update.message.reply_to_message
    if not reply or not reply.photo:
        await update.message.reply_text("Pehle poster/photo bhejein, phir us photo par reply karke /morningphoto likhein.")
        return
    DATA["morning_photo"] = reply.photo[-1].file_id
    save_data(DATA)
    await update.message.reply_text("✅ Morning poster save ho gaya.")

async def clear_morning_photo(update, context):
    if not await admin_only(update, context): return
    DATA["morning_photo"] = ""
    save_data(DATA)
    await update.message.reply_text("✅ Morning poster hata diya; ab sirf text jayega.")

async def set_night_photo(update, context):
    if not await admin_only(update, context): return
    reply = update.message.reply_to_message
    if not reply or not reply.photo:
        await update.message.reply_text("Pehle poster/photo bhejein, phir us photo par reply karke /nightphoto likhein.")
        return
    DATA["night_photo"] = reply.photo[-1].file_id
    save_data(DATA)
    await update.message.reply_text("✅ Night poster save ho gaya.")

async def clear_night_photo(update, context):
    if not await admin_only(update, context): return
    DATA["night_photo"] = ""
    save_data(DATA)
    await update.message.reply_text("✅ Night poster hata diya; ab sirf text jayega.")

async def set_notice_photo(update, context):
    if not await admin_only(update, context): return
    reply = update.message.reply_to_message
    if not reply or not reply.photo:
        await update.message.reply_text("Photo par reply karke /noticephoto NUMBER likhein. Example: /noticephoto 1")
        return
    if not context.args:
        await update.message.reply_text("Use: /noticephoto NUMBER (photo par reply karke)")
        return
    try: number = int(context.args[0])
    except ValueError: number = 0
    items = DATA.get("notices", [])
    if not 1 <= number <= len(items):
        await update.message.reply_text("❌ Notice number galat hai. /notices dekhein.")
        return
    items[number-1]["photo"] = reply.photo[-1].file_id
    save_data(DATA)
    await update.message.reply_text(f"✅ Notice #{number} ka poster save ho gaya.")

async def clear_notice_photo(update, context):
    if not await admin_only(update, context): return
    if not context.args:
        await update.message.reply_text("Use: /clearnoticephoto NUMBER")
        return
    try: number = int(context.args[0])
    except ValueError: number = 0
    items = DATA.get("notices", [])
    if not 1 <= number <= len(items):
        await update.message.reply_text("❌ Notice number galat hai.")
        return
    items[number-1]["photo"] = ""
    save_data(DATA)
    await update.message.reply_text(f"✅ Notice #{number} ka poster hata diya.")



# ============================================================
# TARGET GROUP JOIN / LEAVE TRACKING
# ============================================================

async def member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member

    if not cm or not is_target_group(cm.chat.id):
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

        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO member_current_join(user_id, joined_date, is_member)
                    VALUES (%s, %s, TRUE)
                    ON CONFLICT(user_id) DO UPDATE SET
                        joined_date = EXCLUDED.joined_date,
                        is_member = TRUE
                """, (uid, event_date))
                cur.execute("""
                    INSERT INTO daily_join_cohort(event_date, joins, same_day_leaves)
                    VALUES (%s, 1, 0)
                    ON CONFLICT(event_date) DO UPDATE SET
                        joins = daily_join_cohort.joins + 1
                """, (event_date,))
                cur.execute("""
                    INSERT INTO group_member_current_join(group_id, user_id, joined_date, is_member)
                    VALUES (%s, %s, %s, TRUE)
                    ON CONFLICT(group_id, user_id) DO UPDATE SET
                        joined_date = EXCLUDED.joined_date,
                        is_member = TRUE
                """, (cm.chat.id, uid, event_date))

        # Telegram gives the invite link responsible for the join
        # when the update contains invite attribution.
        if cm.invite_link:
            invite_url = cm.invite_link.invite_link

        add_daily_total(event_date, joins=1)
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO group_daily_totals(group_id, event_date, joins, leaves)
                    VALUES (%s, %s, 1, 0)
                    ON CONFLICT(group_id, event_date) DO UPDATE SET
                        joins = group_daily_totals.joins + 1
                """, (cm.chat.id, event_date))
                cur.execute("""
                    INSERT INTO group_daily_join_cohort(group_id, event_date, joins, same_day_leaves)
                    VALUES (%s, %s, 1, 0)
                    ON CONFLICT(group_id, event_date) DO UPDATE SET
                        joins = group_daily_join_cohort.joins + 1
                """, (cm.chat.id, event_date))

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
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO group_daily_totals(group_id, event_date, joins, leaves)
                    VALUES (%s, %s, 0, 1)
                    ON CONFLICT(group_id, event_date) DO UPDATE SET
                        leaves = group_daily_totals.leaves + 1
                """, (cm.chat.id, event_date))

        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT joined_date, is_member
                    FROM group_member_current_join
                    WHERE group_id = %s AND user_id = %s
                """, (cm.chat.id, uid))
                membership = cur.fetchone()
                if membership and membership[1] and membership[0] == event_date:
                    cur.execute("""
                        INSERT INTO daily_join_cohort(event_date, joins, same_day_leaves)
                        VALUES (%s, 0, 1)
                        ON CONFLICT(event_date) DO UPDATE SET
                            same_day_leaves = daily_join_cohort.same_day_leaves + 1
                    """, (event_date,))
                    cur.execute("""
                        INSERT INTO group_daily_join_cohort(group_id, event_date, joins, same_day_leaves)
                        VALUES (%s, %s, 0, 1)
                        ON CONFLICT(group_id, event_date) DO UPDATE SET
                            same_day_leaves = group_daily_join_cohort.same_day_leaves + 1
                    """, (cm.chat.id, event_date))
                cur.execute("""
                    UPDATE member_current_join SET is_member = FALSE
                    WHERE user_id = %s
                """, (uid,))
                cur.execute("""
                    UPDATE group_member_current_join SET is_member = FALSE
                    WHERE group_id = %s AND user_id = %s
                """, (cm.chat.id, uid))

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
    print(f"Target Groups: {get_target_ids()}", flush=True)
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
    app.add_handler(CommandHandler("targets", list_targets))
    app.add_handler(CommandHandler("addtarget", add_target))
    app.add_handler(CommandHandler("removetarget", remove_target))
    app.add_handler(CommandHandler("selecttarget", select_target))
    app.add_handler(CommandHandler("setcommandgroup", set_command_group))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("lefttoday", lefttoday))
    app.add_handler(CommandHandler("yesterday", yesterday))
    app.add_handler(CommandHandler("addlink", addlink))
    app.add_handler(CommandHandler("newlink", newlink))
    app.add_handler(CommandHandler("deletelink", deletelink))
    app.add_handler(CommandHandler("links", links))
    app.add_handler(CommandHandler("mylink", mylink))

    # Group automation and scheduled messages.
    app.add_handler(CommandHandler("welcome", welcome_command))
    app.add_handler(CommandHandler("setwelcome", set_welcome))
    app.add_handler(CommandHandler("getwelcome", get_welcome))
    app.add_handler(CommandHandler("autojoin", autojoin_command))
    app.add_handler(CommandHandler("setautojoin", set_autojoin))
    app.add_handler(CommandHandler("seton", set_on))
    app.add_handler(CommandHandler("setoff", set_off))
    app.add_handler(CommandHandler("setmorning", set_morning))
    app.add_handler(CommandHandler("setnight", set_night))
    app.add_handler(CommandHandler("morningphoto", set_morning_photo))
    app.add_handler(CommandHandler("clearmorningphoto", clear_morning_photo))
    app.add_handler(CommandHandler("nightphoto", set_night_photo))
    app.add_handler(CommandHandler("clearnightphoto", clear_night_photo))
    app.add_handler(CommandHandler("noticephoto", set_notice_photo))
    app.add_handler(CommandHandler("clearnoticephoto", clear_notice_photo))
    app.add_handler(CommandHandler("notice", notice))
    app.add_handler(CommandHandler("notices", notices))
    app.add_handler(CommandHandler("delnotice", delete_notice))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CommandHandler("addkeyword", add_keyword))
    app.add_handler(CommandHandler("keywords", list_keywords))
    app.add_handler(CommandHandler("deletekeyword", delete_keyword))
    app.add_handler(CommandHandler("addoption", add_option))
    app.add_handler(CommandHandler("editoption", edit_option))
    app.add_handler(CommandHandler("setpersonalwelcome", set_personal_welcome))
    app.add_handler(CommandHandler("getpersonalwelcome", get_personal_welcome))
    app.add_handler(CommandHandler("options", list_options))
    app.add_handler(CommandHandler("deleteoption", delete_option))

    app.add_handler(CallbackQueryHandler(personal_button))
    # Different handler groups ensure both join-welcome and invite attribution run.
    app.add_handler(ChatJoinRequestHandler(join_request_handler), group=0)
    app.add_handler(ChatMemberHandler(member_update, ChatMemberHandler.CHAT_MEMBER), group=0)
    app.add_handler(ChatMemberHandler(new_member, ChatMemberHandler.CHAT_MEMBER), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, group_keyword_reply))
    app.add_error_handler(error_handler)
    print("Bot polling started...", flush=True)
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)

if __name__ == "__main__":
    main()
