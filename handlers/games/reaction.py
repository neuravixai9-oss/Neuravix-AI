"""Кто быстрее нажмёт — real-time реакция."""
import asyncio
import random
import time
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from handlers.games.engine import outcome_text, BOT_ID

# Хранит задачи таймеров для каждой игры
_timers: dict[str, asyncio.Task] = {}
# Хранит время показа кнопки: game_id -> float (monotonic)
_shown_at: dict[str, float] = {}


def initial_state(player1_id, player2_id, mode, player1_name="Игрок", player2_name="Бот", extra=None, **kwargs) -> dict:
    return {
        "round": 0,
        "max_rounds": 5,
        "p1_score": 0,
        "p2_score": 0,
        "p1_times": [],
        "p2_times": [],
        "phase": "waiting",  # waiting | ready | done
        "last_result": None,
        "player1_name": player1_name,
        "player2_name": player2_name,
        "mode": mode,
    }


def render(session: dict, for_user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    state = session["state"]
    game_id = session["game_id"]
    p1 = session["player1_id"]
    status = session["status"]
    is_done = status == "finished"
    phase = state.get("phase", "waiting")

    p1_name = state.get("player1_name", "Игрок 1")
    p2_name = state.get("player2_name", "Игрок 2")
    p1s = state["p1_score"]
    p2s = state["p2_score"]
    rnd = state["round"]
    max_rnd = state["max_rounds"]
    last = state.get("last_result", "")

    if is_done:
        out = state.get("_outcome", "draw")
        out_txt = outcome_text(out, session, for_user_id)
        avg_p1 = (sum(state["p1_times"]) / len(state["p1_times"]) * 1000) if state["p1_times"] else 0
        avg_p2 = (sum(state["p2_times"]) / len(state["p2_times"]) * 1000) if state["p2_times"] else 0
        header = (
            f"⚡ <b>Кто быстрее нажмёт</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{out_txt}\n\n"
            f"🔵 {p1_name}: {p1s} побед | ср. {avg_p1:.0f}мс\n"
            f"🔴 {p2_name}: {p2s} побед | ср. {avg_p2:.0f}мс\n\n"
        )
        buttons = [
            [InlineKeyboardButton(text="🔄 Реванш", callback_data=f"game:rematch:{game_id}")],
            [InlineKeyboardButton(text="📋 Все игры", callback_data="menu:games")],
        ]
        return header, InlineKeyboardMarkup(inline_keyboard=buttons)

    header = f"⚡ <b>Кто быстрее нажмёт</b> (раунд {rnd + 1}/{max_rnd})\n━━━━━━━━━━━━━━━━━━━━\n\n"
    players_line = f"🔵 <b>{p1_name}</b>: {p1s}  |  🔴 <b>{p2_name}</b>: {p2s}\n\n"
    if last:
        header += f"⏱ {last}\n\n"

    buttons = []
    if phase == "waiting":
        header += "⏳ <b>Готовься!</b>\nЖди кнопку «ЖАТЬ!» — она появится неожиданно.\n\nНажмите «Готов» чтобы начать раунд:"
        buttons.append([InlineKeyboardButton(text="▶️ Начать раунд!", callback_data=f"g:reaction:{game_id}:start")])
    elif phase == "ready":
        header += "⚡ <b>ЖАТЬ!</b> Нажимай как можно быстрее!"
        buttons.append([InlineKeyboardButton(text="⚡⚡ ЖАТЬ! ⚡⚡", callback_data=f"g:reaction:{game_id}:tap")])
    elif phase == "early":
        header += "😬 <b>Слишком рано!</b> Подожди кнопки «ЖАТЬ!»"
        buttons.append([InlineKeyboardButton(text="▶️ Попробовать снова", callback_data=f"g:reaction:{game_id}:start")])

    buttons.append([InlineKeyboardButton(text="📋 Все игры", callback_data="menu:games")])
    text = header + players_line
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


def handle_move(session: dict, payload: str, user_id: int) -> tuple[dict, str | None]:
    state = session["state"]
    p1 = session["player1_id"]
    is_p1 = user_id == p1

    if payload == "start":
        state["phase"] = "waiting"
        # Таймер запустит основной обработчик через asyncio
        return session, None

    if payload == "tap":
        if state.get("phase") != "ready":
            # Слишком рано
            state["phase"] = "early"
            return session, None

        reaction_time = time.monotonic() - _shown_at.get(session["game_id"], time.monotonic())
        rt_ms = reaction_time * 1000

        state["round"] = state.get("round", 0) + 1
        if is_p1:
            state["p1_score"] += 1
            state["p1_times"].append(reaction_time)
            state["last_result"] = f"🔵 {state['player1_name']} победил! Время: {rt_ms:.0f}мс"
        else:
            state["p2_score"] += 1
            state["p2_times"].append(reaction_time)
            state["last_result"] = f"🔴 {state['player2_name']} победил! Время: {rt_ms:.0f}мс"

        state["phase"] = "waiting"
        _shown_at.pop(session["game_id"], None)

        if state["round"] >= state["max_rounds"]:
            p1s = state["p1_score"]
            p2s = state["p2_score"]
            if p1s > p2s:
                out = "win_p1"
            elif p2s > p1s:
                out = "win_p2"
            else:
                out = "draw"
            state["_outcome"] = out
            return session, out

    return session, None


def bot_move(session: dict) -> str | None:
    # Бот реагирует мгновенно
    return "tap"


async def schedule_reaction_round(session: dict, bot, delay: float = None):
    """Запускает раунд с задержкой, затем показывает кнопку."""
    game_id = session["game_id"]
    if delay is None:
        delay = random.uniform(2.0, 5.0)
    await asyncio.sleep(delay)

    from database.db import get_game_session, update_game_session
    s = await get_game_session(game_id)
    if not s or s["status"] != "active":
        return
    state = s["state"]
    state["phase"] = "ready"
    _shown_at[game_id] = time.monotonic()
    await update_game_session(game_id, state=state)

    from handlers.games.engine import deliver_to_both
    await deliver_to_both(s, bot)

    # Бот-соперник
    if s.get("mode") == "bot":
        await asyncio.sleep(random.uniform(0.3, 1.5))
        s2 = await get_game_session(game_id)
        if s2 and s2["status"] == "active" and s2["state"].get("phase") == "ready":
            from handlers.games.engine import process_move
            await process_move(s2, "tap", BOT_ID, bot)
