import random
from aiogram import Bot
from db import get_active_users, get_random_task, log_sent_task, get_user_label

async def job_send_random_task(bot: Bot, db_path: str, organizer_id: int):
    users = await get_active_users(db_path)
    if not users:
        await bot.send_message(organizer_id, "⛔ Нет активных участников — задание не отправлено.")
        return

    task = await get_random_task(db_path)
    if not task:
        await bot.send_message(organizer_id, "⛔ Нет заданий в tasks. Заполни tasks.txt и перезапусти.")
        return

    tg_id, username, full_name = random.choice(users)

    user_msg = (
        "🔔 *Тайная активность!*\n\n"
        f"{task}\n\n"
        "_Это видишь только ты_"
    )
    org_msg = (
        "📌 Назначена активность\n"
        f"Кому: {full_name}" + (f" (@{username})" if username else "") + "\n"
        f"Задание: {task}"
    )

    try:
        await bot.send_message(tg_id, user_msg, parse_mode="Markdown")
        await bot.send_message(organizer_id, org_msg)
        await log_sent_task(db_path, tg_id, task)
    except Exception as e:
        await bot.send_message(organizer_id, f"⚠️ Не смог отправить задание пользователю {tg_id}. Ошибка: {e}")
