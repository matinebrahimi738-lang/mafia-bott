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

نصب پیش‌نیازها:
    pip install python-telegram-bot --upgrade

اجرا:
    1) از @BotFather یک توکن بگیر
    2) توکن رو در متغیر محیطی BOT_TOKEN قرار بده یا مستقیم پایین جایگزین کن
    3) python bot.py
"""

import json
import logging
import os
import random
from dataclasses import dataclass, field
from pathlib import Path

from telegram import Update
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

BOT_TOKEN = "8941118221:AAHh-q5jmLGn0bKXFj098jVaqyAO33PZZEk"
STATS_FILE = Path(__file__).parent / "stats.json"

# ---------------------------------------------------------------------------
# تعریف رول‌ها
# هر رول: نام، تیم (mafia / city / independent)، توضیح، و حداقل تعداد نفرات
# لازم برای فعال شدنش
# ---------------------------------------------------------------------------

ROLES = {
    "پدرخوانده": {
        "team": "mafia",
        "desc": "رهبر مافیا. شب‌ها با گروهش یک نفر رو انتخاب و حذف می‌کنه.",
        "min_players": 5,
        "weight": 1,
    },
    "مافیای ساده": {
        "team": "mafia",
        "desc": "عضو گروه مافیا. در انتخاب شب کمک می‌کنه ولی رأی نهایی با پدرخونده‌ست.",
        "min_players": 7,
        "weight": 1,
    },
    "دکتر": {
        "team": "city",
        "desc": "هر شب می‌تونه یک نفر (حتی خودش) رو از حذف شدن نجات بده.",
        "min_players": 5,
        "weight": 1,
    },
    "کارآگاه": {
        "team": "city",
        "desc": "هر شب هویت یک نفر رو استعلام می‌گیره تا بفهمه مافیاست یا نه.",
        "min_players": 5,
        "weight": 1,
    },
    "تک‌تیرانداز": {
        "team": "city",
        "desc": "یک بار در کل بازی می‌تونه شب یک نفر رو مستقیم حذف کنه.",
        "min_players": 8,
        "weight": 1,
    },
    "شهروند": {
        "team": "city",
        "desc": "توانایی خاصی نداره؛ فقط با بحث و رأی روزها به مافیا مشکوک می‌شه.",
        "min_players": 5,
        "weight": 3,
    },
    "دلقک": {
        "team": "independent",
        "desc": "تیم مستقلِ خودشه؛ هدفش اینه با رأی گروه اعدام بشه تا برنده بشه.",
        "min_players": 9,
        "weight": 1,
    },
}


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


# ---------------------------------------------------------------------------
# هندلرهای دستورات
# ---------------------------------------------------------------------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! من ربات تحلیل رول بازی «جنگ» هستم.\n\n"
        "دستورات:\n"
        "/newgame - شروع یک بازی جدید در این گروه\n"
        "/join - عضویت در بازی جاری\n"
        "/startgame - تخصیص تصادفی رول‌ها بین اعضا\n"
        "/roles - نمایش توضیح رول‌ها\n"
        "/endgame <mafia|city|independent> - پایان بازی و ثبت تیم برنده\n"
        "/stats - آمار برد هر رول تا این لحظه"
    )


async def new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    games[chat_id] = GameState()
    await update.message.reply_text(
        "بازی جدید ساخته شد ✅\nبازیکن‌ها با /join وارد بشن، بعد ادمین با /startgame شروع کنه."
    )


async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if not game or game.started:
        await update.message.reply_text("بازی فعالی برای عضویت وجود نداره. اول /newgame بزن.")
        return

    user = update.effective_user
    if user.id in game.joined:
        await update.message.reply_text("قبلاً عضو شدی!")
        return

    game.joined[user.id] = user.first_name
    await update.message.reply_text(f"{user.first_name} وارد بازی شد. تعداد فعلی: {len(game.joined)} نفر")


async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if not game or game.started:
        await update.message.reply_text("بازی فعالی برای شروع وجود نداره یا قبلاً شروع شده.")
        return

    n = len(game.joined)
    if n < 5:
        await update.message.reply_text("برای شروع حداقل ۵ نفر لازمه.")
        return

    ids = list(game.joined.keys())
    names = [game.joined[i] for i in ids]
    id_by_name = {game.joined[i]: i for i in ids}

    assignment = assign_roles(names)  # name -> role
    game.assignments = {id_by_name[name]: role for name, role in assignment.items()}
    game.started = True

    for user_id, role in game.assignments.items():
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"رول تو تو این بازی: 🎭 {role}\n\n{ROLES[role]['desc']}",
            )
        except Exception:
            logger.warning("نتونستم پیام خصوصی به %s بفرستم؛ باید قبلاً استارت بات رو زده باشه.", user_id)

    await update.message.reply_text(
        f"رول‌ها بین {n} نفر تقسیم شد و برای هرکس خصوصی فرستاده شد ✅\n"
        "کسی که پیام خصوصی نگرفت باید اول ربات رو /start بزنه."
    )


async def show_roles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["📜 لیست رول‌ها:\n"]
    for name, info in ROLES.items():
        team_fa = {"mafia": "مافیا", "city": "شهر", "independent": "مستقل"}[info["team"]]
        lines.append(f"• {name} ({team_fa}) — {info['desc']} [حداقل نفرات: {info['min_players']}]")
    await update.message.reply_text("\n".join(lines))


async def end_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if not game or not game.started:
        await update.message.reply_text("بازی فعالی برای پایان دادن وجود نداره.")
        return

    if not context.args or context.args[0] not in ("mafia", "city", "independent"):
        await update.message.reply_text("استفاده: /endgame mafia یا /endgame city یا /endgame independent")
        return

    winner_team = context.args[0]
    role_names = list(game.assignments.values())
    record_result(role_names, winner_team)

    del games[chat_id]
    await update.message.reply_text(f"بازی تموم شد. تیم برنده: {winner_team} ✅ آمار به‌روزرسانی شد.")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_stats()
    if not data:
        await update.message.reply_text("هنوز آماری ثبت نشده.")
        return

    lines = ["📊 آمار رول‌ها:\n"]
    for role, s in data.items():
        games_count = s["games"]
        wins = s["wins"]
        winrate = (wins / games_count * 100) if games_count else 0
        lines.append(f"• {role}: {wins}/{games_count} برد ({winrate:.0f}%)")
    await update.message.reply_text("\n".join(lines))


def main():
    if BOT_TOKEN == "PUT-YOUR-TOKEN-HERE":
        raise SystemExit("لطفاً BOT_TOKEN رو تنظیم کن (متغیر محیطی یا مستقیم داخل کد).")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
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
