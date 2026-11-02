import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.filters import ExceptionMessageFilter

from bot import config, db as database
from bot.handlers import alarms, photo, pills, profile, quick, start, tasks, tracking
from bot.handlers.start import BOT_COMMANDS
from bot.middlewares import CommandResetsState, OwnerOnly
from bot.scheduler import run_scheduler


async def ignore_not_modified(event) -> bool:
    """Telegram считает ошибкой правку, которая ничего не меняет. Для нас это норма."""
    return True


def build_dispatcher(db, owner_id: int) -> Dispatcher:
    dp = Dispatcher()
    dp["db"] = db  # aiogram передаст db в каждый обработчик, где есть такой аргумент
    dp.update.outer_middleware(OwnerOnly(owner_id))
    dp.message.outer_middleware(CommandResetsState())
    # Фильтр сравнивает с начала строки, а Telegram пишет перед ошибкой свой префикс.
    dp.errors.register(ignore_not_modified, ExceptionMessageFilter(".*message is not modified"))
    # Порядок важен: quick забирает любой текст, поэтому он последний.
    dp.include_routers(
        start.router, profile.router, pills.router, alarms.router,
        tasks.router, tracking.router, photo.router, quick.router,
    )
    return dp


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    db = await database.connect(config.DB_PATH)
    bot = Bot(token=config.BOT_TOKEN)
    dp = build_dispatcher(db, config.ALLOWED_USER_ID)
    await bot.set_my_commands(BOT_COMMANDS)

    scheduler = asyncio.create_task(run_scheduler(db, bot, config.ALLOWED_USER_ID))
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.cancel()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
