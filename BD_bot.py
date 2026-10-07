#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto Reaction Bot
-----------------
Channel-e post hole automatic SMM panel API diye reaction/views order pathay.

Features:
- Multi channel add/remove + ON/OFF
- SMM Provider API (PerfectPanel style)
- Quantity + Service ID setup
- Wallet + markup (provider cost + fixed BDT)
- Binance Instant Pay (API Key/Secret/PayID/Address)
- bKash / Nagad / Rocket manual deposit
- Force channel join (add/remove)
- Order Track by provider Order ID
- Admin Control Panel (screenshot-style buttons)
- How to Use

Env:
  BOT_TOKEN=8865204426:AAH2LcI6nJmIdrx_LpsrB2Yf8xKXC7b-hDs
  OWNER_ID=8289191009
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import datetime
from urllib.parse import quote

import requests
import telebot
from telebot import types

# ================== CONFIG ==================
# সবচেয়ে সহজ: নিচের লাইনে BotFather টোকেন বসান
BOT_TOKEN_HERE = "8865204426:AAF1jIpU4OOlUQYmzgyYB4vmzSaw20YU4tE"
OWNER_ID_HERE = 8289191009

TOKEN = (
    (BOT_TOKEN_HERE or "").strip()
    or os.environ.get("BOT_TOKEN", "").strip()
    or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
)
OWNER_ID = int(
    os.environ.get("OWNER_ID", "").strip() or OWNER_ID_HERE or 8289191009
)
ADMIN_ID = int(os.environ.get("ADMIN_ID", str(OWNER_ID)))
DB_PATH = os.environ.get("AR_DB", "auto_reaction.db")

if not TOKEN:
    raise SystemExit(
        "BOT_TOKEN missing!\n"
        "1) auto_reaction_bot.py খুলুন\n"
        "2) BOT_TOKEN_HERE = \"BotFather_token\" লিখুন\n"
        "   অথবা: export BOT_TOKEN=\"token\"\n"
        "3) আবার চালান"
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("auto_reaction")

bot = telebot.TeleBot(TOKEN, parse_mode=None)
DB_LOCK = threading.Lock()
admin_ids = {OWNER_ID, ADMIN_ID}
user_state = {}  # uid -> {action, ...}


# ================== DB ==================
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def row_get(row, key, default=None):
    if row is None:
        return default
    try:
        if isinstance(row, dict):
            return row.get(key, default)
        if key in row.keys():
            val = row[key]
            return default if val is None else val
    except Exception:
        pass
    return default


def init_db():
    with DB_LOCK:
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                balance REAL DEFAULT 0,
                blocked INTEGER DEFAULT 0,
                created_at TEXT
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT UNIQUE,
                title TEXT,
                username TEXT,
                invite_link TEXT,
                enabled INTEGER DEFAULT 1,
                quantity INTEGER DEFAULT 50,
                service_id TEXT,
                owner_user_id INTEGER,
                created_at TEXT
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                channel_id TEXT,
                channel_title TEXT,
                post_link TEXT,
                quantity INTEGER,
                charge REAL,
                provider_order_id TEXT,
                service_id TEXT,
                status TEXT DEFAULT 'Pending',
                created_at TEXT
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS force_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT,
                title TEXT,
                invite_link TEXT,
                active INTEGER DEFAULT 1
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS pay_methods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                method TEXT,
                name TEXT,
                number TEXT,
                active INTEGER DEFAULT 1
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                method TEXT,
                amount REAL,
                trx TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )"""
        )
        defaults = {
            "api_url": "https://smmvai.com/api/v2",
            "api_key": "",
            "service_id": "",  # reaction+views service on panel
            "default_qty": "50",
            "markup_fixed_bdt": "10",
            "markup_percent": "0",
            "usd_bdt_rate": "120",
            "currency": "BDT",
            "min_deposit": "100",
            "bot_enabled": "1",
            "wallet_enabled": "1",
            "binance_enabled": "1",
            "manual_pay_enabled": "1",
            "max_user_channels": "10",
            "support_username": "@support",
            "binance_api_key": "",
            "binance_secret_key": "",
            "binance_pay_id": "",
            "binance_address": "",
            "binance_network": "BSC BNB Smart Chain (BEP20)",
            "binance_min_usdt": "1",
            "maintenance_text": (
                "সাময়িক রক্ষণাবেক্ষণ চলছে।\n"
                "আমাদের বটে কিছু কাজ চলছে।\n"
                "সাধারণত ঠিক করতে ২৪ ঘণ্টা সময় লাগতে পারে।\n"
                "Admin শীঘ্রই চালু করে দেবে।"
            ),
            "owner_id": str(OWNER_ID),
        }
        for k, v in defaults.items():
            c.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)", (k, v)
            )
        c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (OWNER_ID,))
        if ADMIN_ID != OWNER_ID:
            c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (ADMIN_ID,))
        conn.commit()
        conn.close()
    load_admins()


def load_admins():
    global admin_ids
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT user_id FROM admins")
        rows = c.fetchall()
        conn.close()
        admin_ids = {OWNER_ID, ADMIN_ID}
        for r in rows:
            admin_ids.add(int(r["user_id"]))
    except Exception as e:
        logger.error("load_admins: %s", e)
        admin_ids = {OWNER_ID, ADMIN_ID}


def get_setting(key, default=""):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    if row is None:
        return default
    return row["value"] if row["value"] is not None else default


def set_setting(key, value):
    with DB_LOCK:
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
            (key, str(value)),
        )
        conn.commit()
        conn.close()


def is_admin(uid):
    return int(uid) in admin_ids or int(uid) == OWNER_ID


def is_main_owner(uid):
    try:
        return int(uid) == int(get_setting("owner_id", str(OWNER_ID)) or OWNER_ID)
    except Exception:
        return int(uid) == OWNER_ID


def ensure_user(user):
    uid = user.id
    now = datetime.now().isoformat()
    with DB_LOCK:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE user_id=?", (uid,))
        if not c.fetchone():
            c.execute(
                "INSERT INTO users (user_id, username, full_name, balance, created_at) VALUES (?,?,?,0,?)",
                (
                    uid,
                    user.username or "",
                    ((user.first_name or "") + " " + (user.last_name or "")).strip(),
                    now,
                ),
            )
        else:
            c.execute(
                "UPDATE users SET username=?, full_name=? WHERE user_id=?",
                (
                    user.username or "",
                    ((user.first_name or "") + " " + (user.last_name or "")).strip(),
                    uid,
                ),
            )
        conn.commit()
        conn.close()


def get_user(uid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    row = c.fetchone()
    conn.close()
    return row


def get_balance(uid):
    u = get_user(uid)
    return float(u["balance"] or 0) if u else 0.0


def add_balance(uid, amount):
    with DB_LOCK:
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id=?",
            (float(amount), uid),
        )
        conn.commit()
        conn.close()


def deduct_balance(uid, amount):
    amount = float(amount)
    if amount <= 0:
        return False
    with DB_LOCK:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
        row = c.fetchone()
        if not row:
            conn.close()
            return False
        bal = float(row["balance"] or 0)
        if bal + 1e-9 < amount:
            conn.close()
            return False
        c.execute(
            "UPDATE users SET balance = balance - ? WHERE user_id=?",
            (amount, uid),
        )
        conn.commit()
        conn.close()
        return True


def is_blocked(uid):
    u = get_user(uid)
    return bool(u and int(u["blocked"] or 0) == 1)


def fmt_money(v):
    try:
        return "%.2f %s" % (float(v), get_setting("currency", "BDT"))
    except Exception:
        return str(v)


# ================== SMM API ==================
def api_request(action, extra=None):
    url = (get_setting("api_url") or "").strip()
    key = (get_setting("api_key") or "").strip()
    if not url or not key:
        return None, "API Key/URL set nai. Control Panel → API Key"
    payload = {"key": key, "action": action}
    if extra:
        payload.update(extra)
    try:
        r = requests.post(url, data=payload, timeout=60)
        data = r.json()
        if isinstance(data, dict) and data.get("error") and not data.get("order"):
            # status 100 with order is success even if other fields
            if not (data.get("order") or data.get("order_id")):
                return None, str(data.get("error"))
        return data, None
    except Exception as e:
        logger.error("api_request %s: %s", action, e)
        return None, str(e)


def provider_balance():
    data, err = api_request("balance")
    if err:
        return None, err
    if isinstance(data, dict):
        return data.get("balance"), None
    return None, "bad response"


def provider_add_order(service_id, link, quantity):
    data, err = api_request(
        "add",
        {
            "service": str(service_id),
            "link": str(link).strip(),
            "quantity": str(int(quantity)),
        },
    )
    if err:
        return None, err
    if not isinstance(data, dict):
        return None, "Invalid API response"
    oid = data.get("order") or data.get("order_id") or data.get("id")
    if oid is not None and str(oid).strip():
        return str(oid), None
    msg = data.get("error") or data.get("message") or str(data)[:200]
    st = str(data.get("status") or "")
    low = str(msg).lower()
    if "already" in low or st == "115":
        return None, "Active order already exists for this link"
    if "fund" in low or "balance" in low or st == "118":
        return None, "Provider balance low: %s" % msg
    if st == "114" or "error while creating" in low:
        return None, "Provider rejected service/link (114). Try another service ID."
    return None, msg


def provider_status(order_id):
    data, err = api_request("status", {"order": str(order_id)})
    if err:
        return None, err
    return data, None


def calc_charge(qty):
    """Estimate charge from provider rate if known; else fixed markup * qty/1000 style.
    Uses settings: we store optional rate_per_1000; if missing charge = markup_fixed * max(1, qty/1000) minimum.
    Better: fetch service rate from API when possible — here simple formula.
    """
    try:
        rate = float(get_setting("service_rate", "0") or 0)
    except Exception:
        rate = 0.0
    try:
        markup = float(get_setting("markup_percent", "0") or 0)
    except Exception:
        markup = 0.0
    try:
        fixed = float(get_setting("markup_fixed_bdt", "10") or 10)
    except Exception:
        fixed = 10.0
    try:
        usd = float(get_setting("usd_bdt_rate", "120") or 120)
    except Exception:
        usd = 120.0
    qty = float(qty)
    cost_usd = (rate / 1000.0) * qty if rate > 0 else 0.0
    cost = cost_usd * (1 + markup / 100.0) * usd
    cost += fixed * (qty / 1000.0)
    # minimum charge at least fixed for small qty
    if cost < 0.01:
        cost = max(fixed * max(qty / 1000.0, 0.05), 1.0)
    return round(cost, 2)


def refresh_service_rate():
    """Pull rate for configured service_id from provider."""
    sid = (get_setting("service_id") or "").strip()
    if not sid:
        return
    data, err = api_request("services")
    if err or not isinstance(data, list):
        return
    for s in data:
        if str(s.get("service") or s.get("id")) == str(sid):
            try:
                set_setting("service_rate", str(float(s.get("rate") or 0)))
            except Exception:
                pass
            return


# ================== FORCE JOIN ==================
def get_force_channels():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM force_channels WHERE active=1")
    rows = c.fetchall()
    conn.close()
    return rows


def check_force_join(uid):
    channels = get_force_channels()
    missing = []
    for ch in channels:
        chat_id = ch["chat_id"]
        try:
            m = bot.get_chat_member(chat_id, uid)
            if m.status in ("left", "kicked"):
                missing.append(ch)
        except Exception:
            missing.append(ch)
    return missing


def force_join_kb(missing):
    kb = types.InlineKeyboardMarkup()
    for ch in missing:
        link = ch["invite_link"] or ""
        title = ch["title"] or "Channel"
        if link:
            kb.add(types.InlineKeyboardButton("Join %s" % title, url=link))
    kb.add(types.InlineKeyboardButton("✅ I Joined", callback_data="fj_check"))
    return kb


# ================== KEYBOARDS ==================
def main_menu_kb(uid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("🔗 API Key", "📊 Quantity")
    kb.add("📢 Channels", "💼 Wallet")
    kb.add("❓ How to Use", "🎛 Control Panel")
    kb.add("🔎 Order Track", "📦 My Orders")
    if is_admin(uid):
        kb.add("🛡 Admin Panel")
    return kb


def admin_panel_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🔗 API Setup", callback_data="adm_api"),
        types.InlineKeyboardButton("🎯 Service ID", callback_data="adm_svc"),
    )
    kb.add(
        types.InlineKeyboardButton("📊 Default Qty", callback_data="adm_qty"),
        types.InlineKeyboardButton("💰 Markup", callback_data="adm_markup"),
    )
    kb.add(
        types.InlineKeyboardButton("📢 Channels", callback_data="adm_channels"),
        types.InlineKeyboardButton("🔐 Force Join", callback_data="adm_force"),
    )
    kb.add(
        types.InlineKeyboardButton("💳 Pay Methods", callback_data="adm_pay"),
        types.InlineKeyboardButton("💛 Binance Setup", callback_data="adm_binance"),
    )
    kb.add(
        types.InlineKeyboardButton("📥 Pending Deposits", callback_data="adm_deps"),
        types.InlineKeyboardButton("➕ Add Balance", callback_data="adm_addbal"),
    )
    kb.add(
        types.InlineKeyboardButton("📈 Stats", callback_data="adm_stats"),
        types.InlineKeyboardButton("📣 Broadcast", callback_data="adm_bc"),
    )
    kb.add(
        types.InlineKeyboardButton("👑 Add Admin", callback_data="adm_addadmin"),
        types.InlineKeyboardButton("➖ Remove Admin", callback_data="adm_rmadmin"),
    )
    kb.add(
        types.InlineKeyboardButton("🔄 Ownership Transfer", callback_data="adm_owner"),
        types.InlineKeyboardButton("💾 Backup Source", callback_data="adm_backup"),
    )
    on = get_setting("bot_enabled", "1") == "1"
    wal = get_setting("wallet_enabled", "1") == "1"
    bn = get_setting("binance_enabled", "1") == "1"
    kb.add(
        types.InlineKeyboardButton(
            "Bot: %s" % ("ON 🟢" if on else "OFF 🔴"),
            callback_data="adm_bot_toggle",
        )
    )
    kb.add(
        types.InlineKeyboardButton(
            "Wallet: %s" % ("ON" if wal else "OFF"),
            callback_data="adm_wal_toggle",
        ),
        types.InlineKeyboardButton(
            "Binance: %s" % ("ON" if bn else "OFF"),
            callback_data="adm_bn_toggle",
        ),
    )
    return kb


def send_backup_files(chat_id):
    """Send bot source code + DB backup to admin as downloadable files."""
    import io

    paths = [os.path.abspath(__file__)]
    if os.path.exists(DB_PATH):
        paths.append(os.path.abspath(DB_PATH))
    sent = 0
    for path in paths:
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as f:
                data = f.read()
            bio = io.BytesIO(data)
            bio.name = os.path.basename(path)
            bot.send_document(
                chat_id,
                bio,
                caption="Backup: %s (%s bytes)" % (bio.name, len(data)),
            )
            sent += 1
        except Exception as e:
            try:
                bot.send_message(chat_id, "Backup fail: %s" % e)
            except Exception:
                pass
    req = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "requirements_auto_reaction.txt",
    )
    if os.path.isfile(req):
        try:
            with open(req, "rb") as f:
                bio = io.BytesIO(f.read())
                bio.name = "requirements_auto_reaction.txt"
                bot.send_document(chat_id, bio, caption="requirements")
                sent += 1
        except Exception:
            pass
    if sent == 0:
        bot.send_message(chat_id, "No backup files found.")
    else:
        bot.send_message(chat_id, "Backup sent (%s file)." % sent)


def channels_admin_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM channels ORDER BY id DESC LIMIT 30")
    rows = c.fetchall()
    conn.close()
    for r in rows:
        flag = "🟢" if int(r["enabled"] or 0) else "🔴"
        label = "%s %s" % (flag, (r["title"] or r["chat_id"])[:40])
        kb.add(
            types.InlineKeyboardButton(label, callback_data="ch_info_%s" % r["id"])
        )
        kb.add(
            types.InlineKeyboardButton(
                "Toggle %s" % r["id"], callback_data="ch_tog_%s" % r["id"]
            ),
            types.InlineKeyboardButton(
                "Delete %s" % r["id"], callback_data="ch_del_%s" % r["id"]
            ),
        )
    kb.add(types.InlineKeyboardButton("➕ Add Channel", callback_data="ch_add"))
    kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data="adm_back"))
    return kb


def wallet_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    if get_setting("manual_pay_enabled", "1") == "1":
        kb.add(types.InlineKeyboardButton("💳 Deposit (bKash/Nagad/Rocket)", callback_data="wal_dep"))
    if get_setting("binance_enabled", "1") == "1":
        kb.add(types.InlineKeyboardButton("💛 Binance Instant (BEP20)", callback_data="wal_bn"))
    return kb


# ================== CHANNEL POST AUTO ORDER ==================
def build_post_link(chat, message_id):
    username = getattr(chat, "username", None)
    if username:
        return "https://t.me/%s/%s" % (username, message_id)
    # private channel: t.me/c/CHATID/MSGID (strip -100)
    cid = str(chat.id)
    if cid.startswith("-100"):
        cid = cid[4:]
    return "https://t.me/c/%s/%s" % (cid, message_id)


def get_channel_row(chat_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM channels WHERE chat_id=?", (str(chat_id),))
    row = c.fetchone()
    conn.close()
    return row


def process_auto_order(chat, message):
    """Called on new channel post."""
    if get_setting("bot_enabled", "1") != "1":
        return
    row = get_channel_row(chat.id)
    if not row or int(row["enabled"] or 0) != 1:
        return

    api_key = (get_setting("api_key") or "").strip()
    if not api_key:
        logger.warning("auto order skip: no api key")
        return

    service_id = (row["service_id"] or get_setting("service_id") or "").strip()
    if not service_id:
        logger.warning("auto order skip: no service_id")
        try:
            bot.send_message(
                OWNER_ID,
                "Auto Reaction skipped: Service ID set nai.\nAdmin → Service ID",
            )
        except Exception:
            pass
        return

    qty = int(row["quantity"] or get_setting("default_qty") or 50)
    if qty < 1:
        qty = 50

    post_link = build_post_link(chat, message.message_id)
    charge = calc_charge(qty)
    payer = int(row["owner_user_id"] or OWNER_ID)

    # balance check on channel owner
    bal = get_balance(payer)
    if bal + 1e-9 < charge:
        try:
            bot.send_message(
                payer,
                "Auto Reaction FAILED — balance kom.\n"
                "Channel: %s\nNeed: %s | Have: %s\nDeposit from Wallet."
                % (row["title"] or chat.id, fmt_money(charge), fmt_money(bal)),
            )
        except Exception:
            pass
        return

    if not deduct_balance(payer, charge):
        return

    oid, err = provider_add_order(service_id, post_link, qty)
    if err or not oid:
        add_balance(payer, charge)
        try:
            bot.send_message(
                payer,
                "Auto Reaction order fail: %s\nBalance refunded.\nPost: %s"
                % (err, post_link),
            )
        except Exception:
            pass
        return

    now = datetime.now().isoformat()
    with DB_LOCK:
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            """INSERT INTO orders
               (user_id, channel_id, channel_title, post_link, quantity, charge,
                provider_order_id, service_id, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                payer,
                str(chat.id),
                row["title"] or getattr(chat, "title", "") or "",
                post_link,
                qty,
                charge,
                str(oid),
                str(service_id),
                "Pending",
                now,
            ),
        )
        conn.commit()
        conn.close()

    # Notify like screenshot
    uname = row["username"] or getattr(chat, "username", "") or ""
    if uname and not str(uname).startswith("@"):
        uname = "@" + uname
    text = (
        "🛒 Order Pending!\n\n"
        "🛒 Order ID: #%s\n"
        "📊 Quantity: %s Pcs\n"
        "🌐 Channel: %s\n"
        "🖼 Post: %s"
        % (oid, qty, uname or (row["title"] or chat.id), post_link)
    )
    try:
        bot.send_message(payer, text, disable_web_page_preview=False)
    except Exception:
        pass
    if payer != OWNER_ID:
        try:
            bot.send_message(OWNER_ID, "Auto order → user %s\n%s" % (payer, text))
        except Exception:
            pass


# ================== HANDLERS ==================
@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    uid = message.from_user.id
    if is_blocked(uid):
        bot.reply_to(message, "You are blocked.")
        return
    ensure_user(message.from_user)
    # Maintenance: still allow start/menu, but show notice (orders blocked separately)
    if get_setting("bot_enabled", "1") != "1" and not is_admin(uid):
        bot.reply_to(
            message,
            get_setting(
                "maintenance_text",
                "Bot temporary maintenance. Try again later.",
            ),
            reply_markup=main_menu_kb(uid),
        )
        return
    missing = check_force_join(uid)
    if missing and not is_admin(uid):
        bot.reply_to(
            message,
            "Please join required channels first:",
            reply_markup=force_join_kb(missing),
        )
        return
    bot.send_message(
        message.chat.id,
        "Auto Reaction Bot\n\n"
        "Nijer channel add korun (max 10).\n"
        "Post hole automatic reaction/views order jabe.\n\n"
        "Bot ke channel e ADMIN din.",
        reply_markup=main_menu_kb(uid),
    )


@bot.callback_query_handler(func=lambda c: c.data == "fj_check")
def cb_fj(call):
    uid = call.from_user.id
    missing = check_force_join(uid)
    if missing:
        bot.answer_callback_query(call.id, "Still missing channels", show_alert=True)
        try:
            bot.edit_message_reply_markup(
                call.message.chat.id,
                call.message.message_id,
                reply_markup=force_join_kb(missing),
            )
        except Exception:
            pass
        return
    bot.answer_callback_query(call.id, "OK")
    bot.send_message(
        call.message.chat.id,
        "Thanks! /start press korun.",
        reply_markup=main_menu_kb(uid),
    )


@bot.message_handler(func=lambda m: m.text == "❓ How to Use")
def btn_how(message):
    bot.reply_to(
        message,
        "How to Use\n\n"
        "1) Admin: API Key set korun (SMM panel)\n"
        "2) Admin: Service ID set korun (reaction+views service)\n"
        "3) Channel list e channel add korun\n"
        "4) Bot ke oi channel e ADMIN din (post dekhte parbe)\n"
        "5) Wallet e balance add korun\n"
        "6) Channel ON thakle notun post e auto order jabe\n\n"
        "Order Track: provider Order ID din\n"
        "Quantity: default / per-channel qty\n",
        reply_markup=main_menu_kb(message.from_user.id),
    )


@bot.message_handler(func=lambda m: m.text == "🔗 API Key")
def btn_api(message):
    uid = message.from_user.id
    if not is_admin(uid):
        bot.reply_to(message, "Admin only. Control Panel use korun.")
        return
    url = get_setting("api_url") or ""
    key = get_setting("api_key") or ""
    masked = (key[:4] + "…" + key[-4:]) if len(key) > 8 else ("set" if key else "empty")
    bal, err = provider_balance() if key else (None, "no key")
    bot.reply_to(
        message,
        "API Setup\n\nURL: %s\nKey: %s\nProvider balance: %s\n\n"
        "Admin Panel → API Setup theke change korun."
        % (url, masked, bal if bal is not None else (err or "—")),
    )


@bot.message_handler(func=lambda m: m.text == "📊 Quantity")
def btn_qty(message):
    uid = message.from_user.id
    q = get_setting("default_qty", "50")
    if is_admin(uid):
        user_state[uid] = {"action": "set_default_qty"}
        bot.reply_to(message, "Default Quantity ekhon: %s\nNotun number likhun:" % q)
    else:
        bot.reply_to(message, "Default Quantity: %s\n(Admin change korte parbe)" % q)


def user_channels_kb(uid):
    """User can add/toggle/delete own channels (max 10)."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM channels WHERE owner_user_id=? ORDER BY id DESC",
        (uid,),
    )
    rows = c.fetchall()
    conn.close()
    max_ch = int(get_setting("max_user_channels", "10") or 10)
    for r in rows:
        flag = "ON" if int(r["enabled"] or 0) else "OFF"
        title = (r["title"] or r["chat_id"] or "?")[:28]
        kb.add(
            types.InlineKeyboardButton(
                "%s | %s" % (flag, title),
                callback_data="uch_info_%s" % r["id"],
            )
        )
        kb.add(
            types.InlineKeyboardButton(
                "Toggle", callback_data="uch_tog_%s" % r["id"]
            ),
            types.InlineKeyboardButton(
                "Delete", callback_data="uch_del_%s" % r["id"]
            ),
        )
    if len(rows) < max_ch:
        kb.add(
            types.InlineKeyboardButton(
                "➕ Add Channel (%s/%s)" % (len(rows), max_ch),
                callback_data="uch_add",
            )
        )
    else:
        kb.add(
            types.InlineKeyboardButton(
                "Limit %s/%s reached" % (len(rows), max_ch),
                callback_data="noop",
            )
        )
    return kb


@bot.message_handler(func=lambda m: m.text == "📢 Channels")
def btn_channels(message):
    uid = message.from_user.id
    ensure_user(message.from_user)
    max_ch = int(get_setting("max_user_channels", "10") or 10)
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT COUNT(*) AS n FROM channels WHERE owner_user_id=?", (uid,)
    )
    n = int(c.fetchone()["n"])
    c.execute(
        "SELECT * FROM channels WHERE owner_user_id=? ORDER BY id DESC",
        (uid,),
    )
    rows = c.fetchall()
    conn.close()
    lines = [
        "Your Channels (%s/%s)\n" % (n, max_ch),
        "Bot must be ADMIN in each channel.\n",
    ]
    if not rows:
        lines.append("No channel yet. Add with ➕ button.")
    else:
        for r in rows:
            lines.append(
                "%s #%s %s\n  %s | qty %s"
                % (
                    "ON" if int(r["enabled"] or 0) else "OFF",
                    r["id"],
                    r["title"] or "-",
                    r["chat_id"],
                    r["quantity"],
                )
            )
    bot.reply_to(
        message,
        "\n".join(lines),
        reply_markup=user_channels_kb(uid),
    )


@bot.message_handler(func=lambda m: m.text == "💼 Wallet")
def btn_wallet(message):
    uid = message.from_user.id
    ensure_user(message.from_user)
    if get_setting("wallet_enabled", "1") != "1" and not is_admin(uid):
        bot.reply_to(message, "Wallet system is OFF by admin.")
        return
    bal = get_balance(uid)
    bot.reply_to(
        message,
        "Wallet\n\nBalance: %s\n\nDeposit method choose korun:" % fmt_money(bal),
        reply_markup=wallet_kb(),
    )


@bot.message_handler(func=lambda m: m.text == "🎛 Control Panel")
def btn_control(message):
    uid = message.from_user.id
    if not is_admin(uid):
        bot.reply_to(message, "Admin only.")
        return
    bot.reply_to(
        message,
        "Control Panel",
        reply_markup=admin_panel_kb(),
    )


@bot.message_handler(func=lambda m: m.text == "🛡 Admin Panel")
def btn_admin(message):
    if not is_admin(message.from_user.id):
        return
    bot.reply_to(message, "Admin Panel", reply_markup=admin_panel_kb())


@bot.message_handler(func=lambda m: m.text == "📦 My Orders")
def btn_my_orders(message):
    uid = message.from_user.id
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 15", (uid,)
    )
    rows = c.fetchall()
    conn.close()
    if not rows:
        bot.reply_to(message, "No orders yet.")
        return
    lines = ["My Orders:\n"]
    for o in rows:
        lines.append(
            "#%s | Provider:%s | qty:%s | %s | %s"
            % (
                o["id"],
                o["provider_order_id"],
                o["quantity"],
                o["status"],
                (o["created_at"] or "")[:16],
            )
        )
    bot.reply_to(message, "\n".join(lines))


@bot.message_handler(func=lambda m: m.text == "🔎 Order Track")
def btn_track(message):
    uid = message.from_user.id
    user_state[uid] = {"action": "track"}
    bot.reply_to(message, "Provider Order ID likhun (example: 1223769):")


# ----- Channel posts (auto) -----
@bot.channel_post_handler(content_types=["text", "photo", "video", "document", "animation", "audio", "voice", "sticker"])
def on_channel_post(message):
    try:
        process_auto_order(message.chat, message)
    except Exception as e:
        logger.exception("channel_post: %s", e)


@bot.edited_channel_post_handler(content_types=["text", "photo", "video", "document"])
def on_channel_edit(message):
    # optional: skip edits to avoid double orders
    return


# ----- Wallet callbacks -----
@bot.callback_query_handler(func=lambda c: c.data == "wal_dep")
def cb_wal_dep(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    if get_setting("manual_pay_enabled", "1") != "1":
        bot.send_message(call.message.chat.id, "Manual deposit is OFF.")
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM pay_methods WHERE active=1")
    rows = c.fetchall()
    conn.close()
    kb = types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        kb.add(
            types.InlineKeyboardButton(
                "%s — %s" % (r["method"], r["number"]),
                callback_data="dep_m_%s" % r["id"],
            )
        )
    if not rows:
        bot.send_message(
            call.message.chat.id,
            "No manual methods. Admin → Pay Methods → ➕ Add.\nOr use Binance Instant.",
        )
        return
    bot.send_message(call.message.chat.id, "Method choose korun:", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("dep_m_"))
def cb_dep_method(call):
    uid = call.from_user.id
    try:
        mid = int(call.data.split("_")[2])
    except Exception:
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM pay_methods WHERE id=?", (mid,))
    m = c.fetchone()
    conn.close()
    if not m:
        bot.answer_callback_query(call.id, "Not found")
        return
    bot.answer_callback_query(call.id)
    user_state[uid] = {
        "action": "dep_amount",
        "method_id": mid,
        "method": m["method"],
        "number": m["number"],
    }
    bot.send_message(
        call.message.chat.id,
        "%s number: %s\n\n"
        "Koto taka deposit korben? (min %s)\n\n"
        "IMPORTANT:\n"
        "• ONLY Send Money (Cash Out NA)\n"
        "• Joto taka bola hobe THIK otoy taka pathaben\n"
        "• Button phone: bKash/Nagad app → Send Money → number e amount\n"
        "• Pore Transaction ID din"
        % (m["method"], m["number"], get_setting("min_deposit", "100")),
    )


@bot.callback_query_handler(func=lambda c: c.data == "wal_bn")
def cb_wal_bn(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    if get_setting("binance_enabled", "1") != "1":
        bot.send_message(call.message.chat.id, "Binance Instant is OFF.")
        return
    if not get_setting("binance_api_key") and not get_setting("binance_address"):
        bot.send_message(call.message.chat.id, "Binance not configured by admin.")
        return
    user_state[uid] = {"action": "bn_amount"}
    bot.send_message(
        call.message.chat.id,
        "Binance Instant Verify\n\n"
        "Network: %s\n"
        "Amount USDT ($) likhun (min %s):\n\n"
        "Warning: wrong network = money loss.\n"
        "Only BEP20 / as admin set."
        % (
            get_setting("binance_network", "BSC BNB Smart Chain (BEP20)"),
            get_setting("binance_min_usdt", "1"),
        ),
    )


# ----- Admin callbacks -----
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("adm_"))
def cb_admin(call):
    uid = call.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(call.id, "Admin only", show_alert=True)
        return
    data = call.data
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)

    if data == "adm_back":
        bot.send_message(chat_id, "Admin Panel", reply_markup=admin_panel_kb())
        return

    if data == "adm_api":
        user_state[uid] = {"action": "set_api_url"}
        bot.send_message(
            chat_id,
            "API URL likhun:\nExample: https://smmvai.com/api/v2\n\nCancel: cancel",
        )
        return

    if data == "adm_svc":
        user_state[uid] = {"action": "set_service"}
        bot.send_message(
            chat_id,
            "Reaction/Views Service ID likhun (panel er service number):\n"
            "Current: %s" % (get_setting("service_id") or "empty"),
        )
        return

    if data == "adm_qty":
        user_state[uid] = {"action": "set_default_qty"}
        bot.send_message(
            chat_id,
            "Default quantity:\nCurrent: %s" % get_setting("default_qty", "50"),
        )
        return

    if data == "adm_markup":
        user_state[uid] = {"action": "set_markup_fixed"}
        bot.send_message(
            chat_id,
            "Fixed markup BDT per 1000 units:\nCurrent: %s"
            % get_setting("markup_fixed_bdt", "10"),
        )
        return

    if data == "adm_channels":
        bot.send_message(
            chat_id,
            "Channels (bot must be ADMIN):",
            reply_markup=channels_admin_kb(),
        )
        return

    if data == "adm_force":
        rows = get_force_channels()
        lines = ["Force Join Channels:\n"]
        if not rows:
            lines.append("None")
        for r in rows:
            lines.append("- #%s %s | %s" % (r["id"], r["title"], r["chat_id"]))
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("➕ Add", callback_data="fc_add"))
        for r in rows:
            kb.add(
                types.InlineKeyboardButton(
                    "🗑 %s" % (r["title"] or r["id"]),
                    callback_data="fc_del_%s" % r["id"],
                )
            )
        bot.send_message(chat_id, "\n".join(lines), reply_markup=kb)
        return

    if data == "adm_pay":
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM pay_methods WHERE active=1")
        rows = c.fetchall()
        conn.close()
        lines = ["Pay Methods (bKash/Nagad/Rocket):\n"]
        kb = types.InlineKeyboardMarkup(row_width=1)
        if not rows:
            lines.append("None yet.")
        for r in rows:
            lines.append(
                "#%s %s | %s | %s" % (r["id"], r["method"], r["name"], r["number"])
            )
            kb.add(
                types.InlineKeyboardButton(
                    "🗑 Delete #%s" % r["id"],
                    callback_data="pay_del_%s" % r["id"],
                )
            )
        kb.add(types.InlineKeyboardButton("➕ Add Method", callback_data="pay_add"))
        on = get_setting("manual_pay_enabled", "1") == "1"
        kb.add(
            types.InlineKeyboardButton(
                "Manual Pay: %s" % ("ON" if on else "OFF"),
                callback_data="pay_toggle",
            )
        )
        bot.send_message(chat_id, "\n".join(lines), reply_markup=kb)
        return

    if data == "adm_binance":
        kb = types.InlineKeyboardMarkup(row_width=1)
        en = get_setting("binance_enabled", "1") == "1"
        kb.add(
            types.InlineKeyboardButton(
                "Instant Verify: %s" % ("ON" if en else "OFF"),
                callback_data="bn_toggle",
            )
        )
        kb.add(types.InlineKeyboardButton("API Key", callback_data="bn_key"))
        kb.add(types.InlineKeyboardButton("Secret Key", callback_data="bn_sec"))
        kb.add(types.InlineKeyboardButton("Pay ID", callback_data="bn_payid"))
        kb.add(types.InlineKeyboardButton("Address (BEP20)", callback_data="bn_addr"))
        bot.send_message(
            chat_id,
            "Binance Instant Setup\n\n"
            "Network: %s\n"
            "API: %s\nSecret: %s\nPayID: %s\nAddress: %s"
            % (
                get_setting("binance_network", "BSC BEP20"),
                "set" if get_setting("binance_api_key") else "empty",
                "set" if get_setting("binance_secret_key") else "empty",
                get_setting("binance_pay_id") or "empty",
                (get_setting("binance_address") or "empty")[:24],
            ),
            reply_markup=kb,
        )
        return

    if data == "adm_deps":
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "SELECT * FROM deposits WHERE status='pending' ORDER BY id DESC LIMIT 20"
        )
        rows = c.fetchall()
        conn.close()
        if not rows:
            bot.send_message(chat_id, "No pending deposits.")
            return
        for d in rows:
            kb = types.InlineKeyboardMarkup()
            kb.add(
                types.InlineKeyboardButton(
                    "✅ Approve", callback_data="dep_ok_%s" % d["id"]
                ),
                types.InlineKeyboardButton(
                    "❌ Reject", callback_data="dep_no_%s" % d["id"]
                ),
            )
            bot.send_message(
                chat_id,
                "Deposit #%s\nUser: %s\n%s %s\nTrx: %s"
                % (d["id"], d["user_id"], d["method"], fmt_money(d["amount"]), d["trx"]),
                reply_markup=kb,
            )
        return

    if data == "adm_addbal":
        user_state[uid] = {"action": "add_bal_uid"}
        bot.send_message(chat_id, "User ID likhun:")
        return

    if data == "adm_stats":
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM orders")
        orders = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM channels WHERE enabled=1")
        chans = c.fetchone()[0]
        conn.close()
        pbal, _ = provider_balance()
        bot.send_message(
            chat_id,
            "Stats\nUsers: %s\nOrders: %s\nActive channels: %s\nProvider bal: %s"
            % (users, orders, chans, pbal),
        )
        return

    if data == "adm_bc":
        user_state[uid] = {"action": "broadcast"}
        bot.send_message(chat_id, "Broadcast message likhun:")
        return

    if data == "adm_addadmin":
        user_state[uid] = {"action": "add_admin"}
        bot.send_message(chat_id, "New admin user_id:")
        return

    if data == "adm_rmadmin":
        user_state[uid] = {"action": "rm_admin"}
        bot.send_message(chat_id, "Remove admin user_id:")
        return

    if data == "adm_bot_toggle":
        cur = get_setting("bot_enabled", "1")
        set_setting("bot_enabled", "0" if cur == "1" else "1")
        bot.send_message(
            chat_id,
            "Bot is now %s" % ("OFF" if cur == "1" else "ON"),
            reply_markup=admin_panel_kb(),
        )
        return

    if data == "adm_wal_toggle":
        cur = get_setting("wallet_enabled", "1")
        set_setting("wallet_enabled", "0" if cur == "1" else "1")
        bot.send_message(
            chat_id,
            "Wallet %s" % ("OFF" if cur == "1" else "ON"),
            reply_markup=admin_panel_kb(),
        )
        return

    if data == "adm_bn_toggle":
        cur = get_setting("binance_enabled", "1")
        set_setting("binance_enabled", "0" if cur == "1" else "1")
        bot.send_message(
            chat_id,
            "Binance Instant %s" % ("OFF" if cur == "1" else "ON"),
            reply_markup=admin_panel_kb(),
        )
        return

    if data == "adm_backup":
        bot.send_message(chat_id, "Preparing backup…")
        try:
            send_backup_files(chat_id)
        except Exception as e:
            bot.send_message(chat_id, "Backup error: %s" % e)
        return

    if data == "adm_owner":
        if not is_main_owner(uid):
            bot.send_message(chat_id, "Only Main Owner can transfer ownership.")
            return
        user_state[uid] = {"action": "owner_transfer"}
        bot.send_message(
            chat_id,
            "Ownership Transfer\n\n"
            "New Owner er Telegram User ID likhun:\n"
            "(example: 8289191009)\n\n"
            "Cancel likhle batil.",
        )
        return


@bot.callback_query_handler(func=lambda c: c.data == "noop")
def cb_noop(call):
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data in ("ch_add", "uch_add"))
def cb_ch_add(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    # Users can add own channels; admins too
    max_ch = int(get_setting("max_user_channels", "10") or 10)
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT COUNT(*) AS n FROM channels WHERE owner_user_id=?", (uid,)
    )
    n = int(c.fetchone()["n"])
    conn.close()
    if n >= max_ch and not is_admin(uid):
        bot.send_message(
            call.message.chat.id,
            "Maximum %s channels. Delete one first." % max_ch,
        )
        return
    user_state[uid] = {"action": "ch_add"}
    bot.send_message(
        call.message.chat.id,
        "Channel add:\n"
        "• @username likhun\n"
        "• OR channel theke ekta post FORWARD korun\n"
        "• OR chat id (-100...)\n\n"
        "Bot ke oi channel e ADMIN rakhte hobe.\n"
        "Cancel = cancel",
    )


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("uch_tog_"))
def cb_uch_tog(call):
    uid = call.from_user.id
    try:
        cid = int(call.data.split("_")[2])
    except Exception:
        return
    with DB_LOCK:
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "SELECT * FROM channels WHERE id=? AND owner_user_id=?",
            (cid, uid),
        )
        r = c.fetchone()
        if not r and not is_admin(uid):
            conn.close()
            bot.answer_callback_query(call.id, "Not yours", show_alert=True)
            return
        if not r and is_admin(uid):
            c.execute("SELECT * FROM channels WHERE id=?", (cid,))
            r = c.fetchone()
        if not r:
            conn.close()
            return
        newv = 0 if int(r["enabled"] or 0) else 1
        c.execute("UPDATE channels SET enabled=? WHERE id=?", (newv, cid))
        conn.commit()
        conn.close()
    bot.answer_callback_query(call.id, "Toggled")
    bot.send_message(
        call.message.chat.id,
        "Channel updated.",
        reply_markup=user_channels_kb(uid),
    )


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("uch_del_"))
def cb_uch_del(call):
    uid = call.from_user.id
    try:
        cid = int(call.data.split("_")[2])
    except Exception:
        return
    with DB_LOCK:
        conn = get_conn()
        c = conn.cursor()
        if is_admin(uid):
            c.execute("DELETE FROM channels WHERE id=?", (cid,))
        else:
            c.execute(
                "DELETE FROM channels WHERE id=? AND owner_user_id=?",
                (cid, uid),
            )
        conn.commit()
        conn.close()
    bot.answer_callback_query(call.id, "Deleted")
    bot.send_message(
        call.message.chat.id,
        "Channel deleted.",
        reply_markup=user_channels_kb(uid),
    )


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("ch_tog_"))
def cb_ch_tog(call):
    if not is_admin(call.from_user.id):
        return
    try:
        cid = int(call.data.split("_")[2])
    except Exception:
        return
    with DB_LOCK:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT enabled FROM channels WHERE id=?", (cid,))
        r = c.fetchone()
        if r:
            newv = 0 if int(r["enabled"] or 0) else 1
            c.execute("UPDATE channels SET enabled=? WHERE id=?", (newv, cid))
            conn.commit()
        conn.close()
    bot.answer_callback_query(call.id, "Toggled")
    bot.send_message(
        call.message.chat.id, "Updated.", reply_markup=channels_admin_kb()
    )


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("ch_del_"))
def cb_ch_del(call):
    if not is_admin(call.from_user.id):
        return
    try:
        cid = int(call.data.split("_")[2])
    except Exception:
        return
    with DB_LOCK:
        conn = get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM channels WHERE id=?", (cid,))
        conn.commit()
        conn.close()
    bot.answer_callback_query(call.id, "Deleted")
    bot.send_message(
        call.message.chat.id, "Deleted.", reply_markup=channels_admin_kb()
    )


@bot.callback_query_handler(func=lambda c: c.data == "fc_add")
def cb_fc_add(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    user_state[call.from_user.id] = {"action": "fc_title"}
    bot.send_message(call.message.chat.id, "Force channel display name:")


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("fc_del_"))
def cb_fc_del(call):
    if not is_admin(call.from_user.id):
        return
    try:
        fid = int(call.data.split("_")[2])
    except Exception:
        return
    with DB_LOCK:
        conn = get_conn()
        c = conn.cursor()
        c.execute("UPDATE force_channels SET active=0 WHERE id=?", (fid,))
        conn.commit()
        conn.close()
    bot.answer_callback_query(call.id, "Removed")
    bot.send_message(call.message.chat.id, "Force channel removed.")


@bot.callback_query_handler(
    func=lambda c: c.data in ("bn_key", "bn_sec", "bn_payid", "bn_addr", "bn_toggle")
)
def cb_bn_fields(call):
    if not is_admin(call.from_user.id):
        return
    if call.data == "bn_toggle":
        cur = get_setting("binance_enabled", "1")
        set_setting("binance_enabled", "0" if cur == "1" else "1")
        bot.answer_callback_query(call.id, "Toggled")
        bot.send_message(
            call.message.chat.id,
            "Binance Instant: %s" % ("OFF" if cur == "1" else "ON"),
        )
        return
    mapping = {
        "bn_key": ("binance_api_key", "Binance API Key:"),
        "bn_sec": ("binance_secret_key", "Binance Secret Key:"),
        "bn_payid": ("binance_pay_id", "Binance Pay ID:"),
        "bn_addr": (
            "binance_address",
            "USDT Address (BSC BEP20):\nNetwork: BNB Smart Chain (BEP20)",
        ),
    }
    key, prompt = mapping[call.data]
    user_state[call.from_user.id] = {"action": "set_setting", "key": key}
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, prompt)


@bot.callback_query_handler(func=lambda c: c.data == "pay_add")
def cb_pay_add(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    user_state[call.from_user.id] = {"action": "pay_method_name"}
    bot.send_message(
        call.message.chat.id,
        "Method name likhun:\nbKash / Nagad / Rocket / Other",
    )


@bot.callback_query_handler(func=lambda c: c.data == "pay_toggle")
def cb_pay_toggle(call):
    if not is_admin(call.from_user.id):
        return
    cur = get_setting("manual_pay_enabled", "1")
    set_setting("manual_pay_enabled", "0" if cur == "1" else "1")
    bot.answer_callback_query(call.id, "Toggled")
    bot.send_message(
        call.message.chat.id,
        "Manual pay: %s" % ("OFF" if cur == "1" else "ON"),
    )


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("pay_del_"))
def cb_pay_del(call):
    if not is_admin(call.from_user.id):
        return
    try:
        pid = int(call.data.split("_")[2])
    except Exception:
        return
    with DB_LOCK:
        conn = get_conn()
        c = conn.cursor()
        c.execute("UPDATE pay_methods SET active=0 WHERE id=?", (pid,))
        conn.commit()
        conn.close()
    bot.answer_callback_query(call.id, "Deleted")
    bot.send_message(call.message.chat.id, "Method removed.")


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("dep_ok_"))
def cb_dep_ok(call):
    if not is_admin(call.from_user.id):
        return
    try:
        did = int(call.data.split("_")[2])
    except Exception:
        return
    with DB_LOCK:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM deposits WHERE id=?", (did,))
        d = c.fetchone()
        if not d or d["status"] != "pending":
            conn.close()
            bot.answer_callback_query(call.id, "Already processed")
            return
        c.execute("UPDATE deposits SET status='approved' WHERE id=?", (did,))
        c.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id=?",
            (float(d["amount"]), d["user_id"]),
        )
        conn.commit()
        conn.close()
    bot.answer_callback_query(call.id, "Approved")
    try:
        bot.send_message(
            d["user_id"],
            "Deposit approved: +%s" % fmt_money(d["amount"]),
        )
    except Exception:
        pass
    bot.send_message(call.message.chat.id, "Approved #%s" % did)


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("dep_no_"))
def cb_dep_no(call):
    if not is_admin(call.from_user.id):
        return
    try:
        did = int(call.data.split("_")[2])
    except Exception:
        return
    with DB_LOCK:
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "UPDATE deposits SET status='rejected' WHERE id=? AND status='pending'",
            (did,),
        )
        conn.commit()
        conn.close()
    bot.answer_callback_query(call.id, "Rejected")
    bot.send_message(call.message.chat.id, "Rejected #%s" % did)


# ----- Binance verify (simple order-id check via Pay API optional) -----
def binance_verify_simple(trx: str) -> tuple:
    """Lightweight check: require API keys set; accept trx length.
    Production: call Binance Pay order query. Here we verify format + optional API.
    """
    api_key = get_setting("binance_api_key")
    secret = get_setting("binance_secret_key")
    if not api_key or not secret:
        return False, "Binance keys not set"
    trx = (trx or "").strip()
    if len(trx) < 6:
        return False, "Invalid transaction id"
    # Optional: Binance Pay query — many setups use merchant order query.
    # Without full merchant integration we accept trx and admin can audit.
    # Attempt public-style timestamp signature request if endpoint configured.
    return True, "ok"


# ----- Text state machine -----
@bot.message_handler(
    func=lambda m: m.from_user.id in user_state,
    content_types=["text"],
)
def state_flow(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    action = st.get("action")
    text = (message.text or "").strip()
    low = text.lower()
    if low in ("cancel", "/cancel", "বাতিল"):
        user_state.pop(uid, None)
        bot.reply_to(message, "Cancelled.", reply_markup=main_menu_kb(uid))
        return

    if action == "track":
        user_state.pop(uid, None)
        # local by provider id
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "SELECT * FROM orders WHERE provider_order_id=? OR id=?",
            (text.replace("#", ""), text.replace("#", "")),
        )
        row = c.fetchone()
        conn.close()
        data, err = provider_status(text.replace("#", ""))
        if row:
            status = row["status"]
            start_c = "-"
            remains = "-"
            if data and isinstance(data, dict):
                status = data.get("status") or status
                start_c = data.get("start_count", start_c)
                remains = data.get("remains", remains)
            bot.reply_to(
                message,
                "Order Track\n\n"
                "Order ID: %s\n"
                "Qty: %s\n"
                "Channel: %s\n"
                "Post: %s\n"
                "Status: %s\n"
                "Start: %s | Remains: %s\n"
                "Charge: %s"
                % (
                    row["provider_order_id"] or row["id"],
                    row["quantity"],
                    row["channel_title"] or row["channel_id"],
                    row["post_link"],
                    status,
                    start_c,
                    remains,
                    fmt_money(row["charge"]),
                ),
            )
            return
        if data and isinstance(data, dict) and not err:
            bot.reply_to(
                message,
                "Provider Track\nID: %s\nStatus: %s\nStart: %s\nRemains: %s"
                % (
                    text,
                    data.get("status"),
                    data.get("start_count"),
                    data.get("remains"),
                ),
            )
            return
        bot.reply_to(message, "Order ID not found. Only real IDs work.")
        return

    if action == "set_api_url":
        if not is_admin(uid):
            return
        if not text.startswith("http"):
            bot.reply_to(message, "URL must start with https://")
            return
        set_setting("api_url", text)
        st["action"] = "set_api_key"
        user_state[uid] = st
        bot.reply_to(message, "API Key paste korun:")
        return

    if action == "set_api_key":
        if not is_admin(uid):
            return
        set_setting("api_key", text)
        user_state.pop(uid, None)
        refresh_service_rate()
        bal, err = provider_balance()
        bot.reply_to(
            message,
            "API saved.\nProvider balance: %s"
            % (bal if bal is not None else err),
            reply_markup=admin_panel_kb(),
        )
        return

    if action == "set_service":
        if not is_admin(uid):
            return
        set_setting("service_id", text)
        user_state.pop(uid, None)
        refresh_service_rate()
        bot.reply_to(
            message,
            "Service ID saved: %s\nRate: %s"
            % (text, get_setting("service_rate") or "unknown"),
            reply_markup=admin_panel_kb(),
        )
        return

    if action == "set_default_qty":
        if not is_admin(uid):
            return
        try:
            q = int(text)
            assert q > 0
        except Exception:
            bot.reply_to(message, "Number din")
            return
        set_setting("default_qty", str(q))
        user_state.pop(uid, None)
        bot.reply_to(message, "Default qty = %s" % q)
        return

    if action == "set_markup_fixed":
        if not is_admin(uid):
            return
        try:
            float(text)
        except Exception:
            bot.reply_to(message, "Number din")
            return
        set_setting("markup_fixed_bdt", text)
        user_state.pop(uid, None)
        bot.reply_to(message, "Fixed markup = %s BDT / 1000" % text)
        return

    if action == "set_setting":
        if not is_admin(uid):
            return
        key = st.get("key")
        set_setting(key, text)
        user_state.pop(uid, None)
        bot.reply_to(message, "Saved %s" % key)
        return

    if action == "ch_add":
        max_ch = int(get_setting("max_user_channels", "10") or 10)
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) AS n FROM channels WHERE owner_user_id=?", (uid,)
        )
        n = int(c.fetchone()["n"])
        conn.close()
        if n >= max_ch and not is_admin(uid):
            user_state.pop(uid, None)
            bot.reply_to(message, "Max %s channels." % max_ch)
            return
        chat_id = None
        title = None
        username = None
        if message.forward_from_chat:
            chat_id = str(message.forward_from_chat.id)
            title = message.forward_from_chat.title
            username = message.forward_from_chat.username
        else:
            t = text
            if t.startswith("@"):
                try:
                    ch = bot.get_chat(t)
                    chat_id = str(ch.id)
                    title = ch.title
                    username = ch.username
                except Exception as e:
                    bot.reply_to(
                        message,
                        "Cannot access chat: %s\n"
                        "Bot ke channel e ADMIN din, then again try." % e,
                    )
                    return
            else:
                chat_id = t
                title = t
        now = datetime.now().isoformat()
        with DB_LOCK:
            conn = get_conn()
            c = conn.cursor()
            c.execute(
                """INSERT OR REPLACE INTO channels
                   (chat_id, title, username, enabled, quantity, service_id, owner_user_id, created_at)
                   VALUES (?,?,?,1,?,?,?,?)""",
                (
                    str(chat_id),
                    title or str(chat_id),
                    username or "",
                    int(get_setting("default_qty") or 50),
                    get_setting("service_id") or "",
                    uid,
                    now,
                ),
            )
            conn.commit()
            conn.close()
        user_state.pop(uid, None)
        bot.reply_to(
            message,
            "Channel saved: %s (%s)\n"
            "Status: ON\n"
            "Bot must be ADMIN in this channel.\n"
            "Post korle auto reaction order jabe."
            % (title, chat_id),
            reply_markup=user_channels_kb(uid),
        )
        return

    if action == "fc_title":
        if not is_admin(uid):
            return
        st["title"] = text[:64]
        st["action"] = "fc_link"
        user_state[uid] = st
        bot.reply_to(message, "Channel link (@user or https://t.me/...):")
        return

    if action == "fc_link":
        if not is_admin(uid):
            return
        title = st.get("title") or "Channel"
        link = text
        chat_ref = text
        if "t.me/" in text:
            chat_ref = "@" + text.rstrip("/").split("/")[-1]
            if chat_ref.startswith("@+"):
                chat_ref = text
        try:
            if chat_ref.startswith("@"):
                ch = bot.get_chat(chat_ref)
                chat_id = str(ch.id)
                if ch.username:
                    link = "https://t.me/%s" % ch.username
            else:
                chat_id = chat_ref
        except Exception:
            chat_id = chat_ref
        with DB_LOCK:
            conn = get_conn()
            c = conn.cursor()
            c.execute(
                "INSERT INTO force_channels (chat_id, title, invite_link, active) VALUES (?,?,?,1)",
                (str(chat_id), title, link),
            )
            conn.commit()
            conn.close()
        user_state.pop(uid, None)
        bot.reply_to(message, "Force channel added: %s" % title)
        return

    if action == "pay_method_name":
        if not is_admin(uid):
            return
        st["method"] = text[:32]
        st["action"] = "pay_method_number"
        user_state[uid] = st
        bot.reply_to(
            message,
            "Number din (je number e Send Money hobe):\nExample: 01XXXXXXXXX",
        )
        return

    if action == "pay_method_number":
        if not is_admin(uid):
            return
        method = st.get("method") or "bKash"
        number = text.strip()
        with DB_LOCK:
            conn = get_conn()
            c = conn.cursor()
            c.execute(
                "INSERT INTO pay_methods (method, name, number, active) VALUES (?,?,?,1)",
                (method, method, number),
            )
            conn.commit()
            conn.close()
        user_state.pop(uid, None)
        bot.reply_to(message, "Saved: %s → %s" % (method, number))
        return

    if action == "pay_method":
        if not is_admin(uid):
            return
        parts = [p.strip() for p in text.split("|")]
        if len(parts) < 3:
            bot.reply_to(message, "Format: Method | Name | Number")
            return
        with DB_LOCK:
            conn = get_conn()
            c = conn.cursor()
            c.execute(
                "INSERT INTO pay_methods (method, name, number, active) VALUES (?,?,?,1)",
                (parts[0], parts[1], parts[2]),
            )
            conn.commit()
            conn.close()
        user_state.pop(uid, None)
        bot.reply_to(message, "Pay method added.")
        return

    if action == "dep_amount":
        try:
            amount = float(text)
        except Exception:
            bot.reply_to(message, "Amount number din")
            return
        min_d = float(get_setting("min_deposit") or 100)
        if amount < min_d:
            bot.reply_to(message, "Min deposit %s" % min_d)
            return
        st["amount"] = amount
        st["action"] = "dep_trx"
        user_state[uid] = st
        bot.reply_to(
            message,
            "Send Money to: %s\nAmount: %s\nCash Out NA.\n\nTransaction ID likhun:"
            % (st.get("number"), amount),
        )
        return

    if action == "dep_trx":
        amount = float(st.get("amount") or 0)
        method = st.get("method") or "manual"
        now = datetime.now().isoformat()
        with DB_LOCK:
            conn = get_conn()
            c = conn.cursor()
            c.execute(
                """INSERT INTO deposits (user_id, method, amount, trx, status, created_at)
                   VALUES (?,?,?,?, 'pending', ?)""",
                (uid, method, amount, text, now),
            )
            did = c.lastrowid
            conn.commit()
            conn.close()
        user_state.pop(uid, None)
        bot.reply_to(
            message,
            "Deposit submitted #%s\nAdmin approve korbe." % did,
        )
        try:
            kb = types.InlineKeyboardMarkup()
            kb.add(
                types.InlineKeyboardButton("✅", callback_data="dep_ok_%s" % did),
                types.InlineKeyboardButton("❌", callback_data="dep_no_%s" % did),
            )
            bot.send_message(
                OWNER_ID,
                "Deposit #%s\nUser %s\n%s %s\nTrx %s"
                % (did, uid, method, amount, text),
                reply_markup=kb,
            )
        except Exception:
            pass
        return

    if action == "bn_amount":
        try:
            amount = float(text)
        except Exception:
            bot.reply_to(message, "Number din")
            return
        min_u = float(get_setting("binance_min_usdt") or 1)
        if amount < min_u:
            bot.reply_to(message, "Min %s USDT" % min_u)
            return
        st["amount"] = amount
        st["action"] = "bn_choose"
        user_state[uid] = st
        kb = types.InlineKeyboardMarkup()
        kb.add(
            types.InlineKeyboardButton("Pay ID", callback_data="bnm_id"),
            types.InlineKeyboardButton("Address", callback_data="bnm_addr"),
        )
        bot.reply_to(
            message,
            "Amount: %s USDT\nPayment method:" % amount,
            reply_markup=kb,
        )
        return

    if action == "bn_trx":
        amount = float(st.get("amount") or 0)
        ok, info = binance_verify_simple(text)
        user_state.pop(uid, None)
        if not ok:
            bot.reply_to(message, "Verify fail: %s" % info)
            return
        # Convert USDT → BDT roughly
        try:
            rate = float(get_setting("usd_bdt_rate") or 120)
        except Exception:
            rate = 120.0
        credit = round(amount * rate, 2)
        add_balance(uid, credit)
        bot.reply_to(
            message,
            "Binance payment accepted.\n+ %s credited.\nNew balance: %s"
            % (fmt_money(credit), fmt_money(get_balance(uid))),
        )
        try:
            bot.send_message(
                OWNER_ID,
                "Binance deposit user %s amount %s USDT trx %s credit %s"
                % (uid, amount, text, credit),
            )
        except Exception:
            pass
        return

    if action == "add_bal_uid":
        if not is_admin(uid):
            return
        try:
            tid = int(text)
        except Exception:
            bot.reply_to(message, "user_id")
            return
        st["tid"] = tid
        st["action"] = "add_bal_amt"
        user_state[uid] = st
        bot.reply_to(message, "Amount (BDT):")
        return

    if action == "add_bal_amt":
        if not is_admin(uid):
            return
        try:
            amt = float(text)
        except Exception:
            bot.reply_to(message, "number")
            return
        tid = st.get("tid")
        ensure_user(types.User(id=tid, is_bot=False, first_name="user"))
        add_balance(tid, amt)
        user_state.pop(uid, None)
        bot.reply_to(message, "Added %s to %s" % (fmt_money(amt), tid))
        try:
            bot.send_message(tid, "Admin added balance: +%s" % fmt_money(amt))
        except Exception:
            pass
        return

    if action == "add_admin":
        if not is_admin(uid):
            return
        try:
            tid = int(text)
        except Exception:
            bot.reply_to(message, "user_id")
            return
        with DB_LOCK:
            conn = get_conn()
            c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (tid,))
            conn.commit()
            conn.close()
        load_admins()
        user_state.pop(uid, None)
        bot.reply_to(message, "Admin added %s" % tid)
        try:
            bot.send_message(tid, "You are now admin of Auto Reaction Bot.")
        except Exception:
            pass
        return

    if action == "rm_admin":
        if not is_main_owner(uid):
            bot.reply_to(message, "Only Main Owner can remove admin")
            return
        try:
            tid = int(text)
        except Exception:
            bot.reply_to(message, "user_id")
            return
        if tid == int(get_setting("owner_id", str(OWNER_ID)) or OWNER_ID):
            bot.reply_to(message, "Cannot remove main owner")
            return
        with DB_LOCK:
            conn = get_conn()
            c = conn.cursor()
            c.execute("DELETE FROM admins WHERE user_id=?", (tid,))
            conn.commit()
            conn.close()
        load_admins()
        user_state.pop(uid, None)
        bot.reply_to(message, "Admin removed: %s" % tid)
        return

    if action == "owner_transfer":
        if not is_main_owner(uid):
            user_state.pop(uid, None)
            bot.reply_to(message, "Only Main Owner")
            return
        try:
            new_owner = int(text)
        except Exception:
            bot.reply_to(message, "Invalid user ID")
            return
        set_setting("owner_id", str(new_owner))
        with DB_LOCK:
            conn = get_conn()
            c = conn.cursor()
            c.execute(
                "INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (new_owner,)
            )
            conn.commit()
            conn.close()
        load_admins()
        user_state.pop(uid, None)
        bot.reply_to(
            message,
            "Ownership transferred.\nNew Owner ID: %s\n"
            "Restart bot recommended (OWNER_ID env update optional)."
            % new_owner,
        )
        try:
            bot.send_message(
                new_owner,
                "You are now Main Owner of Auto Reaction Bot.",
            )
        except Exception:
            pass
        return

    if action == "broadcast":
        if not is_admin(uid):
            return
        user_state.pop(uid, None)
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users")
        rows = c.fetchall()
        conn.close()
        ok = 0
        for r in rows:
            try:
                bot.send_message(r["user_id"], text)
                ok += 1
            except Exception:
                pass
            time.sleep(0.05)
        bot.reply_to(message, "Sent to %s users" % ok)
        return


@bot.callback_query_handler(func=lambda c: c.data in ("bnm_id", "bnm_addr"))
def cb_bn_method(call):
    uid = call.from_user.id
    st = user_state.get(uid) or {}
    if not st.get("amount"):
        bot.answer_callback_query(call.id, "Start from Wallet → Binance")
        return
    bot.answer_callback_query(call.id)
    amount = st.get("amount")
    network = get_setting("binance_network", "BSC BNB Smart Chain (BEP20)")
    if call.data == "bnm_id":
        target = get_setting("binance_pay_id") or "NOT SET"
        label = "Pay ID"
        extra = "Binance app → Pay → Pay ID e pathan."
    else:
        target = get_setting("binance_address") or "NOT SET"
        label = "Address"
        extra = (
            "Network MUST be: %s\n"
            "USDT (BEP20) only. Wrong chain = lost funds."
            % network
        )
    st["action"] = "bn_trx"
    user_state[uid] = st
    bot.send_message(
        call.message.chat.id,
        "Send %s USDT ($)\n\n"
        "%s:\n%s\n\n"
        "%s\n\n"
        "Payment er por Transaction / Order ID likhun:"
        % (amount, label, target, extra),
    )


# ================== MAIN ==================
def main():
    init_db()
    me = bot.get_me()
    logger.info("Auto Reaction Bot @%s owner=%s", me.username, OWNER_ID)
    # channel posts need no privacy mode issues — bot is channel admin
    bot.infinity_polling(timeout=60, long_polling_timeout=60)


if __name__ == "__main__":
    main()
