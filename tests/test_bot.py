"""Проверка настоящего диспетчера и планировщика с поддельным подключением к Telegram."""

import asyncio
from datetime import date, datetime, timedelta

import aiosqlite
import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, PhotoSize, Update, User

from bot import config, db as database, gemini, repo, scheduler
from bot.handlers import alarms, photo, pills, profile, quick, start, tasks, tracking
from bot.main import build_dispatcher

OWNER = config.ALLOWED_USER_ID
TZ = config.TZ


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent = []
        self.fail = False
        self.next_id = 100

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        yield b""

    async def make_request(self, bot, method, timeout=None):
        if self.fail:
            raise RuntimeError("сеть недоступна")
        self.sent.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            self.next_id += 1
            return Message(
                message_id=self.next_id, date=datetime.now(TZ),
                chat=Chat(id=OWNER, type="private"), text=method.text,
            ).as_(bot)
        return True


class Env:
    def __init__(self):
        self.update_id = 0

    async def start(self):
        self.db = await database.connect(":memory:")
        self.session = FakeSession()
        self.bot = Bot(token="123456:TEST", session=self.session)
        # Роутер подключается к одному диспетчеру, а каждый тест создаёт новый.
        for module in (start, profile, pills, alarms, tasks, tracking, photo, quick):
            module.router._parent_router = None
        self.dp = build_dispatcher(self.db, OWNER)

    def texts(self):
        return [
            m.text for m in self.session.sent if isinstance(m, (SendMessage, EditMessageText))
        ]

    def last_markup(self):
        sends = [m for m in self.session.sent if isinstance(m, (SendMessage, EditMessageText))]
        return sends[-1].reply_markup

    async def send(self, text, user_id=OWNER):
        self.update_id += 1
        user = User(id=user_id, is_bot=False, first_name="Тест")
        message = Message(
            message_id=self.update_id, date=datetime.now(TZ),
            chat=Chat(id=user_id, type="private"), from_user=user, text=text,
        )
        await self.dp.feed_update(self.bot, Update(update_id=self.update_id, message=message))

    async def send_photo(self):
        self.update_id += 1
        user = User(id=OWNER, is_bot=False, first_name="Тест")
        message = Message(
            message_id=self.update_id, date=datetime.now(TZ),
            chat=Chat(id=OWNER, type="private"), from_user=user,
            photo=[PhotoSize(file_id="f", file_unique_id="u", width=10, height=10)],
        )
        await self.dp.feed_update(self.bot, Update(update_id=self.update_id, message=message))

    async def press(self, data):
        self.update_id += 1
        user = User(id=OWNER, is_bot=False, first_name="Тест")
        message = Message(
            message_id=1, date=datetime.now(TZ), chat=Chat(id=OWNER, type="private"), text="x"
        )
        callback = CallbackQuery(
            id=str(self.update_id), from_user=user, chat_instance="1", data=data, message=message
        )
        await self.dp.feed_update(
            self.bot, Update(update_id=self.update_id, callback_query=callback)
        )

    async def tick(self, now):
        await scheduler.tick(self.db, self.bot, OWNER, now)


def run(scenario):
    async def wrapper():
        env = Env()
        await env.start()
        try:
            await scenario(env)
        finally:
            await env.db.close()
    asyncio.run(wrapper())


async def add_pill(env, created, stock=10.0, per_dose=1.0, times=("08:00",), weekdays=""):
    return await repo.add_pill(
        env.db, "Витамин", "1 таблетка", per_dose, stock, list(times), weekdays,
        int(created.timestamp()),
    )


async def first_event(env):
    async with env.db.execute("SELECT * FROM alarm_events ORDER BY id") as cursor:
        return await cursor.fetchone()


NOV1 = datetime(2026, 11, 1, 12, 0, tzinfo=TZ)
MORNING = datetime(2026, 11, 2, 8, 0, 30, tzinfo=TZ)


def test_stranger_gets_no_answer():
    async def scenario(env):
        await env.send("/start", user_id=999)
        assert env.session.sent == []
        await env.send("/start")
        assert "Привет, Тест" in env.texts()[0]
    run(scenario)


def test_water_text_and_buttons():
    async def scenario(env):
        await env.send("+300 мл")
        await env.press("water:500")
        await env.press("water:undo")
        assert await repo.water_total(env.db, config.today()) == 300
    run(scenario)


def test_profile_flow_gives_norms_and_new_weight_recalculates():
    async def scenario(env):
        await env.send("/profile")
        for answer in ("90", "180", "20", "м", "3", "80"):
            await env.send(answer)
        assert "похудение" in env.texts()[-1]
        before = await repo.get_norms(env.db)
        await env.send("вес 88")
        after = await repo.get_norms(env.db)
        assert after.kcal < before.kcal
        assert "Вес: 88 кг" in env.texts()[-1]
    run(scenario)


def test_invalid_profile_answer_is_asked_again():
    async def scenario(env):
        await env.send("/profile")
        await env.send("абв")
        assert "число" in env.texts()[-1]
        await env.send("/today")
        assert "Сегодня" in env.texts()[-1]
    run(scenario)


def test_add_pill_dialog_and_command_does_not_become_name():
    async def scenario(env):
        await env.send("/pill_add")
        await env.send("/today")
        assert await repo.list_pills(env.db) == []
        await env.send("/pill_add")
        for answer in ("Омега", "1 капсула", "08:00, 20:00", "пн, ср", "абв", "-", "1", "30"):
            await env.send(answer)
        pills = await repo.list_pills(env.db)
        assert pills[0]["name"] == "Омега" and pills[0]["stock"] == 30
        alarms = await repo.pill_alarms(env.db, pills[0]["id"])
        assert [a["time"] for a in alarms] == ["08:00", "20:00"]
        assert alarms[0]["weekdays"] == "0,2"
        await env.send("/pills")
        assert "Остаток: 30 шт., примерно на 52 дн." in env.texts()[-1]
    run(scenario)


def test_pill_fires_once_and_take_decrements_stock_once():
    async def scenario(env):
        pill_id = await add_pill(env, NOV1)
        await env.tick(MORNING)
        await env.tick(MORNING + timedelta(seconds=20))
        assert sum("Пора принять" in t for t in env.texts()) == 1

        event = await first_event(env)
        await env.press(f"ev:done:{event['id']}")
        await env.press(f"ev:done:{event['id']}")
        assert (await repo.get_pill(env.db, pill_id))["stock"] == 9
        answers = [m for m in env.session.sent if isinstance(m, AnswerCallbackQuery)]
        assert "Уже отмечено" in answers[-1].text

        await env.tick(MORNING + timedelta(hours=2))
        assert sum("Пора принять" in t for t in env.texts()) == 1
    run(scenario)


def test_undo_restores_stock():
    async def scenario(env):
        pill_id = await add_pill(env, NOV1)
        await env.tick(MORNING)
        event = await first_event(env)
        await env.press(f"ev:done:{event['id']}")
        await env.press(f"ev:undo:{event['id']}")
        assert (await repo.get_pill(env.db, pill_id))["stock"] == 10
        assert (await first_event(env))["status"] == "pending"
    run(scenario)


def test_unanswered_pill_repeats_then_is_missed_and_can_be_taken_late():
    async def scenario(env):
        pill_id = await add_pill(env, NOV1)
        for minutes in (0, 30, 60, 90):
            await env.tick(MORNING + timedelta(minutes=minutes))
        assert sum("Пора принять" in t for t in env.texts()) == config.PILL_MAX_PINGS
        assert any("Записал как пропущенный" in t for t in env.texts())
        event = await first_event(env)
        assert event["status"] == "missed"

        await env.tick(MORNING + timedelta(minutes=120))
        assert sum("Записал как пропущенный" in t for t in env.texts()) == 1

        await env.press(f"ev:done:{event['id']}")
        assert (await first_event(env))["status"] == "done"
        assert (await repo.get_pill(env.db, pill_id))["stock"] == 9
    run(scenario)


def test_snooze_delays_next_message(monkeypatch):
    # Кнопка ⏰ считает от config.now(), поэтому фиксируем «сейчас» на дне теста,
    # иначе с реальной датой планировщик дошлёт пропущенные за эти дни дозы.
    pressed_at = MORNING + timedelta(seconds=5)
    monkeypatch.setattr(config, "now", lambda: pressed_at)

    async def scenario(env):
        await add_pill(env, NOV1)
        await env.tick(MORNING)
        event = await first_event(env)
        await env.press(f"ev:snooze:{event['id']}")
        count = sum("Пора принять" in t for t in env.texts())
        await env.tick(pressed_at + timedelta(minutes=1))
        assert sum("Пора принять" in t for t in env.texts()) == count
        await env.tick(pressed_at + timedelta(minutes=16))
        assert sum("Пора принять" in t for t in env.texts()) == count + 1
    run(scenario)


def test_restart_during_outage_still_delivers_late_with_warning():
    async def scenario(env):
        await add_pill(env, NOV1, times=("23:30",))
        await env.tick(datetime(2026, 11, 2, 0, 40, tzinfo=TZ))
        text = next(t for t in env.texts() if "Пора принять" in t)
        assert "с опозданием" in text
        assert "01.11" in text
    run(scenario)


def test_network_failure_retries_on_next_tick():
    async def scenario(env):
        await add_pill(env, NOV1)
        env.session.fail = True
        with pytest.raises(RuntimeError):
            await env.tick(MORNING)
        env.session.fail = False
        await env.tick(MORNING + timedelta(seconds=20))
        assert sum("Пора принять" in t for t in env.texts()) == 1
    run(scenario)


def test_pill_added_after_its_time_starts_next_occurrence():
    async def scenario(env):
        await add_pill(env, MORNING + timedelta(hours=3))
        await env.tick(MORNING + timedelta(hours=4))
        assert await first_event(env) is None
        await env.tick(MORNING + timedelta(days=1))
        assert await first_event(env) is not None
    run(scenario)


def test_weekday_schedule_respected():
    async def scenario(env):
        await add_pill(env, NOV1, weekdays="1")  # вторник, а MORNING это понедельник
        await env.tick(MORNING)
        assert await first_event(env) is None
    run(scenario)


def test_deleted_pill_stops_reminders():
    async def scenario(env):
        pill_id = await add_pill(env, NOV1)
        await env.tick(MORNING)
        await env.press(f"pill:del:{pill_id}")
        await env.tick(MORNING + timedelta(hours=2))
        assert sum("Пора принять" in t for t in env.texts()) == 1
        assert (await first_event(env))["status"] == "cancelled"
    run(scenario)


def test_course_stops_after_last_day_and_keeps_late_last_dose():
    async def scenario(env):
        await repo.add_pill(
            env.db, "Курс", "1 шт", 1, None, ["23:30"], "",
            int(datetime(2026, 11, 2, 12, 0, tzinfo=TZ).timestamp()), date(2026, 11, 2),
        )
        await env.tick(datetime(2026, 11, 2, 23, 31, tzinfo=TZ))
        await env.tick(datetime(2026, 11, 3, 0, 5, tzinfo=TZ))  # повтор приёма уже после полуночи
        assert sum("Пора принять" in t for t in env.texts()) == 2
        assert sum("Курс закончился" in t for t in env.texts()) == 1
        assert await repo.list_pills(env.db) == []

        event = await first_event(env)
        assert event["status"] == "pending"
        await env.press(f"ev:done:{event['id']}")
        assert (await first_event(env))["status"] == "done"

        await env.tick(datetime(2026, 11, 3, 23, 31, tzinfo=TZ))
        assert sum("Пора принять" in t for t in env.texts()) == 2
        assert sum("Курс закончился" in t for t in env.texts()) == 1
    run(scenario)


def test_course_dialog_and_change_for_existing_pill():
    async def scenario(env):
        await env.send("/pill_add")
        for answer in ("Антибиотик", "1 шт", "23:59", "каждый день", "7", "1", "-"):
            await env.send(answer)
        pill = (await repo.list_pills(env.db))[0]
        assert pill["end_date"] is not None
        assert "Курс: до" in env.texts()[-1]

        await env.press(f"pill:course:{pill['id']}")
        await env.send("-")
        assert (await repo.get_pill(env.db, pill["id"]))["end_date"] is None
    run(scenario)


def test_old_database_gets_new_column_without_losing_data(tmp_path):
    async def scenario():
        path = str(tmp_path / "old.sqlite3")
        old = await aiosqlite.connect(path)
        await old.execute(
            """CREATE TABLE pills (id INTEGER PRIMARY KEY, name TEXT NOT NULL, dose TEXT NOT NULL,
               per_dose REAL NOT NULL DEFAULT 1, stock REAL, active INTEGER NOT NULL DEFAULT 1)"""
        )
        await old.execute("INSERT INTO pills (name, dose, stock) VALUES ('Старая', '1 шт', 9)")
        await old.commit()
        await old.close()

        db = await database.connect(path)
        pills = await repo.list_pills(db)
        assert pills[0]["name"] == "Старая" and pills[0]["stock"] == 9
        assert pills[0]["end_date"] is None
        await db.close()
    asyncio.run(scenario())


def test_low_stock_warning_and_refill():
    async def scenario(env):
        pill_id = await add_pill(env, NOV1, stock=4)
        await env.tick(MORNING)
        event = await first_event(env)
        await env.press(f"ev:done:{event['id']}")
        assert "заканчивается" in env.texts()[-1]
        await env.press(f"pill:refill:{pill_id}")
        await env.send("30")
        assert "Остаток: 33 шт." in env.texts()[-1]
    run(scenario)


def test_reminder_create_fire_and_delete():
    async def scenario(env):
        await env.send("/remind 18:30 позвонить")
        reminders = await repo.list_reminders(env.db, config.today())
        assert reminders[0]["text"] == "позвонить"
        tomorrow = config.today() + timedelta(days=1)
        fire = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 18, 30, 5, tzinfo=TZ)
        # Часы теста прыгают на сутки: фиксируем создание, чтобы сегодняшний раз не сработал.
        await env.db.execute("UPDATE alarms SET created_at = ?", (int(fire.timestamp()) - 3600,))
        await env.db.commit()
        await env.tick(fire)
        await env.tick(fire + timedelta(hours=1))
        assert sum("🔔 позвонить" in t for t in env.texts()) == 1

        event = await first_event(env)
        await env.press(f"ev:done:{event['id']}")
        assert (await first_event(env))["status"] == "done"

        await env.press(f"rem:del:{reminders[0]['id']}")
        assert await repo.list_reminders(env.db, config.today()) == []
    run(scenario)


def test_one_time_reminder_fires_only_on_its_date():
    async def scenario(env):
        await env.send("/remind завтра 10:00 разовое")
        tomorrow = config.today() + timedelta(days=1)
        fire = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 10, 1, tzinfo=TZ)
        await env.tick(fire - timedelta(days=1))
        assert await first_event(env) is None
        await env.tick(fire)
        await env.tick(fire + timedelta(days=1))
        assert sum("🔔 разовое" in t for t in env.texts()) == 1
    run(scenario)


def test_repeated_button_with_unchanged_text_does_not_crash():
    async def scenario(env):
        real = env.session.make_request

        async def not_modified(bot, method, timeout=None):
            if isinstance(method, EditMessageText):
                raise TelegramBadRequest(method, "Bad Request: message is not modified: same")
            return await real(bot, method, timeout)

        env.session.make_request = not_modified
        await env.press("water:undo")  # исключение здесь уронило бы тест
    run(scenario)


def test_photo_goes_through_recognition_to_draft(monkeypatch):
    async def scenario(env):
        async def fake_download(file, destination):
            destination.write(b"image")

        async def fake_recognize(image, mime):
            assert image == b"image" and mime == "image/jpeg"
            return {"type": "scale", "weight_kg": 81.5, "fat_pct": 18.0, "muscle_kg": None}

        monkeypatch.setattr(env.bot, "download", fake_download, raising=False)
        monkeypatch.setattr(gemini, "recognize", fake_recognize)
        await env.send_photo()
        assert "81.5 кг" in env.texts()[-1]
        assert env.last_markup() is not None
        assert await repo.weight_points(env.db, date(2020, 1, 1)) == []
        await env.press("ai:save")
        assert [kg for _, kg in await repo.weight_points(env.db, date(2020, 1, 1))] == [81.5]
    run(scenario)


def test_recognition_failure_is_reported_not_saved(monkeypatch):
    async def scenario(env):
        async def fake_download(file, destination):
            destination.write(b"image")

        async def broken(image, mime):
            raise gemini.RecognitionError("не задан GEMINI_API_KEY")

        monkeypatch.setattr(env.bot, "download", fake_download, raising=False)
        monkeypatch.setattr(gemini, "recognize", broken)
        await env.send_photo()
        assert "Не удалось распознать" in env.texts()[-1]
    run(scenario)


def test_tasks_quick_input_buttons_and_carry_over():
    async def scenario(env):
        today = config.today()
        await env.send("сегодня: забрать посылку")
        task = (await repo.tasks_for_day(env.db, today))[0]
        await env.send("/tasks")
        assert len(env.last_markup().inline_keyboard) == 1

        tomorrow = today + timedelta(days=1)
        await env.press(f"task:failed:{task['id']}:{today}")
        await repo.carry_over_tasks(env.db, tomorrow)
        assert [t["id"] for t in await repo.tasks_for_day(env.db, tomorrow)] == [task["id"]]

        await repo.set_task_status(env.db, task["id"], tomorrow, "done")
        await repo.carry_over_tasks(env.db, tomorrow + timedelta(days=1))
        assert await repo.tasks_for_day(env.db, tomorrow + timedelta(days=1)) == []
    run(scenario)


def test_summaries_are_sent_once_a_day():
    async def scenario(env):
        await add_pill(env, NOV1)
        await env.tick(MORNING)
        await env.tick(MORNING + timedelta(minutes=1))
        assert sum("Доброе утро" in t for t in env.texts()) == 1
        await env.tick(datetime(2026, 11, 2, 21, 0, tzinfo=TZ))
        assert sum("Итог дня" in t for t in env.texts()) == 1
    run(scenario)


def test_activity_adds_to_daily_norm():
    async def scenario(env):
        await env.send("/profile")
        for answer in ("90", "180", "20", "м", "3", "90"):
            await env.send(answer)
        norm = (await repo.get_norms(env.db)).kcal
        await repo.save_activity(env.db, config.today(), 9000, 400, None)
        await env.send("/today")
        assert f"0/{norm + 400} ккал" in env.texts()[-1]
    run(scenario)


def test_photo_draft_saves_only_after_confirmation():
    async def scenario(env):
        from aiogram.fsm.storage.base import StorageKey
        key = StorageKey(bot_id=env.bot.id, chat_id=OWNER, user_id=OWNER)
        draft = {
            "type": "food", "name": "Суп", "grams": 300.0, "kcal": 200.0,
            "protein": 10.0, "fat": 5.0, "carbs": 20.0,
        }
        await env.dp.storage.set_data(key, {"draft": draft})
        await env.press("ai:edit")
        await env.send("ккал 250")
        assert (await repo.day_totals(env.db, config.today()))["kcal"] == 0
        await env.press("ai:save")
        assert (await repo.day_totals(env.db, config.today()))["kcal"] == 250
    run(scenario)
