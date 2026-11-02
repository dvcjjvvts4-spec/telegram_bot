from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, Message

router = Router()

COMMANDS = [
    ("today", "Сводка за сегодня"),
    ("pills", "Таблетки"),
    ("pill_add", "Добавить таблетку"),
    ("pill_log", "Журнал приёмов"),
    ("water", "Вода"),
    ("tasks", "Задачи на сегодня"),
    ("task", "Добавить задачу"),
    ("meal", "Записать еду вручную"),
    ("weight", "Вес и прогресс"),
    ("profile", "Заполнить профиль"),
    ("remind", "Создать напоминание"),
    ("reminders", "Список напоминаний"),
    ("summary", "Время сводок"),
    ("carry", "Автоперенос задач"),
    ("cancel", "Отменить текущий ввод"),
    ("help", "Как пользоваться"),
]
BOT_COMMANDS = [BotCommand(command=c, description=d) for c, d in COMMANDS]

HELP = """Отправляй боту:
• фото еды, весов или часов: распознаю и спрошу перед записью
• +300 мл или 0,5 л: вода
• вес 82,5: вес
• чт: забрать посылку / 12.10: дело / пн,ср: английский / каждый день: зарядка: задача

Напоминания:
/remind 18:30 позвонить
/remind пн,ср 19:00 тренировка
/remind завтра 10:00 дело

Таблетки: /pill_add, затем /pills и /pill_log.
Сначала заполни /profile, чтобы получить нормы."""


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        f"Привет, {message.from_user.first_name}! "
        "Я твой помощник: еда, вода, вес, задачи и таблетки.\n\n" + HELP
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.")
