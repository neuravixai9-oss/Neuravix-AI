"""
Единый игровой движок Neuravix AI.
Каждая игра регистрируется через register_game() и реализует:
  - initial_state(player1_id, player2_id, mode, player1_name, player2_name, extra=None) -> dict
  - render(session, for_user_id) -> (text: str, keyboard: InlineKeyboardMarkup)
  - handle_move(session, payload, user_id) -> (session, outcome)
    outcome: None | "win" | "lose" | "draw" | "win_p1" | "win_p2"
  - bot_move(session) -> payload | None  (для однопользовательского режима)

Необязательные возможности игрового модуля:
  - TURN_BASED = False — игра без строгой очерёдности ходов (например КНБ,
    где оба игрока ходят независимо друг от друга); движок не будет
    выставлять current_turn при создании сессии.
  - resolve_pending(state) — если handle_move положил в state ключ
    "_pending_hide", движок сначала покажет игрокам промежуточное состояние
    поля, подождёт ~1.1с и вызовет эту функцию, чтобы скрыть/завершить
    промежуточный шаг (используется в "Памяти" для показа несовпавшей пары
    карточек перед тем как их закрыть обратно).
"""
import asyncio
import uuid
from typing import Optional

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ── Реестр игр ─────────────────────────────────────────────────────────────────

_GAMES: dict = {}


def register_game(name: str, module):
    _GAMES[name] = module


def get_game(name: str):
    return _GAMES.get(name)


# ── Вспомогательные ────────────────────────────────────────────────────────────

# msg_id_store[user_id] = {"message_id": int, "chat_id": int}
msg_store: dict[int, dict] = {}
BOT_ID = 0  # заглушка; заменяется в main.py


async def deliver(session: dict, bot, for_user_id: int):
    """Редактирует игровое сообщение или отправляет новое (одно на пользователя)."""
    game_mod = get_game(session["game_type"])
    if not game_mod:
        return

    try:
        text, kb = game_mod.render(session, for_user_id)
    except Exception:
        return

    stored = msg_store.get(for_user_id)
    if stored:
        try:
            await bot.edit_message_text(
                chat_id=stored["chat_id"],
                message_id=stored["message_id"],
                text=text,
                reply_markup=kb,
                parse_mode="HTML",
            )
            return
        except Exception:
            pass

    try:
        sent = await bot.send_message(
            chat_id=for_user_id,
            text=text,
            reply_markup=kb,
            parse_mode="HTML",
        )
        msg_store[for_user_id] = {"chat_id": for_user_id, "message_id": sent.message_id}
    except Exception:
        pass


async def deliver_to_both(session: dict, bot):
    p1 = session.get("player1_id")
    p2 = session.get("player2_id")
    tasks = []
    if p1:
        tasks.append(deliver(session, bot, p1))
    if p2 and p2 != BOT_ID and p2 != p1:
        tasks.append(deliver(session, bot, p2))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


# ── Результат игры ─────────────────────────────────────────────────────────────

def outcome_text(outcome: str, session: dict, for_user_id: int) -> str:
    p1 = session.get("player1_id")
    mode = session.get("mode", "friend")

    if mode == "bot":
        if outcome in ("win", "win_p1"):
            return "🏆 <b>Победа!</b> Ты обыграл бота!"
        if outcome in ("lose", "win_p2"):
            return "💔 <b>Поражение.</b> Бот оказался сильнее."
        return "🤝 <b>Ничья!</b> Достойный результат."

    if outcome == "draw":
        return "🤝 <b>Ничья!</b>"
    if outcome == "win_p1":
        return "🏆 <b>Победа!</b>" if for_user_id == p1 else "💔 <b>Поражение.</b>"
    if outcome == "win_p2":
        return "🏆 <b>Победа!</b>" if for_user_id != p1 else "💔 <b>Поражение.</b>"
    if outcome in ("win", "lose"):
        return "🏆 <b>Победа!</b>" if outcome == "win" else "💔 <b>Поражение.</b>"
    return ""


def end_kb(game_id: str, is_creator: bool) -> InlineKeyboardMarkup:
    from keyboards.menus import after_game_kb
    buttons = [
        [InlineKeyboardButton(text="🔄 Играть снова", callback_data=f"game:rematch:{game_id}")],
        [InlineKeyboardButton(text="📋 Все игры", callback_data="menu:games"),
         InlineKeyboardButton(text="🏠 Меню", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ── Создание игровой сессии ───────────────────────────────────────────────────

async def create_session(
    game_type: str,
    player1_id: int,
    player1_name: str,
    mode: str = "friend",
    player2_id: int = BOT_ID,
    player2_name: str = "Бот",
    extra: Optional[str] = None,
) -> dict:
    from database.db import create_game_session

    game_mod = get_game(game_type)
    if not game_mod:
        raise ValueError(f"Неизвестная игра: {game_type}")

    game_id = uuid.uuid4().hex[:10]
    state = game_mod.initial_state(
        player1_id=player1_id,
        player2_id=player2_id,
        mode=mode,
        player1_name=player1_name,
        player2_name=player2_name,
        extra=extra,
    )

    # Игры без строгой очерёдности (например КНБ) обрабатывают ходы обоих
    # игроков независимо от поля current_turn.
    turn_based = getattr(game_mod, "TURN_BASED", True)

    status = "active" if mode == "bot" else "waiting"
    session = await create_game_session(
        game_id=game_id,
        game_type=game_type,
        player1_id=player1_id,
        player2_id=player2_id if mode == "bot" else None,
        mode=mode,
        state=state,
        current_turn=player1_id if turn_based else None,
        status=status,
    )
    return session


async def accept_friend_invite(
    game_id: str,
    joiner_id: int,
    joiner_name: str,
    bot=None,
) -> Optional[dict]:
    from database.db import get_game_session, update_game_session

    session = await get_game_session(game_id)
    if not session or session["status"] != "waiting":
        return None
    if session["player1_id"] == joiner_id:
        return None

    game_mod = get_game(session["game_type"])
    if not game_mod:
        return None

    state = session["state"]
    state["player2_name"] = joiner_name

    await update_game_session(
        game_id,
        player2_id=joiner_id,
        status="active",
        state=state,
    )
    return await get_game_session(game_id)


# ── Обработка хода ─────────────────────────────────────────────────────────────

async def process_move(
    session: dict, payload: str, user_id: int, bot
) -> Optional[str]:
    """
    Выполняет ход, обновляет БД, доставляет сообщение.
    Возвращает outcome или None.
    """
    from database.db import get_game_session, update_game_session, delete_game_session

    game_mod = get_game(session["game_type"])
    if not game_mod:
        return None

    game_id = session["game_id"]

    try:
        new_session, outcome = game_mod.handle_move(session, payload, user_id)
    except Exception as exc:
        import logging
        logging.getLogger("games").exception("Ошибка хода в игре %s (%s): %s", session.get("game_type"), game_id, exc)
        # Не оставляем игрока с зависшим полем — переотправляем текущее
        # (последнее сохранённое) состояние, чтобы он мог продолжить игру.
        try:
            await deliver_to_both(session, bot)
        except Exception:
            pass
        return None

    if outcome:
        new_session["status"] = "finished"
        await update_game_session(game_id, state=new_session["state"], status="finished")
        await deliver_to_both(new_session, bot)
        return outcome

    await update_game_session(
        game_id,
        state=new_session["state"],
        current_turn=new_session.get("current_turn", user_id),
        status="active",
    )

    # Некоторые игры (например "Память") должны на мгновение показать
    # промежуточное состояние поля (например, обе открытые несовпавшие
    # карточки), прежде чем оно скроется и ход перейдёт дальше.
    pending = new_session["state"].get("_pending_hide")
    if pending and hasattr(game_mod, "resolve_pending"):
        await deliver_to_both(new_session, bot)
        await asyncio.sleep(1.1)
        game_mod.resolve_pending(new_session["state"])
        await update_game_session(
            game_id,
            state=new_session["state"],
            current_turn=new_session.get("current_turn", user_id),
        )

    # Ход бота
    if new_session.get("mode") == "bot" and new_session.get("current_turn") == BOT_ID:
        await deliver(new_session, bot, user_id)
        await asyncio.sleep(0.4)
        try:
            bot_payload = game_mod.bot_move(new_session)
        except Exception as exc:
            import logging
            logging.getLogger("games").exception("Ошибка хода бота в игре %s (%s): %s", session.get("game_type"), game_id, exc)
            bot_payload = None
        if bot_payload is not None:
            refreshed = await get_game_session(game_id)
            if refreshed and refreshed["status"] == "active":
                return await process_move(refreshed, bot_payload, BOT_ID, bot)
        else:
            await update_game_session(game_id, status="finished")
            new_session["status"] = "finished"
            await deliver_to_both(new_session, bot)
            return "draw"
    else:
        await deliver_to_both(new_session, bot)

    return None
