from aiogram import BaseMiddleware


class OwnerOnly(BaseMiddleware):
    """Пропускает только владельца. Остальным бот не отвечает вовсе."""

    def __init__(self, owner_id: int) -> None:
        self.owner_id = owner_id

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is None or user.id != self.owner_id:
            return None
        return await handler(event, data)


class CommandResetsState(BaseMiddleware):
    """Команда прерывает начатый ввод: иначе /today стало бы названием таблетки."""

    async def __call__(self, handler, event, data):
        state = data.get("state")
        if state and (event.text or "").startswith("/"):
            await state.clear()
            data["raw_state"] = None  # фильтры состояний читают это значение
        return await handler(event, data)
