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
    init_db,
    upsert_user,
    set_inactive,
    get_active_users,
    get_child_for_santa,
    clear_pairs,
    set_pair,
    get_user_label,
    load_tasks_if_empty,
    add_schedule,
    remove_schedule,
    list_schedules,
    set_setting,
    get_setting,
    reset_waves,
    init_wave_queue,
    get_wave_state_full,
    get_wave_groups,
    advance_wave,
    clear_wave_assignments,
    insert_wave_assignment,
    get_wave_assignments,
    full_reset,
    reload_tasks_from_file, get_used_tasks, reset_used_tasks_for_group, mark_task_used,
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
    raise RuntimeError("Заполни .env")

# ---------------- CORE ----------------
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone=TZ)

WAITING_GROUP_MESSAGE = set()

# ---------------- UTILS ----------------
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
async def get_group_chat_id():
    v = await get_setting(DB_PATH, "GROUP_CHAT_ID")
    return int(v) if v else None


# ---------------- SCHEDULER ----------------
async def reschedule_cron():
    for job in scheduler.get_jobs():
        if job.id.startswith("cron_"):
            scheduler.remove_job(job.id)

    for hh, mm in await list_schedules(DB_PATH):
        scheduler.add_job(
            job_send_random_task,
            CronTrigger(hour=hh, minute=mm),
            kwargs={"bot": bot, "db_path": DB_PATH, "organizer_id": ORGANIZER_ID},
            id=f"cron_{hh}_{mm}",
        )


async def schedule_one_shot(seconds: int):
    run_at = datetime.now(tz=scheduler.timezone) + timedelta(seconds=seconds)
    scheduler.add_job(
        job_send_random_task,
        "date",
        run_date=run_at,
        kwargs={"bot": bot, "db_path": DB_PATH, "organizer_id": ORGANIZER_ID},
    )
    return run_at

# ---------------- START ----------------
@dp.message(CommandStart())
async def start_cmd(message: Message):
    if message.chat.type != "private":
        await message.answer("👋 Напиши мне в личку, чтобы участвовать в игре 🙂")
        return

    await upsert_user(
        DB_PATH,
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name or "",
    )

    await message.answer(
        "✅ Ты зарегистрирован",
        reply_markup=user_menu(is_dev(message.from_user.id)),
    )


@dp.message(Command("menu"))
async def menu_cmd(message: Message):
    if message.chat.type != "private":
        await message.answer("📩 Открой личку с ботом и напиши /menu")
        return

    await message.answer(
        "Меню:",
        reply_markup=user_menu(is_dev(message.from_user.id)),
    )


@dp.message(Command("set_group"))
async def set_group_cmd(message: Message):
    if message.chat.type == "private":
        await message.answer("❗ Команда выполняется в группе")
        return

    if message.from_user.id != DEVELOPER_ID:
        await message.answer("⛔ Нет доступа")
        return

    await set_setting(DB_PATH, "GROUP_CHAT_ID", str(message.chat.id))
    await message.answer("✅ Группа успешно привязана")


# ---------------- DELETE ----------------
@dp.callback_query(F.data == "delete_me")
async def delete_me(call: CallbackQuery):
    await set_inactive(DB_PATH, call.from_user.id)
    await call.message.answer("❌ Удалён из игры")

# ---------------- SAY TO GROUP ----------------
@dp.callback_query(F.data == "dev_say_group")
async def dev_say_group(call: CallbackQuery):
    if not is_dev(call.from_user.id):
        return
    WAITING_GROUP_MESSAGE.add(call.from_user.id)
    await call.message.answer("✍️ Напиши текст — он уйдёт в группу")

@dp.message()
async def catch_group_text(message: Message):
    if message.from_user.id not in WAITING_GROUP_MESSAGE:
        return
    if message.chat.type != "private":
        return

    WAITING_GROUP_MESSAGE.remove(message.from_user.id)
    gid = await get_group_chat_id()
    if not gid:
        await message.answer("❌ Группа не привязана")
        return

    await bot.send_message(gid, message.text)
    await message.answer("✅ Отправлено в группу")

# ---------------- TASKS ----------------
@dp.callback_query(F.data.in_(["dev_task_now", "dev_task_3", "dev_task_5"]))
async def task_delay(call: CallbackQuery):
    if not is_dev(call.from_user.id):
        return

    seconds = {
        "dev_task_now": 5,
        "dev_task_3": 180,
        "dev_task_5": 300,
    }[call.data]

    run_at = await schedule_one_shot(seconds)
    await call.message.answer(f"⏰ Задание будет отправлено в {run_at.strftime('%H:%M:%S')}")

# ---------------- WAVES ----------------
async def pick_task_for_user(db_path: str, user_id: int, group_idx: int, tasks: list[str]) -> str:
    used = await get_used_tasks(db_path, user_id, group_idx)
    available = [t for t in tasks if t not in used]

    if not available:
        await reset_used_tasks_for_group(db_path, group_idx)
        available = tasks

    task = random.choice(available)
    await mark_task_used(db_path, user_id, group_idx, task)
    return task



async def run_wave():
    users = await get_active_users(DB_PATH)
    if len(users) < 4:
        return "⛔ Мало игроков"

    wave_index, active_idx, is_init = await get_wave_state_full(DB_PATH)

    if not is_init:
        ids = [u[0] for u in users]
        random.shuffle(ids)
        await init_wave_queue(DB_PATH, split_into_groups_max5(ids))
        wave_index, active_idx, _ = await get_wave_state_full(DB_PATH)

    groups = await get_wave_groups(DB_PATH)
    active = groups[active_idx]
    passive = groups[(active_idx + 1) % len(groups)]

    tasks = read_lines(EMOTIONS_FILE)
    pairs = make_wave_mapping(active, passive)

    log = [f"🌊 Волна {wave_index} запущена"]

    for a_id, t_id in pairs:
        task = await pick_task_for_user(DB_PATH, a_id, active_idx, tasks)

        await bot.send_message(
            a_id,
            f"🎯 *Твоя цель (если в задании это предусмотрено)*: {await get_user_label(DB_PATH, t_id)}\n\n"
            f"*Задание:*\n{task}"
        )

        log.append(
            f"{await get_user_label(DB_PATH, a_id)} → "
            f"{await get_user_label(DB_PATH, t_id)} | {task}"
        )

    # сообщение разработчику
    await bot.send_message(
        DEVELOPER_ID,
        "🚀 " + "\n".join(log)
    )

    return f"✅ Волна {wave_index} запущена"


@dp.callback_query(F.data == "dev_wave_run")
async def wave_run(call: CallbackQuery):
    await call.message.answer(await run_wave())

@dp.callback_query(F.data == "dev_users")
async def dev_users(call: CallbackQuery):
    if not is_dev(call.from_user.id):
        return

    users = await get_active_users(DB_PATH)
    if not users:
        await call.message.answer("👥 Активных игроков нет.")
        return

    lines = []
    for tg_id, username, full_name in users:
        line = f"• {full_name}"
        if username:
            line += f" (@{username})"
        line += f" [{tg_id}]"
        lines.append(line)

    await call.message.answer(
        "👥 Список игроков:\n\n" + "\n".join(lines)
    )


@dp.callback_query(F.data == "dev_status")
async def dev_status(call: CallbackQuery):
    if not is_dev(call.from_user.id):
        return

    users = await get_active_users(DB_PATH)
    groups = await get_wave_groups(DB_PATH)
    wave_index, active_idx, is_init = await get_wave_state_full(DB_PATH)
    chat_id = await get_setting(DB_PATH, "GROUP_CHAT_ID")

    msg = (
        "📊 *Статус игры*\n\n"
        f"👥 Игроков: {len(users)}\n"
        f"🌊 Групп: {len(groups)}\n"
        f"🌊 Волна: {wave_index}\n"
        f"🔥 ACTIVE группа: {active_idx + 1 if is_init else '-'}\n"
        f"💬 Группа привязана: {'да' if chat_id else 'нет'}"
    )

    await call.message.answer(msg, parse_mode="Markdown")

@dp.callback_query(F.data == "dev_treasure")
async def dev_treasure(call: CallbackQuery):
    if not is_dev(call.from_user.id):
        return

    gid = await get_group_chat_id()
    if not gid:
        await call.message.answer("❌ Группа не привязана (/set_group)")
        return

    riddles = read_lines(TREASURE_FILE)
    if not riddles:
        await call.message.answer("⚠️ treasure.txt пуст.")
        return

    riddle = random.choice(riddles)

    await bot.send_message(
        gid,
        "🪙 *Начинается событие «Золотоискатель»*\n\n" + riddle,
        parse_mode="Markdown"
    )

# ---------------- бля ----------------
@dp.callback_query(F.data == "santa_me")
async def santa_me(call: CallbackQuery):
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
async def dev_santa_start(call: CallbackQuery):
    if not is_dev(call.from_user.id):
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

    # лички
    for s, c in pairs.items():
        try:
            await bot.send_message(
                s,
                f"🎅 Твой подопечный:\n{await get_user_label(DB_PATH, c)}"
            )
        except:
            pass

    # организатор
    log = ["🎅 Санта запущен:"]
    for s, c in pairs.items():
        log.append(
            f"{await get_user_label(DB_PATH, s)} → {await get_user_label(DB_PATH, c)}"
        )

    await bot.send_message(ORGANIZER_ID, "\n".join(log))
    await call.message.answer("✅ Санта запущен.")


@dp.callback_query(F.data == "dev_wave_next")
async def dev_wave_next(call: CallbackQuery):
    if not is_dev(call.from_user.id):
        return

    await advance_wave(DB_PATH)
    res = await run_wave()
    await call.message.answer(res)


@dp.callback_query(F.data == "dev_wave_reset")
async def dev_wave_reset(call: CallbackQuery):
    if not is_dev(call.from_user.id):
        return

    await reset_waves(DB_PATH)
    await call.message.answer("🔄 Волны сброшены. Очередь будет пересобрана.")


@dp.callback_query(F.data == "dev_full_reset")
async def dev_full_reset(call: CallbackQuery):
    if not is_dev(call.from_user.id):
        return

    await full_reset(DB_PATH)
    await call.message.answer("🧹 Полный сброс выполнен.")


@dp.callback_query(F.data == "dev_reload_tasks")
async def dev_reload_tasks(call: CallbackQuery):
    if not is_dev(call.from_user.id):
        return

    count = await reload_tasks_from_file(DB_PATH, TASKS_FILE)
    if count == 0:
        await call.message.answer("⚠️ Файл заданий пуст или отсутствует.")
    else:
        await call.message.answer(f"✅ Задания перезагружены: {count} шт.")






# ---------------- MAIN ----------------
async def main():
    await init_db(DB_PATH)
    await load_tasks_if_empty(DB_PATH, TASKS_FILE)
    await reschedule_cron()
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
