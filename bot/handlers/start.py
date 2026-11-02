from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router()
@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        f"Привет, {message.from_user.first_name}! "
        "Я твой помощник по привычкам - будем вместе отслеживать прогерсс и вырабатывать новые."
    )