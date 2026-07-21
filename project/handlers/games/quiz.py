"""
Викторина: соло-режим (на очки, без соперника) и режим с другом
(оба отвечают на одни и те же вопросы, побеждает набравший больше очков).
Вопросы не повторяются в рамках одной игры и берутся случайно из банка
QUESTIONS (handlers/games/quiz_questions.py).
"""
import random
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from handlers.games.engine import outcome_text, BOT_ID
from handlers.games.quiz_questions import QUESTIONS, CATEGORY_LABELS

TURN_BASED = False

ROUNDS = 10                 # вопросов за партию
LETTERS = ["🅰️", "🅱️", "🅲", "🅳"]


def _pick_questions(n: int) -> list[int]:
    pool = list(range(len(QUESTIONS)))
    random.shuffle(pool)
    return pool[:n]


def initial_state(player1_id, player2_id, mode, player1_name="Игрок", player2_name="Бот", extra=None, **kwargs) -> dict:
    n = min(ROUNDS, len(QUESTIONS))
    order = _pick_questions(n)
    return {
        "player1_name": player1_name,
        "player2_name": player2_name,
        "mode": mode,
        "order": order,          # индексы вопросов в QUESTIONS, по одному на раунд
        "round": 0,               # текущий раунд (0-based)
        "player1_score": 0,
        "player2_score": 0,
        "answers": {},            # str(user_id) -> выбранный индекс варианта в текущем раунде
        "last_feedback": None,    # текст фидбэка по прошлому раунду
    }


def _current_question(state: dict):
    idx = state["order"][state["round"]]
    return QUESTIONS[idx]  # (category, difficulty, question, options, correct_idx)


def render(session: dict, for_user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    state = session["state"]
    game_id = session["game_id"]
    status = session["status"]
    is_done = status == "finished"

    p1 = session["player1_id"]
    p1_name = state.get("player1_name", "Игрок 1")
    p2_name = state.get("player2_name", "Игрок 2")
    solo = session.get("mode") == "bot"
    p1s, p2s = state["player1_score"], state["player2_score"]

    header = "📚 <b>Викторина</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"

    if is_done:
        if solo:
            total = len(state["order"])
            header += f"🏁 <b>Игра окончена!</b>\n\nТвой результат: <b>{p1s} из {total}</b>\n\n"
            if total and p1s == total:
                header += "🏆 Идеально! Все ответы верны!\n\n"
            elif total and p1s >= total * 0.7:
                header += "👏 Отличный результат!\n\n"
            else:
                header += "💪 Попробуй ещё раз, чтобы улучшить счёт!\n\n"
        else:
            out = state.get("_outcome", "draw")
            header += outcome_text(out, session, for_user_id) + "\n\n"
        rows = [[InlineKeyboardButton(text="🔄 Играть снова", callback_data=f"game:rematch:{game_id}")],
                [InlineKeyboardButton(text="📋 Все игры", callback_data="menu:games")]]
        players_line = "" if solo else f"🔵 <b>{p1_name}</b>: {p1s}  |  🔴 <b>{p2_name}</b>: {p2s}\n\n"
        return header + players_line, InlineKeyboardMarkup(inline_keyboard=rows)

    category, difficulty, question, options, _correct = _current_question(state)
    cat_label = CATEGORY_LABELS.get(category, category)
    diff_label = {"easy": "🟢 Лёгкий", "medium": "🟡 Средний", "hard": "🔴 Сложный"}.get(difficulty, difficulty)
    round_no = state["round"] + 1
    total = len(state["order"])

    header += f"{cat_label} · {diff_label} · Вопрос {round_no}/{total}\n\n"
    if state.get("last_feedback"):
        header += f"ℹ️ {state['last_feedback']}\n\n"

    header += f"❓ <b>{question}</b>\n\n"

    already = str(for_user_id) in state.get("answers", {})
    if already and not solo:
        header += "⏳ Ждём ответ соперника...\n\n"

    players_line = "" if solo else f"🔵 <b>{p1_name}</b>: {p1s}  |  🔴 <b>{p2_name}</b>: {p2s}\n\n"

    rows = []
    can_answer = not already
    for i, opt in enumerate(options):
        data = f"g:quiz:{game_id}:{i}" if can_answer else f"g:quiz:{game_id}:noop"
        rows.append([InlineKeyboardButton(text=f"{LETTERS[i]} {opt}", callback_data=data)])
    rows.append([InlineKeyboardButton(text="🏳️ Завершить игру", callback_data=f"g:quiz:{game_id}:surrender")])
    rows.append([InlineKeyboardButton(text="📋 Все игры", callback_data="menu:games")])

    return header + players_line, InlineKeyboardMarkup(inline_keyboard=rows)


def _finish(session: dict, state: dict) -> str:
    if session.get("mode") == "bot":
        state["_outcome"] = "solo_done"
        return "solo_done"
    p1s, p2s = state["player1_score"], state["player2_score"]
    if p1s > p2s:
        out = "win_p1"
    elif p2s > p1s:
        out = "win_p2"
    else:
        out = "draw"
    state["_outcome"] = out
    return out


def handle_move(session: dict, payload: str, user_id: int) -> tuple[dict, str | None]:
    state = session["state"]

    if payload == "noop":
        return session, None
    if payload == "surrender":
        if session.get("mode") == "bot":
            state["_outcome"] = "solo_done"
            return session, "solo_done"
        out = "win_p2" if user_id == session["player1_id"] else "win_p1"
        state["_outcome"] = out
        return session, out

    try:
        choice = int(payload)
    except ValueError:
        return session, None
    if not (0 <= choice <= 3):
        return session, None

    answers = state.setdefault("answers", {})
    if str(user_id) in answers:
        return session, None

    answers[str(user_id)] = choice

    p1 = session["player1_id"]
    p2 = session.get("player2_id") or BOT_ID
    solo = session.get("mode") == "bot"

    # В соло-режиме нет второго живого игрока — сразу проверяем ответ.
    if solo:
        if str(p2) not in answers:
            # "бот" в соло-режиме не отвечает — используем как техническую заглушку
            answers[str(p2)] = -1
    else:
        if str(p2) not in answers and session.get("mode") == "friend":
            pass  # ждём второго живого игрока

    if str(p1) not in answers or str(p2) not in answers:
        return session, None

    _category, _difficulty, _question, options, correct = _current_question(state)

    if solo:
        c1 = answers[str(p1)]
        if c1 == correct:
            state["player1_score"] += 1
            state["last_feedback"] = f"✅ Верно! Правильный ответ: {LETTERS[correct]} {options[correct]}"
        else:
            state["last_feedback"] = f"❌ Неверно. Правильный ответ: {LETTERS[correct]} {options[correct]}"
    else:
        c1, c2 = answers[str(p1)], answers[str(p2)]
        p1_right = c1 == correct
        p2_right = c2 == correct
        if p1_right:
            state["player1_score"] += 1
        if p2_right:
            state["player2_score"] += 1
        p1_name = state.get("player1_name", "Игрок 1")
        p2_name = state.get("player2_name", "Игрок 2")
        marks = f"🔵 {p1_name}: {'✅' if p1_right else '❌'}  🔴 {p2_name}: {'✅' if p2_right else '❌'}"
        state["last_feedback"] = f"Правильный ответ: {LETTERS[correct]} {options[correct]}\n{marks}"

    state["answers"] = {}
    state["round"] += 1

    if state["round"] >= len(state["order"]):
        outcome = _finish(session, state)
        return session, outcome

    return session, None


def bot_move(session: dict) -> str | None:
    """Не используется движком напрямую (TURN_BASED=False), реализован для
    совместимости с интерфейсом игр."""
    return None
