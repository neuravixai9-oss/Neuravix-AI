"""Четыре в ряд — 6 строк × 7 столбцов. Улучшенный бот с оценкой угроз."""
import random
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from handlers.games.engine import outcome_text, BOT_ID

ROWS, COLS = 6, 7
P1_CHIP = "🔴"
P2_CHIP = "🟡"
EMPTY = "⚫"

# Веса столбцов: центр важнее
COL_WEIGHTS = [1, 2, 3, 5, 3, 2, 1]


def initial_state(player1_id, player2_id, mode, player1_name="Игрок", player2_name="Бот", extra=None, **kwargs) -> dict:
    return {
        "board": [[0] * COLS for _ in range(ROWS)],
        "player1_name": player1_name,
        "player2_name": player2_name,
        "mode": mode,
    }


def _drop(board, col, sym) -> list | None:
    for r in range(ROWS - 1, -1, -1):
        if board[r][col] == 0:
            new = [row[:] for row in board]
            new[r][col] = sym
            return new
    return None


def _check_win(board, sym) -> bool:
    for r in range(ROWS):
        for c in range(COLS):
            if all(c + d < COLS and board[r][c + d] == sym for d in range(4)):
                return True
            if all(r + d < ROWS and board[r + d][c] == sym for d in range(4)):
                return True
            if all(r + d < ROWS and c + d < COLS and board[r + d][c + d] == sym for d in range(4)):
                return True
            if all(r + d < ROWS and c - d >= 0 and board[r + d][c - d] == sym for d in range(4)):
                return True
    return False


def _is_full(board) -> bool:
    return all(board[0][c] != 0 for c in range(COLS))


def _count_threats(board, sym, length=3) -> int:
    """Считает количество строк из `length` символов sym + пустые клетки."""
    count = 0
    for r in range(ROWS):
        for c in range(COLS):
            dirs = [(0, 1), (1, 0), (1, 1), (1, -1)]
            for dr, dc in dirs:
                cells = []
                for d in range(4):
                    nr, nc = r + dr * d, c + dc * d
                    if 0 <= nr < ROWS and 0 <= nc < COLS:
                        cells.append(board[nr][nc])
                if len(cells) == 4:
                    syms = sum(1 for x in cells if x == sym)
                    empty = sum(1 for x in cells if x == 0)
                    if syms == length and empty == 4 - length:
                        count += 1
    return count


def _score_board(board, sym) -> int:
    """Оценочная функция позиции для sym."""
    opp = 1 if sym == 2 else 2
    score = 0
    # Угрозы на 3 в ряд
    score += _count_threats(board, sym, 3) * 10
    score -= _count_threats(board, opp, 3) * 8
    # Угрозы на 2 в ряд
    score += _count_threats(board, sym, 2) * 2
    # Центральная колонка
    center = [board[r][3] for r in range(ROWS)]
    score += center.count(sym) * 6
    return score


def render(session: dict, for_user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    state = session["state"]
    board = state["board"]
    game_id = session["game_id"]
    p1 = session["player1_id"]
    status = session["status"]
    turn = session.get("current_turn")
    is_my_turn = turn == for_user_id and status == "active"
    is_done = status == "finished"

    p1_name = state.get("player1_name", "Игрок 1")
    p2_name = state.get("player2_name", "Игрок 2")

    if is_done:
        out = outcome_text(state.get("_outcome", "draw"), session, for_user_id)
        header = f"🟡 <b>Четыре в ряд</b>\n━━━━━━━━━━━━━━━━━━━━\n\n{out}\n\n"
    else:
        turn_name = p1_name if turn == p1 else p2_name
        whose = "👉 Твой ход!" if is_my_turn else f"⏳ Ход: <b>{turn_name}</b>"
        header = f"🟡 <b>Четыре в ряд</b>\n━━━━━━━━━━━━━━━━━━━━\n\n{whose}\n\n"

    p1_arrow = " 👈" if turn == p1 and not is_done else ""
    p2_arrow = " 👈" if turn != p1 and not is_done else ""
    players_line = f"{P1_CHIP} <b>{p1_name}</b>{p1_arrow}  vs  {P2_CHIP} <b>{p2_name}</b>{p2_arrow}\n\n"

    board_lines = []
    col_nums = " ".join(str(c + 1) for c in range(COLS))
    board_lines.append(col_nums)
    for r in range(ROWS):
        row_str = ""
        for c in range(COLS):
            v = board[r][c]
            row_str += (P1_CHIP if v == 1 else P2_CHIP if v == 2 else EMPTY)
        board_lines.append(row_str)

    buttons = []
    if is_my_turn:
        col_btns = []
        for c in range(COLS):
            avail = board[0][c] == 0
            label = str(c + 1) if avail else "✖"
            data = f"g:connect4:{game_id}:{c}" if avail else f"g:connect4:{game_id}:noop"
            col_btns.append(InlineKeyboardButton(text=label, callback_data=data))
        buttons.append(col_btns)

    if is_done:
        buttons.append([InlineKeyboardButton(text="🔄 Реванш", callback_data=f"game:rematch:{game_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="🏳️ Сдаться", callback_data=f"g:connect4:{game_id}:surrender")])
    buttons.append([InlineKeyboardButton(text="📋 Все игры", callback_data="menu:games")])

    board_text = "\n".join(board_lines)
    text = header + players_line + f"<code>{board_text}</code>"
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


def handle_move(session: dict, payload: str, user_id: int) -> tuple[dict, str | None]:
    if payload == "noop":
        return session, None
    if payload == "surrender":
        out = "win_p2" if user_id == session["player1_id"] else "win_p1"
        session["state"]["_outcome"] = out
        return session, out
    try:
        col = int(payload)
    except ValueError:
        return session, None

    board = session["state"]["board"]
    p1 = session["player1_id"]
    sym = 1 if user_id == p1 else 2
    new_board = _drop(board, col, sym)
    if new_board is None:
        return session, None
    session["state"]["board"] = new_board

    if _check_win(new_board, sym):
        out = "win_p1" if sym == 1 else "win_p2"
        session["state"]["_outcome"] = out
        return session, out
    if _is_full(new_board):
        session["state"]["_outcome"] = "draw"
        return session, "draw"

    p2 = session.get("player2_id") or BOT_ID
    session["current_turn"] = p2 if user_id == p1 else p1
    return session, None


def bot_move(session: dict) -> str | None:
    board = session["state"]["board"]
    free = [c for c in range(COLS) if board[0][c] == 0]
    if not free:
        return None

    # 1. Выиграть немедленно
    for c in free:
        nb = _drop(board, c, 2)
        if nb and _check_win(nb, 2):
            return str(c)

    # 2. Заблокировать победу игрока
    for c in free:
        nb = _drop(board, c, 1)
        if nb and _check_win(nb, 1):
            return str(c)

    # 3. Не давать игроку выиграть на следующем ходу (ловушки)
    safe = []
    for c in free:
        nb = _drop(board, c, 2)
        if nb:
            # Проверяем что противник не выигрывает сразу после
            opp_win = False
            for c2 in range(COLS):
                if nb[0][c2] == 0:
                    nb2 = _drop(nb, c2, 1)
                    if nb2 and _check_win(nb2, 1):
                        opp_win = True
                        break
            if not opp_win:
                safe.append(c)

    candidates = safe if safe else free

    # 4. Выбираем ход с наилучшей оценкой позиции
    best_score = None
    best_cols = []
    for c in candidates:
        nb = _drop(board, c, 2)
        if nb:
            s = _score_board(nb, 2) + COL_WEIGHTS[c]
            if best_score is None or s > best_score:
                best_score = s
                best_cols = [c]
            elif s == best_score:
                best_cols.append(c)

    return str(random.choice(best_cols)) if best_cols else str(random.choice(free))
