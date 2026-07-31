"""Орёл и решка."""
import random
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from handlers.games.engine import outcome_text, BOT_ID


def initial_state(player1_id, player2_id, mode, player1_name="Игрок", player2_name="Бот", extra=None, **kwargs) -> dict:
    return {
        "player1_wins": 0,
        "player2_wins": 0,
        "rounds": 0,
        "max_rounds": 5,
        "last_result": None,
        "player1_choice": None,
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
    turn = session.get("current_turn")
    is_my_turn = turn == for_user_id and status == "active"

    p1_name = state.get("player1_name", "Игрок 1")
    p2_name = state.get("player2_name", "Игрок 2")
    p1w = state["player1_wins"]
    p2w = state["player2_wins"]
    rounds = state["rounds"]
    max_rounds = state["max_rounds"]
    last = state.get("last_result")

    if is_done:
        out = state.get("_outcome", "draw")
        out_txt = outcome_text(out, session, for_user_id)
        header = f"🪙 <b>Орёл и решка</b>\n━━━━━━━━━━━━━━━━━━━━\n\n{out_txt}\n\n"
    else:
        header = f"🪙 <b>Орёл и решка</b> (раунд {rounds + 1}/{max_rounds})\n━━━━━━━━━━━━━━━━━━━━\n\n"
        if is_my_turn:
            header += "👉 <b>Твой выбор:</b>"
        else:
            header += f"⏳ Ход: <b>{p2_name if turn != p1 else p1_name}</b>"
        header += "\n\n"

    if last:
        header += f"🎰 <b>Результат:</b> {last}\n\n"

    score_bar = f"{'🪙' * p1w}{'🔘' * (max_rounds - p1w - p2w - max(0, max_rounds - rounds))}{'🔘' * p2w}" if rounds else ""
    players_line = f"🔵 <b>{p1_name}</b>: {p1w} побед  |  🔴 <b>{p2_name}</b>: {p2w} побед\n\n"

    buttons = []
    if is_my_turn and not is_done:
        buttons.append([
            InlineKeyboardButton(text="🦅 Орёл", callback_data=f"g:coinflip:{game_id}:heads"),
            InlineKeyboardButton(text="🔵 Решка", callback_data=f"g:coinflip:{game_id}:tails"),
        ])
    if is_done:
        from handlers.games.engine import end_game_buttons
        buttons.extend(end_game_buttons(game_id))
    else:
        from handlers.games.engine import in_progress_buttons
        buttons.append(in_progress_buttons(game_id))

    text = header + players_line
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


def handle_move(session: dict, payload: str, user_id: int) -> tuple[dict, str | None]:
    state = session["state"]
    p1 = session["player1_id"]
    p2 = session.get("player2_id") or BOT_ID
    is_p1 = user_id == p1
    mode = session.get("mode", "bot")

    if payload in ("heads", "tails"):
        # Серверная проверка очереди хода — раньше её не было, из-за чего
        # ход НИКОГДА не переключался ко второму игроку (current_turn не
        # менялся), и в режиме с другом второй игрок фактически не мог
        # ходить, а победы всегда засчитывались первому игроку.
        if user_id != session.get("current_turn"):
            return session, None

        state["player1_choice"] = payload  # для истории/отладки
        result = random.choice(["heads", "tails"])

        coin = "🦅 Орёл" if result == "heads" else "🔵 Решка"
        choice_str = "🦅 Орёл" if payload == "heads" else "🔵 Решка"

        guesser_won = (result == payload)
        who = state.get("player1_name") if is_p1 else state.get("player2_name")
        state["last_result"] = (
            f"{coin} | {who} выбрал: {choice_str} → "
            f"{'✅ Победа' if guesser_won else '❌ Поражение'}"
        )

        if guesser_won:
            if is_p1:
                state["player1_wins"] += 1
            else:
                state["player2_wins"] += 1
        else:
            if is_p1:
                state["player2_wins"] += 1
            else:
                state["player1_wins"] += 1

        state["rounds"] += 1
        rounds = state["rounds"]
        max_rounds = state["max_rounds"]

        if rounds >= max_rounds or max(state["player1_wins"], state["player2_wins"]) > max_rounds // 2:
            p1w = state["player1_wins"]
            p2w = state["player2_wins"]
            if p1w > p2w:
                out = "win_p1"
            elif p2w > p1w:
                out = "win_p2"
            else:
                out = "draw"
            state["_outcome"] = out
            return session, out

        # Следующий раунд — очередь переходит к другому игроку (в bot-режиме
        # это BOT_ID, и process_move сам вызовет bot_move()).
        session["current_turn"] = p2 if is_p1 else p1
        return session, None

    return session, None


def bot_move(session: dict) -> str | None:
    return random.choice(["heads", "tails"])
