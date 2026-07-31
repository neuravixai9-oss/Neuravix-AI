"""
Секретные команды (пасхалки) — Neuravix AI.

Полностью скрытая, аддитивная система: НЕ регистрируется через BotFather,
НЕ отображается ни в одном меню бота, не меняет ни одного существующего
роутера или обработчика. Один универсальный обработчик покрывает ВСЕ команды
из config.SECRET_COMMANDS — чтобы добавить 31-ю и далее команду, достаточно
дописать запись в config.py, сюда лезть не нужно.
"""
import random
from datetime import datetime

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from database.db import (
    get_or_create_user, mark_secret_command_found, count_found_secret_commands,
)
from config import SECRET_COMMANDS, SECRET_ACHIEVEMENTS, SECRET_COMMANDS_TOTAL, VERSION

router = Router()

FORTUNES = [
    "Сегодня твой день — не упусти момент.",
    "Скоро тебя ждёт приятный сюрприз.",
    "Задуманное обязательно сбудется.",
    "Будь смелее — риск оправдан.",
    "Хорошие новости уже в пути.",
    "Сегодня отличный день, чтобы начать что-то новое.",
    "Прислушайся к интуиции — она не подводит.",
    "Терпение — ключ к успеху в ближайшие дни.",
    "Тебя ждёт интересная встреча или разговор.",
    "Всё идёт по плану, даже если кажется иначе.",
]


def _progress_bar(found: int, total: int, length: int = 10) -> str:
    if not total:
        return "░" * length
    filled = max(0, min(length, round(found / total * length)))
    return "█" * filled + "░" * (length - filled)


def _next_reward(found: int) -> int | None:
    for threshold, _ in SECRET_ACHIEVEMENTS:
        if found < threshold:
            return threshold
    return None


async def _special_response(key: str, message: Message) -> str:
    """Команды с динамическим содержимым (случайное предсказание, время и т.п.)."""
    if key == "fortune":
        return f"🔮 <b>Предсказание:</b>\n\n<i>{random.choice(FORTUNES)}</i>"

    if key == "version":
        return (
            "⚙️ <b>Neuravix AI — секретное окно версии</b>\n\n"
            f"Версия движка: <code>{VERSION}</code>\n"
            "Статус: 🟢 Онлайн\n\n"
            "Поздравляю, ты нашёл то, что видит обычно только владелец 👀"
        )

    if key == "whoami":
        u = await get_or_create_user(message.from_user.id)
        uname = f"@{u['username']}" if u.get("username") else "не указан"
        return (
            "🕵️ <b>Сканирование личности...</b>\n\n"
            f"👤 Имя: <b>{message.from_user.first_name or 'Незнакомец'}</b>\n"
            f"🆔 ID: <code>{u['telegram_id']}</code>\n"
            f"🔗 Username: {uname}\n"
            f"💎 Тариф: <b>{u.get('subscription', 'free')}</b>\n\n"
            "Личность подтверждена ✅"
        )

    if key == "time":
        now = datetime.now().strftime("%H:%M:%S · %d.%m.%Y")
        return f"⏰ Проверяю время...\n\n<b>{now}</b>\n\nСамое лучшее время — сейчас."

    text = SECRET_COMMANDS.get(key)
    return text if text else "🤷 Секрет пока не готов."


@router.message(Command(commands=list(SECRET_COMMANDS.keys())))
async def handle_secret_command(message: Message, command: CommandObject):
    key = (command.command or "").lower()
    if key not in SECRET_COMMANDS:
        return  # на всякий случай — не наша команда

    reply = await _special_response(key, message)
    await message.answer(reply, parse_mode="HTML")

    is_new = await mark_secret_command_found(message.from_user.id, key)
    if not is_new:
        return  # уже находил раньше — прогресс не растёт и уведомление не дублируется

    found = await count_found_secret_commands(message.from_user.id)
    total = SECRET_COMMANDS_TOTAL
    bar = _progress_bar(found, total)

    notify = (
        "🎉 <b>Новая секретная команда найдена!</b>\n\n"
        "🏆 +1 к коллекции\n\n"
        f"{bar}\n"
        f"Найдено:\n<b>{found} / {total}</b>"
    )
    next_reward = _next_reward(found)
    if next_reward:
        notify += f"\n\nСледующая награда:\n<b>{next_reward} команд</b>"
    await message.answer(notify, parse_mode="HTML")

    # Достижение за очередной порог
    for threshold, title in SECRET_ACHIEVEMENTS:
        if found == threshold:
            await message.answer(
                f"🏆 <b>Новое достижение!</b>\n\n«{title}»",
                parse_mode="HTML",
            )
            break

    # Все команды найдены — финальное поздравление
    if found == total:
        await message.answer(
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "👑 <b>Поздравляем!</b>\n\n"
            "Вы нашли ВСЕ секретные команды Neuravix AI!\n\n"
            "🏆 Получено достижение:\n«Хранитель Neuravix»\n\n"
            "Спасибо, что исследовали все секреты бота ❤️",
            parse_mode="HTML",
        )
