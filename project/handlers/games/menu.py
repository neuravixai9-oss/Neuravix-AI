import asyncio

from aiogram import Router, F
from aiogram.types import CallbackQuery

from database.db import get_or_create_user, get_game_session, get_active_session_for_user
from handlers.games import engine
from keyboards.menus import games_menu_kb, game_mode_kb, invite_friend_kb, back_to_main_kb, switch_game_kb, difficulty_kb
from config import GAMES

router = Router()

# Игры, для которых перед выбором режима нужно выбрать уровень сложности
GAMES_WITH_DIFFICULTY = {"memory"}


# ── Меню игр ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:games")
async def open_games_menu(callback: CallbackQuery):
    active = await get_active_session_for_user(callback.from_user.id)
    try:
        await callback.message.edit_text(
            "🎮 <b>Игровой центр</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Играй против умного бота или пригласи друга!\n\n"
            "Выбери игру:",
            reply_markup=games_menu_kb(has_active=bool(active)),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            "🎮 <b>Игровой центр</b>\n\nВыбери игру:",
            reply_markup=games_menu_kb(has_active=bool(active)),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("game:open:"))
async def open_game(callback: CallbackQuery):
    game_type = callback.data.split(":", 2)[2]
    g = GAMES.get(game_type)
    if not g:
        await callback.answer("❌ Игра не найдена", show_alert=True)
        return

    if game_type in GAMES_WITH_DIFFICULTY:
        text = (
            f"{g['emoji']} <b>{g['title']}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Выбери уровень сложности:"
        )
        kb = difficulty_kb(game_type)
    else:
        text = (
            f"{g['emoji']} <b>{g['title']}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Выбери режим игры:"
        )
        kb = game_mode_kb(game_type)

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("game:diff:"))
async def choose_difficulty(callback: CallbackQuery):
    # формат: game:diff:<game_type>:<difficulty>
    parts = callback.data.split(":", 3)
    if len(parts) < 4:
        await callback.answer()
        return
    _, _, game_type, difficulty = parts
    g = GAMES.get(game_type, {"emoji": "🎮", "title": "Игра"})
    text = (
        f"{g['emoji']} <b>{g['title']}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Выбери режим игры:"
    )
    try:
        await callback.message.edit_text(text, reply_markup=game_mode_kb(game_type, extra=difficulty), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=game_mode_kb(game_type, extra=difficulty), parse_mode="HTML")
    await callback.answer()


# ── Создание игры ─────────────────────────────────────────────────────────────

def _parse_game_type_extra(data: str) -> tuple[str, str | None]:
    """Разбирает 'gm:bot:<game_type>' или 'gm:bot:<game_type>:<extra>'."""
    raw = data.split(":", 2)[2]
    if ":" in raw:
        game_type, extra = raw.split(":", 1)
        return game_type, extra
    return raw, None


@router.callback_query(F.data.startswith("gm:bot:"))
async def start_vs_bot(callback: CallbackQuery, bot=None):
    game_type, extra = _parse_game_type_extra(callback.data)
    await get_or_create_user(
        callback.from_user.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
    )
    name1 = callback.from_user.first_name or "Игрок"
    session = await engine.create_session(
        game_type, callback.from_user.id, name1, mode="bot",
        player2_id=engine.BOT_ID, player2_name="🤖 Бот", extra=extra,
    )
    try:
        await callback.message.delete()
    except Exception:
        pass
    await engine.deliver(session, bot, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("gm:friend:"))
async def start_vs_friend(callback: CallbackQuery, bot=None):
    game_type, extra = _parse_game_type_extra(callback.data)
    await get_or_create_user(
        callback.from_user.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
    )
    name1 = callback.from_user.first_name or "Игрок"
    session = await engine.create_session(
        game_type, callback.from_user.id, name1, mode="friend", extra=extra,
    )
    game_id = session["game_id"]
    me = await bot.get_me()
    g = GAMES.get(game_type, {"emoji": "🎮", "title": "Игра"})
    try:
        await callback.message.edit_text(
            f"{g['emoji']} <b>{g['title']} — ожидание соперника</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Поделись приглашением с другом.\n\n"
            f"⏱ Приглашение действительно <b>5 минут</b>.\n\n"
            f"🆔 Код игры: <code>{game_id}</code>",
            reply_markup=invite_friend_kb(game_id, me.username),
            parse_mode="HTML",
        )
        # Запоминаем это сообщение, чтобы когда соперник присоединится и игра
        # начнётся, движок отредактировал именно его, а не прислал новое.
        engine.msg_store[callback.from_user.id] = {
            "chat_id": callback.message.chat.id,
            "message_id": callback.message.message_id,
        }
    except Exception:
        sent = await callback.message.answer(
            f"Приглашение на {g['title']} создано. Поделись ссылкой с другом!",
            reply_markup=invite_friend_kb(game_id, me.username),
        )
        engine.msg_store[callback.from_user.id] = {
            "chat_id": sent.chat.id,
            "message_id": sent.message_id,
        }
    await callback.answer()


@router.callback_query(F.data.startswith("game:cancel_invite:"))
async def cancel_invite(callback: CallbackQuery):
    game_id = callback.data.split(":", 2)[2]
    from database.db import delete_game_session
    await delete_game_session(game_id)
    try:
        await callback.message.edit_text(
            "✖️ Приглашение отменено.",
            reply_markup=back_to_main_kb(),
        )
    except Exception:
        pass
    await callback.answer("✖️ Приглашение отменено")


# ── Реконнект ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "game:reconnect")
async def reconnect(callback: CallbackQuery, bot=None):
    session = await get_active_session_for_user(callback.from_user.id)
    if not session:
        await callback.answer("Активной игры нет", show_alert=True)
        return
    await callback.answer()
    await engine.deliver(session, bot, callback.from_user.id)


# ── Реванш ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("game:rematch:"))
async def rematch(callback: CallbackQuery, bot=None):
    old_id = callback.data.split(":", 2)[2]
    old = await get_game_session(old_id)
    if not old:
        await callback.answer("Игра не найдена", show_alert=True)
        return

    game_type = old["game_type"]
    mode = old.get("mode", "bot")

    old_state = old.get("state", {})
    p1_name = old_state.get("player1_name", "Игрок")
    p2_name = old_state.get("player2_name", "Бот")
    p2_id = old.get("player2_id") or engine.BOT_ID

    session = await engine.create_session(
        game_type,
        old["player1_id"],
        p1_name,
        mode=mode,
        player2_id=p2_id if mode == "bot" else engine.BOT_ID,
        player2_name=p2_name,
        extra=old_state.get("difficulty"),
    )

    if mode == "friend" and callback.from_user.id != old["player1_id"]:
        state = session["state"]
        state["player2_name"] = p2_name
        from database.db import update_game_session
        await update_game_session(
            session["game_id"],
            player2_id=callback.from_user.id,
            status="active",
            state=state,
        )
        session = await get_game_session(session["game_id"])

    await callback.answer()
    await engine.deliver_to_both(session, bot)


# ── Сменить игру (после партии) ───────────────────────────────────────────────

@router.callback_query(F.data.startswith("game:reswitch:"))
async def reswitch_game(callback: CallbackQuery):
    game_id = callback.data.split(":", 2)[2]
    old = await get_game_session(game_id)
    if not old:
        await callback.answer("Игра не найдена", show_alert=True)
        return
    if old["player1_id"] != callback.from_user.id:
        await callback.answer("❌ Только создатель может сменить игру", show_alert=True)
        return
    try:
        await callback.message.edit_text(
            "🎮 <b>Выбери другую игру</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Сыграем что-нибудь другое?",
            reply_markup=switch_game_kb(game_id),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("game:switchto:"))
async def switchto_game(callback: CallbackQuery, bot=None):
    # формат: game:switchto:<game_id>:<new_game_type>
    parts = callback.data.split(":", 3)
    if len(parts) < 4:
        await callback.answer()
        return
    _, _, old_game_id, new_game_type = parts

    old = await get_game_session(old_game_id)
    if not old:
        await callback.answer("Игра не найдена", show_alert=True)
        return
    if new_game_type not in GAMES:
        await callback.answer("❌ Неизвестная игра", show_alert=True)
        return

    old_state = old.get("state", {})
    p1_name = old_state.get("player1_name", "Игрок")
    p2_name = old_state.get("player2_name", "Бот")
    mode = old.get("mode", "bot")
    p2_id = old.get("player2_id") or engine.BOT_ID

    session = await engine.create_session(
        new_game_type,
        old["player1_id"],
        p1_name,
        mode=mode,
        player2_id=p2_id if mode == "bot" else engine.BOT_ID,
        player2_name=p2_name,
    )

    if mode == "friend":
        # Обоим показываем новую игру
        state = session["state"]
        state["player2_name"] = p2_name
        p2_real = old.get("player2_id")
        if p2_real:
            from database.db import update_game_session
            await update_game_session(
                session["game_id"],
                player2_id=p2_real,
                status="active",
                state=state,
            )
            session = await get_game_session(session["game_id"])

    g = GAMES.get(new_game_type, {"emoji": "🎮", "title": new_game_type})
    await callback.answer(f"▶️ Начинаем {g['emoji']} {g['title']}!")
    await engine.deliver_to_both(session, bot)


# ── Обработка игровых ходов ───────────────────────────────────────────────────
# Формат callback_data: g:<game_type>:<game_id>:<payload>

@router.callback_query(F.data.startswith("g:"))
async def handle_game_move(callback: CallbackQuery, bot=None):
    parts = callback.data.split(":", 3)
    if len(parts) < 4:
        await callback.answer()
        return

    _, game_type, game_id, payload = parts
    session = await get_game_session(game_id)
    if not session:
        await callback.answer("❌ Игра завершена или не найдена", show_alert=True)
        return
    if session["status"] != "active":
        await callback.answer("Игра уже завершена", show_alert=True)
        return

    user_id = callback.from_user.id
    if user_id not in (session["player1_id"], session.get("player2_id")):
        await callback.answer("❌ Ты не участвуешь в этой игре", show_alert=True)
        return

    current_turn = session.get("current_turn")
    if current_turn and current_turn != user_id:
        await callback.answer("⏳ Не твой ход", show_alert=True)
        return

    await callback.answer()
    await engine.process_move(session, payload, user_id, bot)
