from . import engine
from . import tictactoe, connect4, memory, guess, coinflip, reaction, rps, quiz

engine.register_game("tictactoe", tictactoe)
engine.register_game("connect4", connect4)
engine.register_game("memory", memory)
engine.register_game("guess", guess)
engine.register_game("coinflip", coinflip)
engine.register_game("reaction", reaction)
engine.register_game("rps", rps)
engine.register_game("quiz", quiz)

from .menu import router as games_router


async def handle_join_game(message, room_id: str, bot=None, state=None):
    """Обрабатывает переход по deep-link приглашению в игру."""
    from database.db import get_game_session, get_or_create_user
    from config import GAMES

    await get_or_create_user(
        message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )

    session = await get_game_session(room_id)
    if not session:
        await message.answer("❌ Игра не найдена — приглашение истекло или недействительно.")
        return
    if session["player1_id"] == message.from_user.id:
        await message.answer("⚠️ Ты сам создал эту игру — ожидай соперника.")
        return
    if session["status"] != "waiting":
        await message.answer("❌ Игра уже началась или завершена.")
        return

    joiner_name = message.from_user.first_name or "Игрок"
    session = await engine.accept_friend_invite(room_id, message.from_user.id, joiner_name, bot=bot)
    if not session:
        await message.answer("❌ Не удалось присоединиться — приглашение уже неактуально.")
        return

    # Игровое поле для обоих игроков придёт одним сообщением — отдельное
    # приветственное сообщение не отправляем, чтобы не засорять чат.
    await engine.deliver_to_both(session, bot)
