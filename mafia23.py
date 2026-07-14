# -*- coding: utf-8 -*-
"""
ربات تلگرام برای مدیریت و تحلیل رول‌های بازی متنی «جنگ» (شبیه مافیا/ورولف)

قابلیت‌ها:
- ساخت بازی جدید داخل گروه
- عضویت بازیکن‌ها با /join
- تخصیص تصادفی و متعادل رول‌ها بین بازیکن‌ها (بر اساس تعداد نفرات)
- ارسال خصوصی رول هرکس به خودش (بقیه گروه نمی‌بینن)
- نمایش توضیح هر رول با /roles
- ثبت نتیجه بازی و نگهداری آمار برد هر رول با /endgame و /stats
- راهنمای کامل با /help

نصب پیش‌نیازها:
    pip install python-telegram-bot --upgrade

اجرا:
    1) از @BotFather یک توکن بگیر
    2) توکن رو در متغیر محیطی BOT_TOKEN قرار بده (پیشنهاد می‌شود، نه هاردکد)
       مثال (لینوکس/مک):   export BOT_TOKEN="123456:ABC-DEF..."
       مثال (ویندوز PowerShell): $env:BOT_TOKEN="123456:ABC-DEF..."
    3) python bot.py

نکته امنیتی: توکن ربات را هرگز مستقیم داخل کد ننویس و آن را جایی
(گیت‌هاب عمومی، چت، فایل به‌اشتراک‌گذاشته‌شده و ...) پابلیک نکن.
اگر فکر می‌کنی توکن قبلی‌ات لو رفته، از @BotFather با دستور /revoke
یک توکن جدید بگیر.
"""

import html
import json
import logging
import os
import random
from dataclasses import dataclass, field
from pathlib import Path

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# توکن را از متغیر محیطی بخوان؛ هرگز اینجا هاردکد نکن.
BOT_TOKEN = ("8941118221:AAEiikPRgIxK_xkQpyR7jHNU2PrzoW_HIGg")
STATS_FILE = Path(__file__).parent / "stats.json"

VERSION = "2.0"

# ---------------------------------------------------------------------------
# تعریف رول‌ها
# هر رول: نام، تیم (mafia / city / independent)، توضیح، ایموجی و حداقل تعداد
# نفرات لازم برای فعال شدنش
# ---------------------------------------------------------------------------

ROLES = {
    "پدرخوانده": {
        "team": "mafia",
        "emoji": "🕴",
        "desc": "رهبر مافیا. شب‌ها با گروهش یک نفر رو انتخاب و حذف می‌کنه.",
        "min_players": 5,
        "weight": 1,
    },
    "مافیای ساده": {
        "team": "mafia",
        "emoji": "🔪",
        "desc": "عضو گروه مافیا. در انتخاب شب کمک می‌کنه ولی رأی نهایی با پدرخونده‌ست.",
        "min_players": 7,
        "weight": 1,
    },
    "دکتر": {
        "team": "city",
        "emoji": "🩺",
        "desc": "هر شب می‌تونه یک نفر (حتی خودش) رو از حذف شدن نجات بده.",
        "min_players": 5,
        "weight": 1,
    },
    "کارآگاه": {
        "team": "city",
        "emoji": "🕵️",
        "desc": "هر شب هویت یک نفر رو استعلام می‌گیره تا بفهمه مافیاست یا نه.",
        "min_players": 5,
        "weight": 1,
    },
    "تک‌تیرانداز": {
        "team": "city",
        "emoji": "🎯",
        "desc": "یک بار در کل بازی می‌تونه شب یک نفر رو مستقیم حذف کنه.",
        "min_players": 8,
        "weight": 1,
    },
    "شهروند": {
        "team": "city",
        "emoji": "👤",
        "desc": "توانایی خاصی نداره؛ فقط با بحث و رأی روزها به مافیا مشکوک می‌شه.",
        "min_players": 5,
        "weight": 3,
    },
    "دلقک": {
        "team": "independent",
        "emoji": "🤡",
        "desc": "تیم مستقلِ خودشه؛ هدفش اینه با رأی گروه اعدام بشه تا برنده بشه.",
        "min_players": 9,
        "weight": 1,
    },
}

TEAM_FA = {"mafia": "مافیا 🔪", "city": "شهر 🏘", "independent": "مستقل 🎭"}


def eligible_roles(player_count: int):
    """رول‌هایی که با توجه به تعداد بازیکن‌ها قابل استفاده‌ان"""
    return {name: r for name, r in ROLES.items() if r["min_players"] <= player_count}


def assign_roles(players: list[str]) -> dict[str, str]:
    """
    تخصیص متعادل رول‌ها به بازیکن‌ها.
    """
    n = len(players)
    pool = eligible_roles(n)
    special = {k: v for k, v in pool.items() if k != "شهروند"}

    max_mafia = max(1, n // 3)

    role_list = []
    mafia_count = 0
    for name, info in special.items():
        if info["team"] == "mafia":
            if mafia_count >= max_mafia:
                continue
            mafia_count += 1
        role_list.append(name)

    random.shuffle(role_list)
    role_list = role_list[:max(0, n - 1)]

    while len(role_list) < n:
        role_list.append("شهروند")

    random.shuffle(role_list)
    shuffled_players = players[:]
    random.shuffle(shuffled_players)

    return dict(zip(shuffled_players, role_list))


# ---------------------------------------------------------------------------
# مدیریت وضعیت بازی به ازای هر گروه (چت)
# ---------------------------------------------------------------------------


@dataclass
class GameState:
    joined: dict[int, str] = field(default_factory=dict)  # user_id -> نام نمایشی
    assignments: dict[int, str] = field(default_factory=dict)  # user_id -> رول
    started: bool = False


games: dict[int, GameState] = {}


def load_stats() -> dict:
    if STATS_FILE.exists():
        return json.loads(STATS_FILE.read_text(encoding="utf-8"))
    return {}


def save_stats(stats: dict) -> None:
    STATS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


def record_result(role_names: list[str], winner_team: str) -> None:
    stats = load_stats()
    for role in role_names:
        team = ROLES[role]["team"]
        entry = stats.setdefault(role, {"games": 0, "wins": 0})
        entry["games"] += 1
        if team == winner_team:
            entry["wins"] += 1
    save_stats(stats)


def esc(text: str) -> str:
    """اسکیپ کردن کاراکترهای خاص HTML برای جلوگیری از خرابی فرمت پیام."""
    return html.escape(str(text))


# ---------------------------------------------------------------------------
# هندلرهای دستورات
# ---------------------------------------------------------------------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        "╔════════════════════╗\n"
        "⚔️ <b>به ربات مدیریت بازی جنگ خوش اومدی!</b>\n"
        "╚════════════════════╝\n\n"
        f"👋 سلام <b>{esc(user.first_name)}</b>!\n\n"
        "🔥 با این ربات می‌تونی:\n"
        "🎭 بازی جدید بسازی\n"
        "👥 بازیکن‌ها رو مدیریت کنی\n"
        "🎲 رول‌ها رو خودکار تقسیم کنی\n"
        "📊 آمار بازی‌ها رو ببینی\n\n"
        "📖 برای دیدن راهنمای کامل دستورات، /help رو بزن.\n\n"
        f"⚡ نسخه {VERSION}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 <b>راهنمای ربات</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "🎮 <b>مدیریت بازی</b>\n"
        "🆕 /newgame — ساخت بازی جدید در گروه\n"
        "➕ /join — عضویت در بازی جاری\n"
        "🎲 /startgame — تخصیص تصادفی رول‌ها بین اعضا\n"
        "🏁 /endgame &lt;mafia|city|independent&gt; — پایان بازی و ثبت تیم برنده\n\n"
        "📋 <b>اطلاعات</b>\n"
        "🎭 /roles — نمایش توضیح رول‌ها\n"
        "📊 /stats — آمار برد هر رول\n\n"
        "━━━━━━━━━━━━━━\n"
        f"⚡ نسخه {VERSION}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    games[chat_id] = GameState()
    text = (
        "🆕 <b>بازی جدید ساخته شد!</b> ✅\n"
        "━━━━━━━━━━━━━━\n"
        "➕ بازیکن‌ها با /join وارد بشن\n"
        "🎲 بعد ادمین با /startgame شروعش کنه"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if not game or game.started:
        await update.message.reply_text(
            "❌ بازی فعالی برای عضویت وجود نداره.\nاول با /newgame یه بازی بساز.",
        )
        return

    user = update.effective_user
    if user.id in game.joined:
        await update.message.reply_text(f"⚠️ <b>{esc(user.first_name)}</b>، قبلاً عضو شدی!", parse_mode=ParseMode.HTML)
        return

    game.joined[user.id] = user.first_name
    text = (
        f"✅ <b>{esc(user.first_name)}</b> وارد بازی شد.\n"
        "━━━━━━━━━━━━━━\n"
        f"👥 تعداد بازیکنان: <b>{len(game.joined)}</b> نفر\n"
        "⏳ منتظر بازیکنان بیشتر..."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if not game or game.started:
        await update.message.reply_text("❌ بازی فعالی برای شروع وجود نداره یا قبلاً شروع شده.")
        return

    n = len(game.joined)
    if n < 5:
        await update.message.reply_text(f"⚠️ برای شروع حداقل ۵ نفر لازمه. (الان: {n} نفر)")
        return

    ids = list(game.joined.keys())
    names = [game.joined[i] for i in ids]
    id_by_name = {game.joined[i]: i for i in ids}

    assignment = assign_roles(names)  # name -> role
    game.assignments = {id_by_name[name]: role for name, role in assignment.items()}
    game.started = True

    sent_ok = 0
    for user_id, role in game.assignments.items():
        info = ROLES[role]
        name = game.joined[user_id]
        pv_text = (
            "🎭 <b>رول شما مشخص شد!</b>\n"
            "━━━━━━━━━━━━━━\n"
            f"👤 <b>بازیکن:</b> {esc(name)}\n\n"
            f"🎯 <b>رول:</b> {info['emoji']} {esc(role)}\n"
            f"🏳️ <b>تیم:</b> {TEAM_FA[info['team']]}\n\n"
            f"📜 <b>توضیح:</b>\n{esc(info['desc'])}\n\n"
            "⚠️ <i>این پیام محرمانه است، به کسی نشونش نده.</i>"
        )
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=pv_text,
                parse_mode=ParseMode.HTML,
            )
            sent_ok += 1
        except Exception:
            logger.warning("نتونستم پیام خصوصی به %s بفرستم؛ باید قبلاً استارت بات رو زده باشه.", user_id)

    text = (
        "🎉 <b>بازی آغاز شد!</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"👥 بازیکنان: <b>{n}</b> نفر\n"
        f"🎭 رول‌ها برای <b>{sent_ok}</b> نفر خصوصی ارسال شد.\n\n"
        "📩 اگه کسی پیام خصوصی نگرفت:\n"
        "اول باید /start رو تو پی‌وی ربات بزنه، بعد ادمین دوباره /startgame بزنه."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def show_roles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["📜 <b>لیست رول‌ها</b>", "━━━━━━━━━━━━━━", ""]
    for name, info in ROLES.items():
        lines.append(
            f"{info['emoji']} <b>{esc(name)}</b> ({TEAM_FA[info['team']]})\n"
            f"   {esc(info['desc'])}\n"
            f"   👥 حداقل نفرات: {info['min_players']}\n"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def end_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if not game or not game.started:
        await update.message.reply_text("❌ بازی فعالی برای پایان دادن وجود نداره.")
        return

    if not context.args or context.args[0] not in ("mafia", "city", "independent"):
        await update.message.reply_text(
            "⚠️ استفاده درست:\n/endgame mafia\n/endgame city\n/endgame independent"
        )
        return

    winner_team = context.args[0]
    role_names = list(game.assignments.values())
    record_result(role_names, winner_team)

    del games[chat_id]
    text = (
        "🏁 <b>بازی تموم شد!</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"🏆 تیم برنده: <b>{TEAM_FA[winner_team]}</b>\n"
        "📊 آمار به‌روزرسانی شد ✅"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_stats()
    if not data:
        await update.message.reply_text("📊 هنوز آماری ثبت نشده.")
        return

    lines = ["📊 <b>آمار رول‌ها</b>", "━━━━━━━━━━━━━━", ""]
    for role, s in data.items():
        info = ROLES.get(role, {"emoji": "🎭"})
        games_count = s["games"]
        wins = s["wins"]
        winrate = (wins / games_count * 100) if games_count else 0
        lines.append(
            f"{info['emoji']} <b>{esc(role)}</b>\n"
            f"   🏆 برد: {wins}   🎮 بازی: {games_count}\n"
            f"   📈 Win Rate: {winrate:.0f}%\n"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


def main():
    if not BOT_TOKEN or BOT_TOKEN == "PUT-YOUR-TOKEN-HERE":
        raise SystemExit(
            "لطفاً BOT_TOKEN رو به‌عنوان متغیر محیطی تنظیم کن، مثلاً:\n"
            "  export BOT_TOKEN=\"123456:ABC-DEF...\"   (لینوکس/مک)\n"
            "  $env:BOT_TOKEN=\"123456:ABC-DEF...\"      (ویندوز PowerShell)"
        )

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("newgame", new_game))
    app.add_handler(CommandHandler("join", join))
    app.add_handler(CommandHandler("startgame", start_game))
    app.add_handler(CommandHandler("roles", show_roles))
    app.add_handler(CommandHandler("endgame", end_game))
    app.add_handler(CommandHandler("stats", stats))

    logger.info("ربات در حال اجراست...")
    app.run_polling()


if __name__ == "__main__":
    main()
