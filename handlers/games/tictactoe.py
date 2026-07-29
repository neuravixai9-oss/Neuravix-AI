"""Крестики-нолики 3×3."""
import random
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from handlers.games.engine import outcome_text, end_kb, BOT_ID

WINS = [
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
]

CELL_SYMBOLS = {0: "⬜", 1: "❌", 2: "⭕"}


def initial_state(player1_id, player2_id, mode, player1_name="Игрок", player2_name="Бот", extra=None, **kwargs) -> dict:
    return {
        "board": [0] * 9,
        "player1_name": player1_name,
        "player2_name": player2_name,
        "mode": mode,
        "move_count": 0,
    }


def _check_winner(board: list) -> int | None:
    for a, b, c in WINS:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    return None


def render(session: dict, for_user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    state = session["state"]
    board = state["board"]
    mode = session.get("mode", "bot")
    game_id = session["game_id"]
    p1 = session["player1_id"]
    p2 = session.get("player2_id")
    status = session["status"]

    p1_name = state.get("player1_name", "Игрок 1")
    p2_name = state.get("player2_name", "Игрок 2")

    turn = session.get("current_turn")
    is_my_turn = (turn == for_user_id) and status == "active"

    winner = _check_winner(board)
    is_done = status == "finished"

    # Header
    if is_done:
        out = outcome_text(session.get("state", {}).get("_outcome", "draw"), session, for_user_id)
        header = f"❌⭕ <b>Крестики-нолики</b>\n━━━━━━━━━━━━━━━━━━━━\n\n{out}\n\n"
    else:
        turn_name = p1_name if turn == p1 else p2_name
        whose = "👉 Твой ход!" if is_my_turn else f"⏳ Ход: <b>{turn_name}</b>"
        header = f"❌⭕ <b>Крестики-нолики</b>\n━━━━━━━━━━━━━━━━━━━━\n\n{whose}\n\n"

    # Players line
    p1_sym = "❌"
    p2_sym = "⭕"
    p1_arrow = " 👈" if (turn == p1 and not is_done) else ""
    p2_arrow = " 👈" if (turn != p1 and not is_done and p2) else ""
    players_line = f"❌ <b>{p1_name}</b>{p1_arrow}  vs  ⭕ <b>{p2_name}</b>{p2_arrow}\n\n"

    # Board
    rows = []
    for r in range(3):
        row_btns = []
        for c in range(3):
            idx = r * 3 + c
            val = board[idx]
            if val == 1:
                label = "❌"
            elif val == 2:
                label = "⭕"
            else:
                label = "·"
            if is_my_turn and val == 0:
                data = f"g:tictactoe:{game_id}:{idx}"
            else:
                data = f"g:tictactoe:{game_id}:noop"
            row_btns.append(InlineKeyboardButton(text=label, callback_data=data))
        rows.append(row_btns)

    if is_done:
        rows.append([InlineKeyboardButton(text="🔄 Реванш", callback_data=f"game:rematch:{game_id}")])
        rows.append([InlineKeyboardButton(text="📋 Все игры", callback_data="menu:games")])
    else:
        rows.append([InlineKeyboardButton(text="🏳️ Сдаться", callback_data=f"g:tictactoe:{game_id}:surrender")])
        rows.append([InlineKeyboardButton(text="📋 Все игры", callback_data="menu:games")])

    text = header + players_line
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def handle_move(session: dict, payload: str, user_id: int) -> tuple[dict, str | None]:
    if payload == "noop":
        return session, None
    if payload == "surrender":
        session["state"]["_outcome"] = "win_p2" if user_id == session["player1_id"] else "win_p1"
        return session, session["state"]["_outcome"]

    board = list(session["state"]["board"])
    try:
        idx = int(payload)
    except ValueError:
        return session, None
    if board[idx] != 0:
        return session, None

    p1 = session["player1_id"]
    symbol = 1 if user_id == p1 else 2
    board[idx] = symbol
    session["state"]["board"] = board
    session["state"]["move_count"] = session["state"].get("move_count", 0) + 1

    winner = _check_winner(board)
    if winner:
        outcome = "win_p1" if winner == 1 else "win_p2"
        session["state"]["_outcome"] = outcome
        return session, outcome
    if all(c != 0 for c in board):
        session["state"]["_outcome"] = "draw"
        return session, "draw"

    # Переключаем ход
    p2 = session.get("player2_id") or BOT_ID
    session["current_turn"] = p2 if user_id == p1 else p1
    return session, None


def bot_move(session: dict) -> str | None:
    board = session["state"]["board"]
    p2_sym = 2
    p1_sym = 1

    # Проверяем выигрышный ход бота
    for i in range(9):
        if board[i] == 0:
            test = list(board)
            test[i] = p2_sym
            if _check_winner(test):
                return str(i)

    # Блокируем выигрышный ход игрока
    for i in range(9):
        if board[i] == 0:
            test = list(board)
            test[i] = p1_sym
            if _check_winner(test):
                return str(i)

    # Центр
    if board[4] == 0:
        return "4"

    # Углы
    corners = [i for i in (0, 2, 6, 8) if board[i] == 0]
    if corners:
        return str(random.choice(corners))

    # Любая свободная
    free = [i for i in range(9) if board[i] == 0]
    return str(random.choice(free)) if free else None
