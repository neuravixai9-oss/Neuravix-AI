"""
Игра на память.
Три уровня сложности (разный размер поля), умный бот, который запоминает
все увиденные карты, и честный показ несовпавшей пары карточек перед тем,
как они закроются обратно (это чинит старый баг, когда вторая карточка
визуально "не открывалась").
"""
import random
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from handlers.games.engine import outcome_text, BOT_ID

# 18 уникальных эмодзи хватает на самый большой (сложный) режим — 18 пар
EMOJIS = [
    "🐶", "🐱", "🐸", "🦁", "🐯", "🦊", "🐺", "🐻", "🐼",
    "🐨", "🐵", "🐰", "🦉", "🦄", "🐷", "🐮", "🐔", "🐙",
]
BACK = "🔲"

DIFFICULTY = {
    "easy":   {"rows": 4, "cols": 4, "label": "🟢 Лёгкий · 4×4"},
    "medium": {"rows": 4, "cols": 6, "label": "🟡 Средний · 4×6"},
    "hard":   {"rows": 6, "cols": 6, "label": "🔴 Сложный · 6×6"},
}
DEFAULT_DIFFICULTY = "easy"


def initial_state(player1_id, player2_id, mode, player1_name="Игрок", player2_name="Бот", extra=None, **kwargs) -> dict:
    difficulty = extra if extra in DIFFICULTY else DEFAULT_DIFFICULTY
    cfg = DIFFICULTY[difficulty]
    rows, cols = cfg["rows"], cfg["cols"]
    n = rows * cols
    pairs = n // 2

    cards = EMOJIS[:pairs] * 2
    random.shuffle(cards)

    return {
        "cards": cards,
        "rows": rows,
        "cols": cols,
        "difficulty": difficulty,
        "revealed": [False] * n,
        "matched": [False] * n,
        "player1_score": 0,
        "player2_score": 0,
        "first_pick": None,
        "player1_name": player1_name,
        "player2_name": player2_name,
        "mode": mode,
        "bot_seen": {},          # str(idx) -> emoji — бот запоминает все открытые карты
    }


def render(session: dict, for_user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    state = session["state"]
    cards = state["cards"]
    revealed = state["revealed"]
    matched = state["matched"]
    rows, cols = state["rows"], state["cols"]
    game_id = session["game_id"]
    p1 = session["player1_id"]
    status = session["status"]
    turn = session.get("current_turn")
    is_my_turn = turn == for_user_id and status == "active"
    is_done = status == "finished"

    p1_name = state.get("player1_name", "Игрок 1")
    p2_name = state.get("player2_name", "Игрок 2")
    p1s = state["player1_score"]
    p2s = state["player2_score"]
    diff_label = DIFFICULTY.get(state.get("difficulty", DEFAULT_DIFFICULTY), DIFFICULTY[DEFAULT_DIFFICULTY])["label"]

    if is_done:
        out = state.get("_outcome", "draw")
        out_txt = outcome_text(out, session, for_user_id)
        header = f"🧠 <b>Игра на память</b> ({diff_label})\n━━━━━━━━━━━━━━━━━━━━\n\n{out_txt}\n\n"
    elif state.get("_pending_hide"):
        header = f"🧠 <b>Игра на память</b> ({diff_label})\n━━━━━━━━━━━━━━━━━━━━\n\n❌ Не совпало! Карточки закрываются...\n\n"
    else:
        turn_name = p1_name if turn == p1 else p2_name
        whose = "👉 Твой ход! Открой карточку" if is_my_turn else f"⏳ Ход: <b>{turn_name}</b>"
        header = f"🧠 <b>Игра на память</b> ({diff_label})\n━━━━━━━━━━━━━━━━━━━━\n\n{whose}\n\n"

    players_line = f"🔵 <b>{p1_name}</b>: {p1s} пар  |  🔴 <b>{p2_name}</b>: {p2s} пар\n\n"

    can_click = is_my_turn and not state.get("_pending_hide")

    board_rows = []
    for r in range(rows):
        row_btns = []
        for c in range(cols):
            idx = r * cols + c
            if matched[idx]:
                label = cards[idx]
                data = f"g:memory:{game_id}:noop"
            elif revealed[idx]:
                label = cards[idx]
                data = f"g:memory:{game_id}:noop"
            else:
                label = BACK
                data = f"g:memory:{game_id}:{idx}" if can_click else f"g:memory:{game_id}:noop"
            row_btns.append(InlineKeyboardButton(text=label, callback_data=data))
        board_rows.append(row_btns)

    if is_done:
        board_rows.append([InlineKeyboardButton(text="🔄 Реванш", callback_data=f"game:rematch:{game_id}")])
    else:
        board_rows.append([InlineKeyboardButton(text="🏳️ Сдаться", callback_data=f"g:memory:{game_id}:surrender")])
    board_rows.append([InlineKeyboardButton(text="📋 Все игры", callback_data="menu:games")])

    text = header + players_line
    return text, InlineKeyboardMarkup(inline_keyboard=board_rows)


def handle_move(session: dict, payload: str, user_id: int) -> tuple[dict, str | None]:
    state = session["state"]

    if payload == "noop":
        return session, None
    if payload == "surrender":
        out = "win_p2" if user_id == session["player1_id"] else "win_p1"
        state["_outcome"] = out
        return session, out

    # Пока идёт показ несовпавшей пары — новые ходы не принимаем
    if state.get("_pending_hide"):
        return session, None

    try:
        idx = int(payload)
    except ValueError:
        return session, None

    n = len(state["cards"])
    if idx < 0 or idx >= n:
        return session, None
    if state["matched"][idx] or state["revealed"][idx]:
        return session, None

    cards = state["cards"]
    p1 = session["player1_id"]
    is_p1 = user_id == p1

    # Бот "видит" эту карту — запоминаем
    bot_seen = state.setdefault("bot_seen", {})
    bot_seen[str(idx)] = cards[idx]

    state["revealed"][idx] = True
    first = state.get("first_pick")

    if first is None:
        state["first_pick"] = idx
        return session, None

    # Второй выбор
    state["first_pick"] = None
    if cards[first] == cards[idx]:
        state["matched"][first] = True
        state["matched"][idx] = True
        if is_p1:
            state["player1_score"] += 1
        else:
            state["player2_score"] += 1
        if all(state["matched"]):
            p1s, p2s = state["player1_score"], state["player2_score"]
            if p1s > p2s:
                out = "win_p1"
            elif p2s > p1s:
                out = "win_p2"
            else:
                out = "draw"
            state["_outcome"] = out
            return session, out
        # Тот же игрок ходит снова (пара найдена)
        return session, None
    else:
        # Не угадал: карточки остаются видны ещё один "кадр", чтобы игрок
        # успел их увидеть — движок покажет это состояние, подождёт и вызовет
        # resolve_pending(), которая их скроет.
        state["_pending_hide"] = [first, idx]
        p2 = session.get("player2_id") or BOT_ID
        session["current_turn"] = p2 if is_p1 else p1

    return session, None


def resolve_pending(state: dict) -> None:
    """Скрывает несовпавшую пару карточек после паузы показа."""
    pending = state.pop("_pending_hide", None)
    if pending:
        for i in pending:
            if 0 <= i < len(state["revealed"]):
                state["revealed"][i] = False


def bot_move(session: dict) -> str | None:
    """Умный бот: запоминает все виденные карты и играет пары, если знает их."""
    state = session["state"]
    cards = state["cards"]
    matched = state["matched"]
    revealed = state["revealed"]
    n = len(cards)
    bot_seen = state.get("bot_seen", {})  # str(idx) -> emoji
    first = state.get("first_pick")

    if first is not None:
        # Второй ход — ищем пару для first-карты
        target = cards[first]
        for idx_str, val in bot_seen.items():
            idx = int(idx_str)
            if val == target and idx != first and not matched[idx] and not revealed[idx]:
                return str(idx)
        # Пары не знаем — берём карту, которую ещё не видели
        seen_idxs = {int(k) for k in bot_seen}
        unseen = [i for i in range(n) if not matched[i] and not revealed[i] and i not in seen_idxs and i != first]
        if unseen:
            return str(random.choice(unseen))
        # Все видели — берём любую скрытую
        hidden = [i for i in range(n) if not matched[i] and not revealed[i] and i != first]
        return str(random.choice(hidden)) if hidden else None
    else:
        # Первый ход — если знаем пару, сразу играем
        seen_items = [(int(k), v) for k, v in bot_seen.items() if not matched[int(k)] and not revealed[int(k)]]
        val_to_idxs: dict[str, list[int]] = {}
        for idx, val in seen_items:
            val_to_idxs.setdefault(val, []).append(idx)
        for val, idxs in val_to_idxs.items():
            available = [i for i in idxs if not matched[i] and not revealed[i]]
            if len(available) >= 2:
                return str(available[0])
        # Пар не знаем — открываем карту, которую ещё не видели
        seen_idxs = {int(k) for k in bot_seen}
        unseen = [i for i in range(n) if not matched[i] and not revealed[i] and i not in seen_idxs]
        if unseen:
            return str(random.choice(unseen))
        # Все видели, но пар не нашли — любая скрытая
        hidden = [i for i in range(n) if not matched[i] and not revealed[i]]
        return str(random.choice(hidden)) if hidden else None
