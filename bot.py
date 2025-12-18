import os
import re
import random
import asyncio
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from db import (
    init_db, upsert_user, set_inactive, get_active_users, get_child_for_santa,
    clear_pairs, set_pair, get_user_label,
    load_tasks_if_empty, add_schedule, remove_schedule, list_schedules,
    set_setting, get_setting,
    reset_waves, init_wave_queue,
    get_wave_state_full, get_wave_groups, advance_wave,
    full_reset, reload_tasks_from_file
)
from logic import build_secret_santa_pairs, split_into_groups_max5, make_wave_mapping
from scheduler_jobs import job_send_random_task
from keyboards import user_menu


# ---------------- ENV ----------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "bot.db")
TZ = os.getenv("TZ", "Europe/Moscow")

DEVELOPER_ID = int(os.getenv("DEVELOPER_ID", "0"))
ORGANIZER_ID = int(os.getenv("ORGANIZER_ID", "0"))

TASKS_FILE = os.getenv("TASKS_FILE", "tasks.txt")
EMOTIONS_FILE = os.getenv("EMOTIONS_FILE", "wave_emotions.txt")
TREASURE_FILE = os.getenv("TREASURE_FILE", "treasure.txt")

if not BOT_TOKEN or not DEVELOPER_ID or not ORGANIZER_ID:
    raise RuntimeError("Заполни .env: BOT_TOKEN, DEVELOPER_ID, ORGANIZER_ID")


# ---------------- CORE ----------------
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone=TZ)


def is_dev(uid: int) -> bool:
    return uid == DEVELOPER_ID


def parse_hhmm(s: str):
    m = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", s.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def read_lines(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [x.strip() for x in f if x.strip()]


# ---------------- GROUP CHAT ----------------
async def get_group_chat_id() -> int | None:
    v = await get_setting(DB_PATH, "GROUP_CHAT_ID")
    return int(v) if v else None


async def ensure_group_chat_bound(call_or_msg):
    gid = await get_group_chat_id()
    if gid is None:
        txt = (
            "❗ Общий чат не привязан.\n\n"
            "Зайди в нужный чат и напиши там команду:\n/set_group"
        )
        if isinstance(call_or_msg, CallbackQuery):
            await call_or_msg.message.answer(txt)
        else:
            await call_or_msg.answer(txt)
        return None
    return gid


# ---------------- START / MENU ----------------
@dp.message(CommandStart())
async def start_cmd(message: Message):
    if message.chat.type != "private":
        await message.answer("Напиши мне в личку /start 🙂")
        return

    await upsert_user(
        DB_PATH,
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name or ""
    )

    await message.answer(
        "✅ Ты зарегистрирован(а).\n\n"
        "🎅 «Санта» — покажет твоего подопечного\n"
        "🔔 Задания приходят в личку\n"
        "🌊 Волны и 🪙 события запускает разработчик",
        reply_markup=user_menu(is_developer=is_dev(message.from_user.id))
    )


@dp.message(Command("menu"))
async def menu_cmd(message: Message):
    if message.chat.type != "private":
        return
    await message.answer(
        "Меню:",
        reply_markup=user_menu(is_developer=is_dev(message.from_user.id))
    )


# ---------------- BIND GROUP ----------------
@dp.message(Command("set_group"))
async def set_group_cmd(message: Message):
    if message.from_user.id != DEVELOPER_ID:
        return
    if message.chat.type == "private":
        await message.answer("Команда выполняется в группе.")
        return

    await set_setting(DB_PATH, "GROUP_CHAT_ID", str(message.chat.id))
    await message.answer("✅ Группа привязана.")


# ---------------- DELETE ME ----------------
@dp.callback_query(F.data == "delete_me")
async def cb_delete(call: CallbackQuery):
    if call.message.chat.type != "private":
        await call.answer("Открой личку с ботом", show_alert=True)
        return
    await set_inactive(DB_PATH, call.from_user.id)
    await call.message.answer("❌ Ты удалён(а) из базы.")
    await call.answer()


# ---------------- SANTA ----------------
@dp.callback_query(F.data == "santa_me")
async def cb_santa_me(call: CallbackQuery):
    if call.message.chat.type != "private":
        return
    child_id = await get_child_for_santa(DB_PATH, call.from_user.id)
    if not child_id:
        await call.message.answer("🎅 Санта ещё не запускался.")
        return
    label = await get_user_label(DB_PATH, child_id)
    await call.message.answer(
        f"🎁 Твой подопечный:\n{label}\n\nНикому не рассказывай 😉"
    )


@dp.callback_query(F.data == "dev_santa_start")
async def cb_dev_santa_start(call: CallbackQuery):
    if call.from_user.id != DEVELOPER_ID:
        return

    users = await get_active_users(DB_PATH)
    if len(users) < 2:
        await call.message.answer("⛔ Нужно минимум 2 игрока.")
        return

    ids = [u[0] for u in users]
    pairs = build_secret_santa_pairs(ids)

    await clear_pairs(DB_PATH)
    for s, c in pairs.items():
        await set_pair(DB_PATH, s, c)

    for s, c in pairs.items():
        try:
            await bot.send_message(
                s,
                f"🎅 *Твой подопечный:*\n{await get_user_label(DB_PATH, c)}",
                parse_mode="Markdown"
            )
        except:
            pass

    log = [
        f"{await get_user_label(DB_PATH, s)} → {await get_user_label(DB_PATH, c)}"
        for s, c in pairs.items()
    ]

    await bot.send_message(
        ORGANIZER_ID,
        "🎅 Санта запущен:\n\n" + "\n".join(log)
    )

    await call.message.answer("✅ Санта запущен.")


# ---------------- TREASURE ----------------
@dp.callback_query(F.data == "dev_treasure")
async def cb_dev_treasure(call: CallbackQuery):
    if call.from_user.id != DEVELOPER_ID:
        return

    gid = await ensure_group_chat_bound(call)
    if not gid:
        return

    riddles = read_lines(TREASURE_FILE)
    if not riddles:
        await call.message.answer("⛔ treasure.txt пуст.")
        return

    await bot.send_message(
        gid,
        "🪙 *Золотоискатель*\n\n" + random.choice(riddles),
        parse_mode="Markdown"
    )


# ---------------- WAVES (FIXED QUEUE) ----------------
async def run_wave_fixed_queue():
    users = await get_active_users(DB_PATH)
    if len(users) < 4:
        await bot.send_message(ORGANIZER_ID, "⛔ Мало игроков для волны.")
        return "⛔ Мало игроков."

    wave_index, active_idx, is_init = await get_wave_state_full(DB_PATH)

    if not is_init:
        ids = [u[0] for u in users]
        random.shuffle(ids)
        groups = split_into_groups_max5(ids)
        await init_wave_queue(DB_PATH, groups)
        wave_index, active_idx, _ = await get_wave_state_full(DB_PATH)

    groups = await get_wave_groups(DB_PATH)
    total = len(groups)

    active = groups[active_idx]
    passive = groups[(active_idx + 1) % total]

    emotions = read_lines(EMOTIONS_FILE) or ["Радость", "Счастье"]
    pairs = make_wave_mapping(active, passive)

    log = [f"🌊 Волна {wave_index}"]
    passive_set = set()
    assignments = []

    for a_id, t_id in pairs:
        emotion = random.choice(emotions)
        assignments.append((a_id, t_id, emotion))
        log.append(
            f"{await get_user_label(DB_PATH, a_id)} → "
            f"{await get_user_label(DB_PATH, t_id)} ({emotion})"
        )
        passive_set.add(t_id)

    await bot.send_message(ORGANIZER_ID, "\n".join(log))

    for a_id, t_id, emotion in assignments:
        await bot.send_message(
            a_id,
            f"🌊 Ваша эмоция: {emotion}\n"
            f"Ваша цель: {await get_user_label(DB_PATH, t_id)}"
        )

    for pid in passive_set:
        await bot.send_message(
            pid,
            "🌊 Вы выбраны целью. Ничего делать не нужно."
        )

    return f"✅ Волна {wave_index} запущена"


@dp.callback_query(F.data == "dev_wave_run")
async def cb_wave_run(call: CallbackQuery):
    if call.from_user.id != DEVELOPER_ID:
        return
    await call.message.answer(await run_wave_fixed_queue())


@dp.callback_query(F.data == "dev_wave_next")
async def cb_wave_next(call: CallbackQuery):
    if call.from_user.id != DEVELOPER_ID:
        return
    await advance_wave(DB_PATH)
    await call.message.answer(await run_wave_fixed_queue())


@dp.callback_query(F.data == "dev_wave_reset")
async def cb_wave_reset(call: CallbackQuery):
    if call.from_user.id != DEVELOPER_ID:
        return
    await reset_waves(DB_PATH)
    await call.message.answer("🔄 Волны сброшены.")


# ---------------- FULL RESET ----------------
@dp.callback_query(F.data == "dev_full_reset")
async def cb_full_reset(call: CallbackQuery):
    if call.from_user.id != DEVELOPER_ID:
        return
    await full_reset(DB_PATH)
    await call.message.answer("🧹 Полный сброс выполнен.")


# ---------------- RELOAD TASKS ----------------
@dp.callback_query(F.data == "dev_reload_tasks")
async def cb_reload_tasks(call: CallbackQuery):
    if call.from_user.id != DEVELOPER_ID:
        return
    count = await reload_tasks_from_file(DB_PATH, TASKS_FILE)
    await call.message.answer(
        f"✅ Задания обновлены ({count})" if count else "⚠️ Файл пуст."
    )


# ---------------- SCHEDULER ----------------
async def reschedule_cron():
    for job in scheduler.get_jobs():
        scheduler.remove_job(job.id)

    times = await list_schedules(DB_PATH)
    for hh, mm in times:
        scheduler.add_job(
            job_send_random_task,
            trigger=CronTrigger(hour=hh, minute=mm),
            kwargs={
                "bot": bot,
                "db_path": DB_PATH,
                "organizer_id": ORGANIZER_ID
            },
            id=f"cron_{hh}_{mm}",
            replace_existing=True
        )


# ---------------- MAIN ----------------
async def main():
    await init_db(DB_PATH)
    await load_tasks_if_empty(DB_PATH, TASKS_FILE)
    await reschedule_cron()

    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
