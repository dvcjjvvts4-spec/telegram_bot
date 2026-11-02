"""Фото -> распознавание -> подтверждение -> запись."""

import io
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import config, gemini, repo
from bot.handlers.profile import norms_text
from bot.keyboards import draft_keyboard
from bot.parsing import parse_corrections

router = Router()
log = logging.getLogger(__name__)
MAX_FILE_BYTES = 10 * 1024 * 1024


class Draft(StatesGroup):
    waiting = State()
    editing = State()


ALIASES = {
    "food": {
        "название": "name", "блюдо": "name", "вес": "grams", "граммы": "grams", "г": "grams",
        "ккал": "kcal", "калории": "kcal", "белки": "protein", "б": "protein",
        "жиры": "fat", "ж": "fat", "углеводы": "carbs", "у": "carbs",
    },
    "scale": {
        "вес": "weight_kg", "жир": "fat_pct", "мышцы": "muscle_kg",
    },
    "watch": {
        "шаги": "steps", "ккал": "active_kcal", "калории": "active_kcal",
        "тренировки": "workouts", "тренировка": "workouts",
    },
}
EDIT_HINT = {
    "food": "Напиши, что поменять: ккал 350, белки 20, вес 250, название Плов",
    "scale": "Напиши, что поменять: вес 82,5, жир 18, мышцы 62",
    "watch": "Напиши, что поменять: шаги 9000, ккал 400, тренировки Бег 30 мин",
}


def show(value, unit: str = "") -> str:
    return "?" if value is None else f"{value:g}{unit}" if isinstance(value, float | int) else value


def draft_text(draft: dict) -> str:
    if draft["type"] == "food":
        return (
            f"🍽 {show(draft['name'])}, примерно {show(draft['grams'], ' г')}\n"
            f"{show(draft['kcal'])} ккал, Б {show(draft['protein'])} / "
            f"Ж {show(draft['fat'])} / У {show(draft['carbs'])}"
        )
    if draft["type"] == "scale":
        return (
            f"⚖️ Вес: {show(draft['weight_kg'], ' кг')}\n"
            f"Жир: {show(draft['fat_pct'], '%')}, мышцы: {show(draft['muscle_kg'], ' кг')}"
        )
    return (
        f"⌚️ Шаги: {show(draft['steps'])}\n"
        f"Активные калории: {show(draft['active_kcal'])}\n"
        f"Тренировки: {show(draft['workouts'])}"
    )


async def process_image(
    message: Message, state: FSMContext, bot: Bot, file_id: str, size: int | None, mime: str
) -> None:
    if size and size > MAX_FILE_BYTES:
        await message.answer("Файл больше 10 МБ, отправь поменьше.")
        return
    status = await message.answer("Смотрю на фото...")
    buffer = io.BytesIO()
    try:
        await bot.download(file_id, destination=buffer)
        draft = await gemini.recognize(buffer.getvalue(), mime)
    except gemini.RecognitionError as error:
        log.warning("Распознавание не удалось: %s", error)
        await status.edit_text(
            f"Не удалось распознать: {error}.\nЕду можно записать вручную: /meal"
        )
        return
    if draft["type"] == "other":
        await status.edit_text("Не похоже на еду, весы или часы. Попробуй другое фото.")
        return
    await state.set_state(Draft.waiting)
    await state.update_data(draft=draft)
    await status.edit_text(draft_text(draft), reply_markup=draft_keyboard())


@router.message(F.photo)
async def got_photo(message: Message, state: FSMContext, bot: Bot) -> None:
    photo = message.photo[-1]  # последний вариант имеет самое большое разрешение
    await process_image(message, state, bot, photo.file_id, photo.file_size, "image/jpeg")


@router.message(F.document.mime_type.startswith("image/"))
async def got_document(message: Message, state: FSMContext, bot: Bot) -> None:
    file = message.document
    await process_image(message, state, bot, file.file_id, file.file_size, file.mime_type)


async def save_draft(db: repo.Db, draft: dict) -> str:
    day = config.today()
    if draft["type"] == "food":
        await repo.add_meal(
            db, day, draft["name"] or "Без названия", draft["grams"], draft["kcal"] or 0,
            draft["protein"] or 0, draft["fat"] or 0, draft["carbs"] or 0,
        )
        return "Записал."
    if draft["type"] == "scale":
        await repo.add_weight(db, day, draft["weight_kg"], draft["fat_pct"], draft["muscle_kg"])
        if await repo.get_profile(db):
            return "Записал, нормы пересчитаны.\n\n" + await norms_text(db)
        return "Записал."
    await repo.save_activity(
        db, day, draft["steps"], draft["active_kcal"], draft["workouts"]
    )
    return "Записал. Активные калории добавлены к норме дня."


@router.callback_query(F.data.startswith("ai:"))
async def draft_button(callback: CallbackQuery, state: FSMContext, db: repo.Db) -> None:
    action = callback.data.split(":")[1]
    draft = (await state.get_data()).get("draft")
    if action == "cancel" or not draft:
        await state.clear()
        await callback.message.edit_text("Отменено." if draft else "Черновик устарел, пришли фото ещё раз.")
    elif action == "save":
        await state.clear()
        await callback.message.edit_text(await save_draft(db, draft))
    else:
        await state.set_state(Draft.editing)
        await callback.message.edit_reply_markup()
        await callback.message.answer(EDIT_HINT[draft["type"]])
    await callback.answer()


@router.message(Draft.editing, F.text)
async def got_correction(message: Message, state: FSMContext) -> None:
    draft = (await state.get_data()).get("draft")
    changes = parse_corrections(message.text, ALIASES[draft["type"]])
    if not changes:
        await message.answer("Не понял. " + EDIT_HINT[draft["type"]])
        return
    draft.update(changes)
    await state.update_data(draft=draft)
    await state.set_state(Draft.waiting)
    await message.answer(draft_text(draft), reply_markup=draft_keyboard())
