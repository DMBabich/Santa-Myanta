from aiogram.utils.keyboard import InlineKeyboardBuilder

def user_menu(is_developer: bool):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎅 Санта", callback_data="santa_me")
    kb.button(text="❌ Удалиться", callback_data="delete_me")
    if is_developer:
        kb.button(text="🧠 Запустить Санту", callback_data="dev_santa_start")
        kb.button(text="⏰ Задание +5 мин", callback_data="dev_task_5")
        kb.button(text="⏰ Задание +10 мин", callback_data="dev_task_10")
        kb.button(text="⏰ Задание +15 мин", callback_data="dev_task_15")
        kb.button(text="🌊 Запустить волну", callback_data="dev_wave_run")
        kb.button(text="➡️ Следующая волна", callback_data="dev_wave_next")
        kb.button(text="🔄 Сбросить волны", callback_data="dev_wave_reset")
        kb.button(text="🪙 Запустить сокровище", callback_data="dev_treasure")
        kb.button(text="👥 Список игроков", callback_data="dev_users")
        kb.button(text="📊 Статус игры", callback_data="dev_status")
        kb.button(text="🧹 Полный сброс (DEV)", callback_data="dev_full_reset")
        kb.button(text="🔄 Перезагрузить задания", callback_data="dev_reload_tasks")
    kb.adjust(2)
    return kb.as_markup()
