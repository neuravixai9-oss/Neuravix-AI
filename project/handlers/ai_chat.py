import asyncio
import html
import time
import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, PhotoSize, Document, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

logger = logging.getLogger("ai_chat")

from database.db import (
    get_or_create_user, can_send_message, increment_message_count,
    create_chat, get_chats, get_chat, rename_chat, toggle_pin_chat, toggle_search_chat,
    delete_chat, get_messages, add_message, update_message_content, delete_messages_after,
)
from keyboards.menus import (
    chat_list_kb, chat_actions_kb, chat_delete_confirm_kb, stop_generation_kb,
    after_response_kb, back_to_chat_kb, back_to_main_kb,
)
from config import SUBSCRIPTION_LIMITS
from services.ai_service import EDIT_INTERVAL

router = Router()

# user_id -> {"task": asyncio.Task, "chat_id": str}
active_generations: dict[int, dict] = {}

MAX_HISTORY_MESSAGES = 40


class AIChatState(StatesGroup):
    browsing = State()
    chatting = State()
    waiting_rename = State()
    waiting_search = State()


async def _render_chat_list(user_id: int, query: str | None = None) -> tuple[str, "InlineKeyboardMarkup"]:
    chats = await get_chats(user_id, query)
    if query:
        header = f"🔎 <b>Поиск:</b> «{html.escape(query)}»\n\n"
        header += "Ничего не найдено." if not chats else f"Найдено диалогов: <b>{len(chats)}</b>"
    else:
        header = (
            "✨ <b>Neuravix AI — Нейросеть</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        if chats:
            header += f"Диалогов: <b>{len(chats)}</b> — выбери или создай новый:"
        else:
            header += (
                "Диалогов пока нет.\n\n"
                "Я могу: отвечать на вопросы, анализировать фото и файлы, "
                "искать в интернете, помогать с кодом.\n\n"
                "👇 Нажми «➕ Новый диалог», чтобы начать!"
            )
    return header, chat_list_kb(chats)


@router.callback_query(F.data == "menu:ai")
async def open_ai_section(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(AIChatState.browsing)
    text, kb = await _render_chat_list(callback.from_user.id)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "chat:list")
async def back_to_chat_list(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AIChatState.browsing)
    await state.update_data(chat_id=None)
    text, kb = await _render_chat_list(callback.from_user.id)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "chat:new")
async def create_new_chat(callback: CallbackQuery, state: FSMContext):
    chat_id = await create_chat(callback.from_user.id)
    await _open_chat(callback, state, chat_id)


@router.callback_query(F.data.startswith("chat:open:"))
async def open_chat(callback: CallbackQuery, state: FSMContext):
    chat_id = callback.data.split(":", 2)[2]
    await _open_chat(callback, state, chat_id)


async def _open_chat(callback: CallbackQuery, state: FSMContext, chat_id: str):
    chat = await get_chat(chat_id)
    if not chat or chat["user_id"] != callback.from_user.id:
        await callback.answer("❌ Диалог не найден", show_alert=True)
        return

    await state.set_state(AIChatState.chatting)
    await state.update_data(chat_id=chat_id)

    messages = await get_messages(chat_id)
    title = chat.get("title") or "Новый диалог"
    search_on = bool(chat.get("search_enabled"))

    if messages:
        preview_lines = []
        for m in messages[-3:]:
            who = "👤" if m["role"] == "user" else "🤖"
            snippet = m["content"].strip().replace("\n", " ")[:90]
            preview_lines.append(f"{who} {snippet}…" if len(m["content"]) > 90 else f"{who} {snippet}")
        preview = "\n".join(preview_lines)
        search_badge = " 🌐" if search_on else ""
        text = (
            f"💬 <b>{html.escape(title)}</b>{search_badge}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{html.escape(preview)}\n\n"
            f"<i>Напиши сообщение, чтобы продолжить ↓</i>"
        )
    else:
        text = (
            f"💬 <b>{html.escape(title)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<i>Напиши вопрос, отправь фото или файл — и начнём!</i>"
        )

    kb = chat_actions_kb(chat_id, bool(chat.get("pinned")), bool(chat.get("search_enabled")))
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("chat:pin:"))
async def pin_chat(callback: CallbackQuery):
    chat_id = callback.data.split(":", 2)[2]
    new_val = await toggle_pin_chat(chat_id)
    chat = await get_chat(chat_id)
    if chat:
        kb = chat_actions_kb(chat_id, bool(chat.get("pinned")), bool(chat.get("search_enabled")))
        try:
            await callback.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            pass
    await callback.answer("📌 Закреплено" if new_val else "Откреплено")


@router.callback_query(F.data.startswith("chat:togglesearch:"))
async def toggle_chat_search(callback: CallbackQuery):
    chat_id = callback.data.split(":", 2)[2]
    new_val = await toggle_search_chat(chat_id)
    chat = await get_chat(chat_id)
    if chat:
        kb = chat_actions_kb(chat_id, bool(chat.get("pinned")), bool(chat.get("search_enabled")))
        try:
            await callback.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            pass
    await callback.answer("🌐 Поиск включён ✅" if new_val else "🌐 Поиск выключен")


@router.callback_query(F.data.startswith("chat:rename:"))
async def rename_chat_start(callback: CallbackQuery, state: FSMContext):
    chat_id = callback.data.split(":", 2)[2]
    await state.set_state(AIChatState.waiting_rename)
    await state.update_data(chat_id=chat_id, rename_msg_id=None)
    text = "✏️ <b>Переименовать диалог</b>\n\nВведи новое название (до 60 символов):"
    try:
        await callback.message.edit_text(
            text,
            reply_markup=back_to_chat_kb(chat_id),
            parse_mode="HTML",
        )
    except Exception:
        msg = await callback.message.answer(text, parse_mode="HTML", reply_markup=back_to_chat_kb(chat_id))
        await state.update_data(rename_msg_id=msg.message_id)
    await callback.answer()


@router.message(AIChatState.waiting_rename, F.text)
async def rename_chat_process(message: Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data.get("chat_id")
    if not chat_id:
        await state.clear()
        return

    new_title = message.text.strip()[:60]
    if not new_title:
        await message.answer("⚠️ Название не может быть пустым. Введи другое название:")
        return

    await rename_chat(chat_id, new_title)
    chat = await get_chat(chat_id)

    await state.set_state(AIChatState.chatting)
    await state.update_data(chat_id=chat_id)

    # Показываем обновлённый чат
    title = chat.get("title") or new_title
    kb = chat_actions_kb(chat_id, bool(chat.get("pinned")), bool(chat.get("search_enabled")))
    await message.answer(
        f"✅ Диалог переименован в «<b>{html.escape(title)}</b>»\n\n"
        f"💬 <b>{html.escape(title)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<i>Напиши сообщение, чтобы продолжить ↓</i>",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("chat:delete:"))
async def delete_chat_confirm_ask(callback: CallbackQuery):
    chat_id = callback.data.split(":", 2)[2]
    try:
        await callback.message.edit_text(
            "🗑️ <b>Удалить этот диалог безвозвратно?</b>\n\nВсе сообщения будут потеряны.",
            reply_markup=chat_delete_confirm_kb(chat_id),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("chat:delete_confirm:"))
async def delete_chat_confirm(callback: CallbackQuery, state: FSMContext):
    chat_id = callback.data.split(":", 2)[2]
    await delete_chat(chat_id)
    await state.set_state(AIChatState.browsing)
    text, kb = await _render_chat_list(callback.from_user.id)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer("✅ Диалог удалён")


@router.callback_query(F.data == "chat:search")
async def search_chats_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AIChatState.waiting_search)
    try:
        await callback.message.edit_text(
            "🔎 <b>Поиск диалогов</b>\n\nВведи слово из названия диалога:",
            reply_markup=back_to_main_kb(),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


@router.message(AIChatState.waiting_search, F.text)
async def search_chats_process(message: Message, state: FSMContext):
    await state.set_state(AIChatState.browsing)
    text, kb = await _render_chat_list(message.from_user.id, message.text.strip())
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


# ── Основная переписка ──────────────────────────────────────────────────────

def _history_for_gemini(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages[-MAX_HISTORY_MESSAGES:]:
        role = "model" if m["role"] == "assistant" else "user"
        content = m.get("content", "").strip()
        if content:
            out.append({"role": role, "content": content})
    return out


async def _download_attachment(message: Message, bot):
    """Возвращает (bytes, filename, mime) для фото или документа."""
    if message.photo:
        photo: PhotoSize = message.photo[-1]
        try:
            file = await bot.get_file(photo.file_id)
            data = (await bot.download_file(file.file_path)).read()
            return data, "photo.jpg", "image/jpeg"
        except Exception:
            return None, None, None
    if message.document:
        doc: Document = message.document
        if doc.file_size and doc.file_size > 20 * 1024 * 1024:
            return None, None, "TOO_BIG"
        try:
            file = await bot.get_file(doc.file_id)
            data = (await bot.download_file(file.file_path)).read()
            return data, doc.file_name or "file", doc.mime_type or "application/octet-stream"
        except Exception:
            return None, None, None
    return None, None, None


def _safe_escape(text: str) -> str:
    """Экранирует HTML и обрезает до безопасного размера."""
    return html.escape(text)[:4000]


async def _run_generation(
    user_id: int,
    chat_id: str,
    placeholder: Message,
    history: list[dict],
    model: str,
    max_tokens: int,
    use_search: bool,
    file_bytes: bytes | None,
    file_name: str | None,
    file_mime: str | None,
    bot,
):
    from services.ai_service import stream_chat, AIError, generate_title, ToolCall

    buffer = ""
    last_edit = 0.0
    stopped = False
    has_output = False
    tool_call = None

    try:
        async for piece in stream_chat(
            history, model=model, max_tokens=max_tokens, use_search=use_search,
            file_bytes=file_bytes, file_name=file_name, file_mime=file_mime,
            user_id=user_id,
        ):
            if isinstance(piece, ToolCall):
                tool_call = piece
                break
            buffer += piece
            has_output = True
            now = time.monotonic()
            if now - last_edit >= EDIT_INTERVAL:
                last_edit = now
                display = (buffer[:3900] + "…") if len(buffer) > 3900 else buffer
                try:
                    await placeholder.edit_text(
                        display or "⏳",
                        reply_markup=stop_generation_kb(chat_id),
                        parse_mode=None,
                    )
                except Exception:
                    pass
    except asyncio.CancelledError:
        stopped = True
    except AIError as e:
        try:
            if buffer.strip():
                partial = _safe_escape(buffer.strip())
                await placeholder.edit_text(
                    f"{partial}\n\n{e.args[0]}",
                    reply_markup=back_to_chat_kb(chat_id), parse_mode="HTML",
                )
            else:
                await placeholder.edit_text(
                    e.args[0], reply_markup=back_to_chat_kb(chat_id), parse_mode="HTML"
                )
        except Exception:
            pass
        return
    except Exception as e:
        logger.error("Непредвиденная ошибка в _run_generation: %r", e, exc_info=True)
        try:
            await placeholder.edit_text(
                "❌ <b>Что-то пошло не так.</b>\n\nПопробуй ещё раз.",
                reply_markup=back_to_chat_kb(chat_id), parse_mode="HTML",
            )
        except Exception:
            pass
        return
    finally:
        active_generations.pop(user_id, None)

    if tool_call is not None and not stopped:
        await _execute_tool_call(
            tool_call, user_id, chat_id, placeholder, bot, file_bytes, file_mime, history,
        )
        return

    final_text = buffer.strip() or "Не удалось получить ответ."
    await add_message(chat_id, "assistant", final_text)
    await increment_message_count(user_id)

    # Финальный рендер.
    # Модель форматирует ответ HTML-тегами (<b>, <code> — см. системный промпт),
    # поэтому отправляем текст как есть, доверяя её разметке, и только если
    # Telegram не смог распарсить HTML (модель ошиблась с тегами) — откатываемся
    # на экранированный обычный текст, чтобы теги не показывались буквально.
    stop_note = "\n\n<i>⏹ Остановлено.</i>" if stopped else ""
    display = (final_text[:3900] + "…") if len(final_text) > 3900 else final_text
    display += stop_note

    try:
        await placeholder.edit_text(
            display,
            reply_markup=after_response_kb(chat_id),
            parse_mode="HTML",
        )
    except Exception:
        try:
            await placeholder.edit_text(
                _safe_escape(final_text) + stop_note,
                reply_markup=after_response_kb(chat_id),
                parse_mode="HTML",
            )
        except Exception:
            pass

    # Автоназвание чата
    chat = await get_chat(chat_id)
    if chat and not chat.get("title"):
        title = await generate_title(history + [{"role": "model", "content": final_text}])
        if title:
            await rename_chat(chat_id, title)


async def _execute_tool_call(
    tool_call, user_id: int, chat_id: str, placeholder: Message, bot,
    file_bytes: bytes | None, file_mime: str | None, history: list[dict],
):
    """Выполняет инструмент, который решила вызвать нейросеть прямо в чате
    (генерация/редактирование изображения, создание файла), и присылает
    пользователю готовый результат — без отдельных кнопок и режимов."""
    from services.ai_service import generate_image, edit_image, AIError, generate_title
    from services.file_tools import build_file
    from database.db import can_generate_image, increment_image_count

    name = tool_call.name
    args = tool_call.args
    summary = None

    async def _check_image_quota() -> bool:
        can_gen, remaining = await can_generate_image(user_id)
        if not can_gen:
            user = await get_or_create_user(user_id)
            sub = user.get("subscription", "free")
            limit = SUBSCRIPTION_LIMITS[sub].get("images_per_day", 5)
            try:
                await placeholder.edit_text(
                    f"⛔ <b>Дневной лимит изображений исчерпан</b>\n\n"
                    f"Использовано <b>{limit}</b> из <b>{limit}</b> генераций сегодня.\n"
                    f"🕛 Лимит обновится в полночь.\n\n"
                    f"Чтобы снять ограничения — оформи подписку в магазине 💎",
                    reply_markup=back_to_chat_kb(chat_id),
                    parse_mode="HTML",
                )
            except Exception:
                pass
            return False
        return True

    try:
        if name == "generate_image":
            prompt = (args.get("prompt") or "").strip()
            if not prompt:
                raise AIError(
                    "⚠️ <b>Не удалось понять, что нарисовать.</b>\n\n"
                    "Опиши подробнее, что нужно изобразить."
                )
            if not await _check_image_quota():
                return
            try:
                await placeholder.edit_text("🎨 <i>Рисую…</i>", parse_mode="HTML")
            except Exception:
                pass
            img_bytes = await generate_image(prompt)
            await increment_image_count(user_id)
            await bot.send_photo(
                placeholder.chat.id,
                photo=BufferedInputFile(img_bytes, filename="neuravix_image.png"),
                caption=f"🖼️ <b>Готово!</b>\n\n📝 <i>{html.escape(prompt[:200])}</i>",
                reply_markup=after_response_kb(chat_id),
                parse_mode="HTML",
            )
            summary = f"[Сгенерировано изображение по запросу: {prompt[:200]}]"

        elif name == "edit_image":
            instruction = (args.get("instruction") or "").strip()
            if not file_bytes or not (file_mime or "").startswith("image/"):
                try:
                    await placeholder.edit_text(
                        "📎 <b>Пришли, пожалуйста, фото</b>, которое нужно отредактировать, "
                        "вместе с описанием изменений — в одном сообщении.",
                        reply_markup=back_to_chat_kb(chat_id), parse_mode="HTML",
                    )
                except Exception:
                    pass
                await add_message(chat_id, "assistant", "[Запросил у пользователя фото для редактирования]")
                return
            if not await _check_image_quota():
                return
            try:
                await placeholder.edit_text("🎨 <i>Редактирую фото…</i>", parse_mode="HTML")
            except Exception:
                pass
            img_bytes = await edit_image(file_bytes, file_mime, instruction or "Улучши это изображение")
            await increment_image_count(user_id)
            await bot.send_photo(
                placeholder.chat.id,
                photo=BufferedInputFile(img_bytes, filename="neuravix_edited.png"),
                caption=f"✅ <b>Готово!</b>\n\n📝 <i>{html.escape(instruction[:200])}</i>",
                reply_markup=after_response_kb(chat_id),
                parse_mode="HTML",
            )
            summary = f"[Отредактировано изображение: {instruction[:200]}]"

        elif name == "create_file":
            filename = args.get("filename") or "file.txt"
            file_type = args.get("file_type") or "text"
            content = args.get("content") or ""
            if not content.strip():
                raise AIError(
                    "⚠️ <b>Не удалось сформировать содержимое файла.</b>\n\n"
                    "Попробуй переформулировать запрос."
                )
            try:
                await placeholder.edit_text("📄 <i>Готовлю файл…</i>", parse_mode="HTML")
            except Exception:
                pass
            data, final_name = build_file(filename, file_type, content)
            await bot.send_document(
                placeholder.chat.id,
                document=BufferedInputFile(data, filename=final_name),
                caption=f"📄 <b>Файл готов:</b> <code>{html.escape(final_name)}</code>",
                reply_markup=after_response_kb(chat_id),
                parse_mode="HTML",
            )
            summary = f"[Создан файл {final_name}]"

        else:
            raise AIError("⚠️ <b>Не удалось выполнить запрос.</b>\n\nПопробуй сформулировать иначе.")

        try:
            await placeholder.delete()
        except Exception:
            pass

        await add_message(chat_id, "assistant", summary)
        await increment_message_count(user_id)

        chat = await get_chat(chat_id)
        if chat and not chat.get("title"):
            title = await generate_title(history + [{"role": "model", "content": summary}])
            if title:
                await rename_chat(chat_id, title)

    except AIError as e:
        try:
            await placeholder.edit_text(
                e.args[0], reply_markup=back_to_chat_kb(chat_id), parse_mode="HTML",
            )
        except Exception:
            pass
    except Exception as e:
        logger.error("Непредвиденная ошибка в _execute_tool_call (%s): %r", name, e, exc_info=True)
        try:
            await placeholder.edit_text(
                "❌ <b>Что-то пошло не так при выполнении запроса.</b>\n\nПопробуй ещё раз.",
                reply_markup=back_to_chat_kb(chat_id), parse_mode="HTML",
            )
        except Exception:
            pass


@router.message(AIChatState.chatting, F.text | F.photo | F.document)
async def handle_ai_message(message: Message, state: FSMContext, bot=None):
    data = await state.get_data()
    chat_id = data.get("chat_id")
    if not chat_id:
        await message.answer(
            "Открой диалог из списка, чтобы продолжить.",
            reply_markup=back_to_main_kb()
        )
        return

    user = await get_or_create_user(message.from_user.id)
    if not user.get("ai_enabled", 1):
        await message.answer("🤖 Нейросеть отключена в настройках.", reply_markup=back_to_main_kb())
        return

    if message.from_user.id in active_generations:
        await message.answer("⏳ Подожди, ещё думаю… Нажми «⏹ Остановить» если хочешь прервать.")
        return

    can_send, remaining = await can_send_message(message.from_user.id)
    if not can_send:
        sub = user.get("subscription", "free")
        limit = SUBSCRIPTION_LIMITS[sub]["messages_per_day"]
        await message.answer(
            f"⛔ <b>Дневной лимит исчерпан</b>\n\n"
            f"Использовано <b>{limit}</b> из <b>{limit}</b> сообщений сегодня.\n"
            f"🕛 Лимит обновится в полночь.\n\n"
            f"Чтобы снять ограничения — оформи подписку в магазине 💎",
            reply_markup=back_to_main_kb(),
            parse_mode="HTML",
        )
        return

    file_bytes, file_name, file_mime = await _download_attachment(message, bot)
    if file_mime == "TOO_BIG":
        await message.answer("📦 Файл слишком большой (максимум 20 МБ). Пришли меньший файл.")
        return

    sub = user.get("subscription", "free")
    if file_bytes and not SUBSCRIPTION_LIMITS[sub].get("can_analyze_files", True):
        await message.answer(
            "📎 <b>Анализ файлов и фото</b> доступен только в платных подписках.\n\n"
            "Оформи Plus или выше в магазине 💎",
            reply_markup=back_to_main_kb(),
            parse_mode="HTML",
        )
        return

    user_text = message.caption or message.text or "Опиши, что на этом изображении."
    await add_message(chat_id, "user", user_text, tg_message_id=message.message_id)

    chat = await get_chat(chat_id)
    can_search = SUBSCRIPTION_LIMITS[sub].get("can_search", False)
    use_search = bool(chat and chat.get("search_enabled")) and not file_bytes and can_search

    history = _history_for_gemini(await get_messages(chat_id))

    model = SUBSCRIPTION_LIMITS[sub]["model"]
    max_tokens = SUBSCRIPTION_LIMITS[sub]["max_tokens"]

    placeholder = await message.answer(
        "⏳ <i>Думаю…</i>",
        parse_mode="HTML",
        reply_markup=stop_generation_kb(chat_id)
    )

    task = asyncio.create_task(_run_generation(
        message.from_user.id, chat_id, placeholder, history, model, max_tokens,
        use_search, file_bytes, file_name, file_mime, bot,
    ))
    active_generations[message.from_user.id] = {"task": task, "chat_id": chat_id}


@router.callback_query(F.data.startswith("ai:stop:"))
async def stop_generation(callback: CallbackQuery):
    entry = active_generations.get(callback.from_user.id)
    if entry:
        entry["task"].cancel()
        await callback.answer("⏹ Останавливаю…")
    else:
        await callback.answer("Генерация уже завершена")
