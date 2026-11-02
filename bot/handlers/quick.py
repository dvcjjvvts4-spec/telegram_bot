"""Быстрый ввод обычным текстом. Подключается последним: забирает всё, что не разобрали другие."""

from aiogram import F, Router
from aiogram.types import Message

from bot import config, repo, reports
from bot.handlers.tasks import add_from_text
from bot.handlers.tracking import water_text
from bot.keyboards import water_keyboard
from bot.parsing import parse_water, parse_weight

router = Router()


@router.message(F.text)
async def quick_text(message: Message, db: repo.Db) -> None:
    text = message.text
    ml = parse_water(text)
    if ml:
        await repo.add_water(db, config.today(), ml)
        await message.answer(await water_text(db), reply_markup=water_keyboard())
        return

    kg = parse_weight(text)
    if kg:
        await repo.add_weight(db, config.today(), kg)
        await message.answer(await reports.weight_report(db, config.today()))
        return

    if await add_from_text(message, db, text):
        return
    await message.answer("Не понял. Примеры команд: /help")
