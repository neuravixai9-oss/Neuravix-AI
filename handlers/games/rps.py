"""
Камень, ножницы, бумага — до 3 побед.
Игра без строгой очерёдности: оба игрока выбирают одновременно
(TURN_BASED = False), раунд разрешается, когда получены оба выбора.
"""
import random
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from handlers.games.engine import outcome_text, BOT_ID

TURN_BASED = False

CHOICES = {"rock": "🪨 Камень", "scissors": "✂️ Ножницы", "paper": "📄 Бумага"}
BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}
TARGET_WINS = 3


def initial_state(player1_id, player2_id, mode, player1_name="Игрок", player2_name="Бот", extra=None, **kwargs) -> dict:
    return {
        "player1_name": player1_name,
        "player2_name": player2_name,
        "mode": mode,
        "player1_score": 0,
        "player2_score": 0,
        "round": 1,
        "choices": {},          # str(user_id) -> "rock"/"scissors"/"paper" (текущий раунд)
        "last_round": None,     # текст итога прошлого раунда
    }


def _other(session: dict, user_id: int) -> int:
    p1 = session["player1_id"]
    p2 = session.get("player2_id") or BOT_ID
    return p2 if user_id == p1 else p1


def render(session: dict, for_user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    state = session["state"]
    game_id = session["game_id"]
    status = session["status"]
    is_done = status == "finished"

    p1 = session["player1_id"]
    p1_name = state.get("player1_name", "Игрок 1")
    p2_name = state.get("player2_name", "Игрок 2")
    p1s, p2s = state["player1_score"], state["player2_score"]

    header = f"✊✋✌ <b>Камень, ножницы, бумага</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"

    if is_done:
        out = state.get("_outcome", "draw")
        header += outcome_text(out, session, for_user_id) + "\n\n"
    else:
        header += f"🎯 Раунд {state['round']} · до {TARGET_WINS} побед\n"
        if state.get("last_round"):
            header += f"ℹ️ {state['last_round']}\n"
        already_chosen = str(for_user_id) in state.get("choices", {})
        if already_chosen:
            header += "⏳ Ждём выбор соперника...\n"
        else:
            header += "👉 Выбери свой ход:\n"
        header += "\n"

    players_line = f"🔵 <b>{p1_name}</b>: {p1s}  |  🔴 <b>{p2_name}</b>: {p2s}\n\n"

    rows = []
    if not is_done:
        can_choose = str(for_user_id) not in state.get("choices", {})
        btn_row = []
        for key, label in CHOICES.items():
            data = f"g:rps:{game_id}:{key}" if can_choose else f"g:rps:{game_id}:noop"
            btn_row.append(InlineKeyboardButton(text=label, callback_data=data))
        rows.append(btn_row)
        rows.append([InlineKeyboardButton(text="🏳️ Сдаться", callback_data=f"g:rps:{game_id}:surrender")])
    else:
        rows.append([InlineKeyboardButton(text="🔄 Играть ещё", callback_data=f"game:rematch:{game_id}")])
        rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:main")])

    return header + players_line, InlineKeyboardMarkup(inline_keyboard=rows)


def _resolve_round(session: dict, c1: str, c2: str) -> str:
    """Возвращает 'p1', 'p2' или 'draw'."""
    if c1 == c2:
        return "draw"
    return "p1" if BEATS[c1] == c2 else "p2"


def handle_move(session: dict, payload: str, user_id: int) -> tuple[dict, str | None]:
    state = session["state"]

    if payload == "noop":
        return session, None
    if payload == "surrender":
        out = "win_p2" if user_id == session["player1_id"] else "win_p1"
        state["_outcome"] = out
        return session, out
    if payload not in CHOICES:
        return session, None

    choices = state.setdefault("choices", {})
    if str(user_id) in choices:
        return session, None  # уже выбрал в этом раунде

    choices[str(user_id)] = payload

    p1 = session["player1_id"]
    p2 = session.get("player2_id") or BOT_ID

    # В режиме против бота бот "ходит" сразу же, как только сходил человек
    if session.get("mode") == "bot" and str(p2) not in choices:
        choices[str(p2)] = random.choice(list(CHOICES.keys()))

    if str(p1) not in choices or str(p2) not in choices:
        return session, None  # ждём второго игрока

    c1, c2 = choices[str(p1)], choices[str(p2)]
    winner = _resolve_round(session, c1, c2)

    if winner == "p1":
        state["player1_score"] += 1
        state["last_round"] = f"{CHOICES[c1]} против {CHOICES[c2]} → 🔵 {state.get('player1_name','Игрок 1')} выиграл раунд!"
    elif winner == "p2":
        state["player2_score"] += 1
        state["last_round"] = f"{CHOICES[c1]} против {CHOICES[c2]} → 🔴 {state.get('player2_name','Игрок 2')} выиграл раунд!"
    else:
        state["last_round"] = f"{CHOICES[c1]} против {CHOICES[c2]} → ничья в раунде"

    state["choices"] = {}
    state["round"] += 1

    if state["player1_score"] >= TARGET_WINS:
        state["_outcome"] = "win_p1"
        return session, "win_p1"
    if state["player2_score"] >= TARGET_WINS:
        state["_outcome"] = "win_p2"
        return session, "win_p2"

    return session, None


def bot_move(session: dict) -> str | None:
    """Не используется напрямую движком (TURN_BASED=False, бот ходит внутри
    handle_move), но реализован для совместимости с интерфейсом игр."""
    return random.choice(list(CHOICES.keys()))
