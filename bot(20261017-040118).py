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



DEFAULT_WELCOME = (
    "👋 Welcome {mention}!\n\n"
    "🎉 Welcome to the group.\n"
    "Please read the group rules and enjoy!"
)


GROUP_SETTING_DEFAULTS = {
    "welcome_enabled": True, "welcome_text": DEFAULT_WELCOME, "welcome_poster_id": "",
    "auto_accept_enabled": False, "auto_accept_start": "09:00", "auto_accept_end": "18:00",
    "on_time": "", "off_time": "", "morning_time": "",
    "morning_text": "🌞 Good Morning everyone!", "morning_poster_id": "", "morning_last_sent": "",
    "night_time": "", "night_text": "🌙 Good Night everyone!", "night_poster_id": "", "night_last_sent": "",
    "notices": [], "keywords": {},
}

def group_settings(group_id=None):
    """Persistent settings isolated by target group; old global settings migrate to first target."""
    if group_id is None:
        group_id = selected_target_id()
    key = str(int(group_id))
    all_settings = DATA.setdefault("group_settings", {})
    if key not in all_settings:
        cfg = json.loads(json.dumps(GROUP_SETTING_DEFAULTS, ensure_ascii=False))
        # Backward-compatible migration: preserve existing global settings for the original target.
        if int(group_id) == TARGET_CHAT_ID:
            for name in GROUP_SETTING_DEFAULTS:
                if name in DATA:
                    cfg[name] = DATA[name]
        all_settings[key] = cfg
    cfg = all_settings[key]
    for name, default in GROUP_SETTING_DEFAULTS.items():
        if name not in cfg:
            cfg[name] = json.loads(json.dumps(default, ensure_ascii=False))
    return cfg

def group_setting_for_update(update):
    return group_settings(selected_target_id())

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
        + "To switch group use /selecttarget GROUP_ID /changegroup."
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
    "welcome_poster_id": "",
    "auto_accept_enabled": False,
    "auto_accept_start": "09:00",
    "auto_accept_end": "18:00",
    "on_time": "",
    "off_time": "",
    "morning_time": "",
    "morning_text": "🌞 Good Morning everyone!",
    "morning_poster_id": "",
    "morning_last_sent": "",
    "night_time": "",
    "night_text": "🌙 Good Night everyone!",
    "night_poster_id": "",
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
        "/selecttarget GROUP_ID /changegroup  /setcommandgroup GROUP_ID\n"
        "/addlink NAME LINK\n/newlink NAME\n/deletelink NAME_OR_LINK\n/links  /mylink\n\n"
        "🤖 AUTOMATION\n"
        "/welcome on|off\n/setwelcome MESSAGE\n/getwelcome\n"
        "/setautojoin START END  (e.g. /setautojoin 09:00 18:00)\n"
        "/autojoin on|off\n"
        "/seton HH:MM\n/setoff HH:MM\n"
        "/setmorning HH:MM MESSAGE\n/setnight HH:MM MESSAGE\n"
        "/notice HH:MM MESSAGE\n/notices\n/delnotice NUMBER\n"
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


async def change_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show configured target groups as buttons; chosen group controls stats and automation settings."""
    if not await check_access(update, context):
        return
    targets = get_target_ids()
    buttons = []
    for gid in targets:
        try:
            chat = await context.bot.get_chat(gid)
            title = chat.title or str(gid)
        except Exception:
            title = str(gid)
        marker = "✅ " if gid == selected_target_id() else ""
        buttons.append([InlineKeyboardButton(f"{marker}{title} · {gid}", callback_data=f"changegroup:{gid}")])
    if not buttons:
        await update.message.reply_text("Target groups nahi mile. Pehle /addtarget GROUP_ID karein.")
        return
    await update.message.reply_text(
        "🎯 Group select karein. Is selection ke baad Stats aur settings commands selected group par kaam karengi:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def change_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data or not query.data.startswith("changegroup:"):
        return
    # CallbackQuery updates do not have update.message, so check access directly.
    if not update.effective_chat or update.effective_chat.type == "private" or not command_group(update):
        await query.answer("Command group mein use karein", show_alert=True)
        return
    if not await is_admin(update, context):
        await query.answer("Admin access required", show_alert=True)
        return
    try:
        gid = int(query.data.split(":", 1)[1])
    except ValueError:
        await query.answer("Invalid group", show_alert=True)
        return
    if gid not in get_target_ids():
        await query.answer("Ye group target list mein nahi hai", show_alert=True)
        return
    DATA["selected_target_group"] = gid
    save_data(DATA)
    try:
        chat = await context.bot.get_chat(gid)
        title = chat.title or str(gid)
    except Exception:
        title = str(gid)
    await query.answer("Group selected")
    await query.edit_message_text(
        f"✅ Selected group: {title}\n🆔 {gid}\n\nAb Stats aur group-settings commands isi group ke liye apply hongi."
    )


async def select_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not context.args:
        await update.message.reply_text("Use: /selecttarget GROUP_ID /changegroup\nYa /changegroup se buttons mein group select karein.")
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
    await update.message.reply_text(f"✅ Selected group: {title}\n🆔 {gid}\nAb Stats aur group-settings commands isi group ke liye apply hongi.")


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

async def set_group_chat_on(bot, only_target_id=None):
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

    target_ids = [only_target_id] if only_target_id is not None else get_target_ids()
    for target_id in target_ids:
        await bot.set_chat_permissions(
            target_id,
            permissions,
            use_independent_chat_permissions=True,
        )

async def set_group_chat_off(bot, only_target_id=None):
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

    target_ids = [only_target_id] if only_target_id is not None else get_target_ids()
    for target_id in target_ids:
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
    if not await admin_only(update, context): return
    if len(context.args) < 2: await update.message.reply_text("Use: /addkeyword payment Payment ke liye admin se contact karein."); return
    word = context.args[0].lower().strip(); reply = " ".join(context.args[1:]).strip(); cfg = group_setting_for_update(update)
    cfg.setdefault("keywords", {})[word] = reply; save_data(DATA)
    await update.message.reply_text(f"✅ Group {selected_target_id()} keyword added: {word} → {reply}")


async def list_keywords(update, context):
    if not await admin_only(update, context): return
    items = group_setting_for_update(update).get("keywords", {})
    if not items: await update.message.reply_text(f"📭 Group {selected_target_id()}: koi keyword set nahi."); return
    await update.message.reply_text(f"🔑 Group {selected_target_id()} keywords:\n\n" + "\n".join(f"• {k} → {v}" for k,v in items.items()))


async def delete_keyword(update, context):
    if not await admin_only(update, context): return
    if not context.args: await update.message.reply_text("Use: /deletekeyword payment"); return
    word = context.args[0].lower().strip(); items = group_setting_for_update(update).setdefault("keywords", {})
    if word not in items: await update.message.reply_text("❌ Ye keyword nahi mila."); return
    del items[word]; save_data(DATA); await update.message.reply_text(f"🗑 Group {selected_target_id()} keyword deleted: {word}")


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
    chat = update.effective_chat
    msg = update.message
    if not chat or not is_target_group(chat.id) or not msg or not msg.text or msg.text.startswith("/"):
        return
    cfg = group_settings(chat.id)
    text = msg.text.lower()
    for word, reply in cfg.get("keywords", {}).items():
        if word.lower() in text:
            try:
                await msg.reply_text(reply)
            except Exception as e:
                print(f"Keyword reply error: {e}", flush=True)
            break


async def welcome_command(update, context):
    if not await admin_only(update, context): return
    cfg = group_setting_for_update(update)
    if not context.args or context.args[0].lower() not in ("on", "off"):
        await update.message.reply_text("Use: /welcome on or /welcome off\nSelected group: " + str(selected_target_id())); return
    cfg["welcome_enabled"] = context.args[0].lower() == "on"
    save_data(DATA)
    await update.message.reply_text("👋 Welcome message: " + ("ON 🟢" if cfg["welcome_enabled"] else "OFF 🔴") + f"\n🎯 Group: {selected_target_id()}")


async def set_welcome(update, context):
    if not await admin_only(update, context): return
    text = update.message.text.partition(" ")[2].strip()
    if not text:
        await update.message.reply_text("Use: /setwelcome Welcome {mention}! 🎉"); return
    cfg = group_setting_for_update(update); cfg["welcome_text"] = text; save_data(DATA)
    await update.message.reply_text(f"✅ Group {selected_target_id()} ka welcome message save ho gaya. Use {{mention}} for member name.")


async def get_welcome(update, context):
    if not await admin_only(update, context): return
    cfg = group_setting_for_update(update)
    await update.message.reply_text(f"🎯 Group: {selected_target_id()}\n👋 Welcome: {'ON' if cfg.get('welcome_enabled', True) else 'OFF'}\n\n{cfg.get('welcome_text', DEFAULT_WELCOME)}\n\nChange: /setwelcome YOUR MESSAGE")


async def autojoin_command(update, context):
    if not await admin_only(update, context): return
    cfg = group_setting_for_update(update)
    if not context.args or context.args[0].lower() not in ("on", "off"):
        await update.message.reply_text("Use: /autojoin on or /autojoin off"); return
    cfg["auto_accept_enabled"] = context.args[0].lower() == "on"; save_data(DATA)
    await update.message.reply_text(f"🎯 Group {selected_target_id()}\nAuto-accept: {'ON' if cfg['auto_accept_enabled'] else 'OFF'}\nWindow: {cfg.get('auto_accept_start')}–{cfg.get('auto_accept_end')} IST")


async def set_autojoin(update, context):
    if not await admin_only(update, context): return
    if len(context.args) != 2:
        await update.message.reply_text("Use: /setautojoin 09:00 18:00"); return
    start_time, end_time = parse_hhmm(context.args[0]), parse_hhmm(context.args[1])
    if start_time is None or end_time is None or start_time == end_time:
        await update.message.reply_text("❌ Sahi time dein. Example: /setautojoin 09:00 18:00"); return
    cfg = group_setting_for_update(update); cfg.update(auto_accept_start=start_time, auto_accept_end=end_time, auto_accept_enabled=True); save_data(DATA)
    await update.message.reply_text(f"✅ Group {selected_target_id()} ke liye auto-accept ON: {start_time}–{end_time} IST")


async def join_request_handler(update, context):
    request = update.chat_join_request
    if not request or not is_target_group(request.chat.id): return
    cfg = group_settings(request.chat.id)
    if not cfg.get("auto_accept_enabled", False): return
    start_text, end_text = cfg.get("auto_accept_start", "09:00"), cfg.get("auto_accept_end", "18:00")
    now_text = now_ist().strftime("%H:%M")
    in_window = (start_text <= now_text < end_text) if start_text < end_text else (now_text >= start_text or now_text < end_text)
    if not in_window: return
    try:
        await context.bot.approve_chat_join_request(chat_id=request.chat.id, user_id=request.from_user.id)
        print(f"Auto-approved join request for group {request.chat.id}: {request.from_user.id}", flush=True)
    except Exception as e: print(f"Join request auto-accept error: {e}", flush=True)


async def send_text_with_optional_poster(bot, chat_id, text, poster_id="", parse_mode=None):
    """Send saved text with optional saved Telegram photo; preserve line breaks."""
    if poster_id:
        # Telegram photo captions are limited to 1024 characters.
        if len(text) <= 1024:
            await bot.send_photo(chat_id=chat_id, photo=poster_id, caption=text, parse_mode=parse_mode)
        else:
            await bot.send_photo(chat_id=chat_id, photo=poster_id)
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode, disable_web_page_preview=True)
    else:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode, disable_web_page_preview=True)

async def set_saved_poster(update, context, key, label):
    if not await admin_only(update, context): return
    msg = update.message.reply_to_message if update.message else None
    if not msg or not msg.photo:
        await update.message.reply_text(f"Photo par reply karke /{context.args[0] if context.args else label.lower().replace(' ', '')} command bhejein."); return
    group_setting_for_update(update)[key] = msg.photo[-1].file_id; save_data(DATA)
    await update.message.reply_text(f"✅ Group {selected_target_id()} ka {label} poster save ho gaya.")


async def clear_saved_poster(update, context, key, label):
    if not await admin_only(update, context): return
    group_setting_for_update(update)[key] = ""; save_data(DATA)
    await update.message.reply_text(f"✅ Group {selected_target_id()} ka {label} poster hata diya.")


async def new_member(update, context):
    cm = update.chat_member
    if not cm or not is_target_group(cm.chat.id): return
    old_status, new_status = cm.old_chat_member.status, cm.new_chat_member.status
    if not (new_status in ("member", "restricted") and old_status in ("left", "kicked")): return
    cfg = group_settings(cm.chat.id)
    if not cfg.get("welcome_enabled", True): return
    user = cm.new_chat_member.user
    text = cfg.get("welcome_text", DEFAULT_WELCOME).replace("{mention}", mention_html(user))
    try:
        await send_text_with_optional_poster(context.bot, cm.chat.id, text, cfg.get("welcome_poster_id", ""), parse_mode="HTML")
    except Exception as e: print(f"Welcome error for {cm.chat.id}: {e}", flush=True)


async def set_on(update, context):
    if not await admin_only(update, context): return
    value = parse_hhmm(context.args[0]) if context.args else None
    if value is None:
        await update.message.reply_text("Use: /seton 09:00"); return
    group_setting_for_update(update)["on_time"] = value; save_data(DATA)
    await update.message.reply_text(f"🟢 Group {selected_target_id()} ON time: {value} IST")


async def set_off(update, context):
    if not await admin_only(update, context): return
    value = parse_hhmm(context.args[0]) if context.args else None
    if value is None:
        await update.message.reply_text("Use: /setoff 22:00"); return
    group_setting_for_update(update)["off_time"] = value; save_data(DATA)
    await update.message.reply_text(f"🔴 Group {selected_target_id()} OFF time: {value} IST")


async def notice(update, context):
    if not await admin_only(update, context): return
    if len(context.args) < 2:
        await update.message.reply_text("Use: /notice 12:30 Important announcement"); return
    value = parse_hhmm(context.args[0]); parts = update.message.text.split(None, 2); message = parts[2].strip() if len(parts) > 2 else ""
    if value is None or not message:
        await update.message.reply_text("❌ Use: /notice 12:30 Message"); return
    cfg = group_setting_for_update(update); cfg.setdefault("notices", []).append({"time": value, "message": message, "poster_id": "", "last_sent": ""}); save_data(DATA)
    await update.message.reply_text(f"✅ Group {selected_target_id()} notice #{len(cfg['notices'])} saved at {value} IST.")


async def set_welcome_poster(update, context):
    await set_saved_poster(update, context, "welcome_poster_id", "Welcome")

async def clear_welcome_poster(update, context):
    await clear_saved_poster(update, context, "welcome_poster_id", "Welcome")

async def set_morning_poster(update, context):
    await set_saved_poster(update, context, "morning_poster_id", "Good Morning")

async def clear_morning_poster(update, context):
    await clear_saved_poster(update, context, "morning_poster_id", "Good Morning")

async def set_night_poster(update, context):
    await set_saved_poster(update, context, "night_poster_id", "Good Night")

async def clear_night_poster(update, context):
    await clear_saved_poster(update, context, "night_poster_id", "Good Night")

async def set_notice_poster(update, context):
    if not await admin_only(update, context): return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Photo par reply karke /setnoticeposter 1"); return
    cfg = group_setting_for_update(update); number = int(context.args[0]); msg = update.message.reply_to_message; items = cfg.get("notices", [])
    if not 1 <= number <= len(items): await update.message.reply_text("❌ Notice number nahi mila."); return
    if not msg or not msg.photo: await update.message.reply_text("❌ Kisi photo par reply karein."); return
    items[number-1]["poster_id"] = msg.photo[-1].file_id; save_data(DATA)
    await update.message.reply_text(f"✅ Group {selected_target_id()} notice #{number} poster save ho gaya.")


async def clear_notice_poster(update, context):
    if not await admin_only(update, context): return
    if not context.args or not context.args[0].isdigit(): await update.message.reply_text("Use: /clearnoticeposter 1"); return
    cfg = group_setting_for_update(update); number = int(context.args[0]); items = cfg.get("notices", [])
    if not 1 <= number <= len(items): await update.message.reply_text("❌ Notice number nahi mila."); return
    items[number-1]["poster_id"] = ""; save_data(DATA); await update.message.reply_text(f"✅ Group {selected_target_id()} notice #{number} poster cleared.")


async def notices(update, context):
    if not await admin_only(update, context): return
    items = group_setting_for_update(update).get("notices", [])
    if not items: await update.message.reply_text(f"📭 Group {selected_target_id()}: koi scheduled notice nahi."); return
    await update.message.reply_text(f"📢 Group {selected_target_id()} Scheduled Notices:\n\n" + "\n\n".join(f"{i}. ⏰ {x['time']} IST\n{x['message']}" for i,x in enumerate(items,1)))


async def delete_notice(update, context):
    if not await admin_only(update, context): return
    if not context.args or not context.args[0].isdigit(): await update.message.reply_text("Use: /delnotice 1"); return
    cfg = group_setting_for_update(update); items = cfg.get("notices", []); n = int(context.args[0])
    if not 1 <= n <= len(items): await update.message.reply_text("❌ Notice number nahi mila."); return
    removed = items.pop(n-1); save_data(DATA); await update.message.reply_text(f"🗑 Group {selected_target_id()} notice deleted: {removed['message']}")


async def settings(update, context):
    if not await admin_only(update, context): return
    cfg = group_setting_for_update(update)
    await update.message.reply_text(
        f"⚙️ SETTINGS — GROUP {selected_target_id()}\n\n"
        f"👋 Welcome: {'ON 🟢' if cfg.get('welcome_enabled') else 'OFF 🔴'}\n"
        f"🟢 Group ON: {cfg.get('on_time') or 'Not set'} IST\n🔴 Group OFF: {cfg.get('off_time') or 'Not set'} IST\n"
        f"🌞 Morning: {cfg.get('morning_time') or 'Not set'} IST\n🌙 Night: {cfg.get('night_time') or 'Not set'} IST\n"
        f"📢 Notices: {len(cfg.get('notices', []))}\n🔑 Keywords: {len(cfg.get('keywords', {}))}\n"
        f"🤖 Auto-accept: {'ON' if cfg.get('auto_accept_enabled') else 'OFF'} ({cfg.get('auto_accept_start')}–{cfg.get('auto_accept_end')})\n"
        f"💾 PostgreSQL storage: ON\n\nGroup change: /selecttarget GROUP_ID /changegroup")


async def scheduler(application):
    print("⏰ Group-specific scheduler started.", flush=True)
    last_minute = ""
    while True:
        try:
            current = now_ist(); hhmm = current.strftime("%H:%M"); today = current.strftime("%Y-%m-%d")
            minute_key = f"{today} {hhmm}"
            if minute_key != last_minute:
                last_minute = minute_key
                changed = False
                for target_id in get_target_ids():
                    cfg = group_settings(target_id)
                    if cfg.get("on_time") == hhmm:
                        try: await set_group_chat_on(application.bot, target_id)
                        except Exception as e: print(f"Group ON error {target_id}: {e}", flush=True)
                    if cfg.get("off_time") == hhmm:
                        try: await set_group_chat_off(application.bot, target_id)
                        except Exception as e: print(f"Group OFF error {target_id}: {e}", flush=True)
                    if cfg.get("morning_time") == hhmm and cfg.get("morning_last_sent") != today:
                        try:
                            await send_text_with_optional_poster(application.bot, target_id, cfg.get("morning_text") or "🌞 Good Morning!", cfg.get("morning_poster_id", ""))
                            cfg["morning_last_sent"] = today; changed = True
                        except Exception as e: print(f"Morning send error {target_id}: {e}", flush=True)
                    if cfg.get("night_time") == hhmm and cfg.get("night_last_sent") != today:
                        try:
                            await send_text_with_optional_poster(application.bot, target_id, cfg.get("night_text") or "🌙 Good Night!", cfg.get("night_poster_id", ""))
                            cfg["night_last_sent"] = today; changed = True
                        except Exception as e: print(f"Night send error {target_id}: {e}", flush=True)
                    for item in cfg.get("notices", []):
                        if item.get("time") == hhmm and item.get("last_sent") != today:
                            try:
                                await send_text_with_optional_poster(application.bot, target_id, f"📢 {item['message']}", item.get("poster_id", ""))
                                item["last_sent"] = today; changed = True
                            except Exception as e: print(f"Notice error {target_id}: {e}", flush=True)
                if changed: save_data(DATA)
            await asyncio.sleep(10)
        except asyncio.CancelledError: raise
        except Exception as e:
            print(f"Scheduler error: {e}", flush=True); await asyncio.sleep(10)


async def set_morning(update, context):
    if not await admin_only(update, context): return
    if len(context.args) < 2: await update.message.reply_text("Use: /setmorning 07:00 Good Morning everyone!"); return
    value = parse_hhmm(context.args[0]); parts = update.message.text.split(None, 2); message = parts[2].strip() if len(parts)>2 else ""
    if value is None or not message: await update.message.reply_text("❌ Use: /setmorning 07:00 Message"); return
    cfg = group_setting_for_update(update); cfg.update(morning_time=value, morning_text=message, morning_last_sent=""); save_data(DATA)
    await update.message.reply_text(f"✅ Group {selected_target_id()} Good Morning set: {value} IST\n{message}")


async def set_night(update, context):
    if not await admin_only(update, context): return
    if len(context.args) < 2: await update.message.reply_text("Use: /setnight 22:00 Good Night everyone!"); return
    value = parse_hhmm(context.args[0]); parts = update.message.text.split(None, 2); message = parts[2].strip() if len(parts)>2 else ""
    if value is None or not message: await update.message.reply_text("❌ Use: /setnight 22:00 Message"); return
    cfg = group_setting_for_update(update); cfg.update(night_time=value, night_text=message, night_last_sent=""); save_data(DATA)
    await update.message.reply_text(f"✅ Group {selected_target_id()} Good Night set: {value} IST\n{message}")


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
    app.add_handler(CommandHandler("changegroup", change_group))
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
    app.add_handler(CommandHandler("setwelcomeposter", set_welcome_poster))
    app.add_handler(CommandHandler("clearwelcomeposter", clear_welcome_poster))
    app.add_handler(CommandHandler("autojoin", autojoin_command))
    app.add_handler(CommandHandler("setautojoin", set_autojoin))
    app.add_handler(CommandHandler("seton", set_on))
    app.add_handler(CommandHandler("setoff", set_off))
    app.add_handler(CommandHandler("setmorning", set_morning))
    app.add_handler(CommandHandler("setmorningposter", set_morning_poster))
    app.add_handler(CommandHandler("clearmorningposter", clear_morning_poster))
    app.add_handler(CommandHandler("setnight", set_night))
    app.add_handler(CommandHandler("setnightposter", set_night_poster))
    app.add_handler(CommandHandler("clearnightposter", clear_night_poster))
    app.add_handler(CommandHandler("notice", notice))
    app.add_handler(CommandHandler("notices", notices))
    app.add_handler(CommandHandler("delnotice", delete_notice))
    app.add_handler(CommandHandler("setnoticeposter", set_notice_poster))
    app.add_handler(CommandHandler("clearnoticeposter", clear_notice_poster))
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

    app.add_handler(CallbackQueryHandler(change_group_callback, pattern=r"^changegroup:"))
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
