"""Угадай число — от 1 до 100."""
import random
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from handlers.games.engine import outcome_text, BOT_ID


def initial_state(player1_id, player2_id, mode, player1_name="Игрок", player2_name="Бот", extra=None, **kwargs) -> dict:
    secret = random.randint(1, 100)
    return {
        "secret": secret,
        "attempts": 0,
        "max_attempts": 7,
        "last_hint": None,
        "history": [],
        "player1_name": player1_name,
        "player2_name": player2_name,
        "mode": mode,
    }


# Ожидающие ввода пользователей (user_id -> game_id)
pending_guess: dict[int, str] = {}


def render(session: dict, for_user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    state = session["state"]
    game_id = session["game_id"]
    p1 = session["player1_id"]
    status = session["status"]
    is_done = status == "finished"

    attempts = state.get("attempts", 0)
    max_att = state.get("max_attempts", 7)
    last_hint = state.get("last_hint", "")
    history = state.get("history", [])
    secret = state.get("secret", "?")

    p1_name = state.get("player1_name", "Игрок")

    if is_done:
        out = state.get("_outcome", "lose")
        out_txt = outcome_text(out, session, for_user_id)
        header = (
            f"🔢 <b>Угадай число</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{out_txt}\n"
            f"🎯 Загаданное число было: <b>{secret}</b>\n\n"
        )
    else:
        remain = max_att - attempts
        bar = "💚" * remain + "🖤" * attempts
        header = (
            f"🔢 <b>Угадай число (1–100)</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>{p1_name}</b>\n"
            f"Попыток осталось: {bar} (<b>{remain}</b>)\n\n"
        )

    if last_hint:
        header += f"💡 <b>Подсказка:</b> {last_hint}\n\n"
    if history:
        header += "📋 <b>Предыдущие попытки:</b>\n"
        for entry in history[-5:]:
            header += f"  • {entry}\n"
        header += "\n"

    if not is_done:
        header += "<i>Напиши число в чат (1–100):</i>"
        pending_guess[for_user_id] = game_id

    buttons = []
    if is_done:
        buttons.append([InlineKeyboardButton(text="🔄 Играть снова", callback_data=f"game:rematch:{game_id}")])
    buttons.append([InlineKeyboardButton(text="📋 Все игры", callback_data="menu:games")])

    return header, InlineKeyboardMarkup(inline_keyboard=buttons)


def handle_move(session: dict, payload: str, user_id: int) -> tuple[dict, str | None]:
    state = session["state"]
    try:
        guess = int(payload)
    except ValueError:
        return session, None

    if not (1 <= guess <= 100):
        return session, None

    secret = state["secret"]
    state["attempts"] = state.get("attempts", 0) + 1
    attempts = state["attempts"]
    max_att = state.get("max_attempts", 7)

    if guess == secret:
        state["_outcome"] = "win"
        state["last_hint"] = f"✅ Угадал! Это <b>{secret}</b>"
        state["history"].append(f"{guess} — ✅ Угадано!")
        return session, "win"

    diff = abs(guess - secret)
    if diff <= 3:
        hint = f"{guess} — 🔥 Очень горячо!"
    elif diff <= 10:
        hint = f"{guess} — 🌡 Тепло"
    elif diff <= 25:
        hint = f"{guess} — 🌬 Прохладно"
    else:
        hint = f"{guess} — ❄️ Холодно"

    direction = "👆 Больше" if guess < secret else "👇 Меньше"
    state["last_hint"] = f"{hint} ({direction})"
    state["history"].append(f"{guess} — {hint}")

    if attempts >= max_att:
        state["_outcome"] = "lose"
        return session, "lose"

    return session, None


def bot_move(session: dict) -> str | None:
    # Бот сам не отгадывает в этой игре (однопользовательская)
    return None
