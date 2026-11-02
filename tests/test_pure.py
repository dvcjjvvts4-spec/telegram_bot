from datetime import date, timedelta

import pytest

from bot import gemini, nutrition, parsing

TODAY = date(2026, 11, 2)  # понедельник


def test_bmr_formula():
    assert nutrition.bmr(80, 180, 20, "m") == 1830
    assert nutrition.bmr(60, 165, 30, "f") == 1320.25


def test_norms_for_weight_loss():
    norms = nutrition.calc_norms(90, 180, 20, "m", 3, 80)
    assert norms.goal == "похудение"
    assert norms.maintenance == round(1930 * 1.55)
    assert norms.kcal == round(1930 * 1.55 * 0.825)
    assert norms.protein == 162 and norms.fat == 81
    assert norms.water_ml == 2925
    assert not norms.floored


def test_norms_never_below_bmr():
    norms = nutrition.calc_norms(90, 180, 20, "m", 1, 60)
    assert norms.kcal == norms.bmr
    assert norms.floored


@pytest.mark.parametrize("target, goal", [(80, "поддержание"), (80.5, "поддержание"), (85, "набор")])
def test_goal_detection(target, goal):
    assert nutrition.calc_norms(80, 180, 20, "m", 2, target).goal == goal


def test_weekly_change_needs_a_week_of_data():
    assert nutrition.weekly_change([(TODAY, 80), (TODAY + timedelta(days=3), 79)]) is None


def test_weekly_change_and_forecast():
    points = [(TODAY + timedelta(days=d), 80 - 0.1 * d) for d in range(15)]
    weekly = nutrition.weekly_change(points)
    assert weekly == pytest.approx(-0.7)
    assert not nutrition.too_fast_loss(weekly, 80)
    assert nutrition.too_fast_loss(-1.0, 80)
    assert nutrition.forecast_date(80, 73, weekly, TODAY) == TODAY + timedelta(days=70)
    assert nutrition.forecast_date(80, 85, weekly, TODAY) is None


def test_progress_percent():
    assert nutrition.progress_percent(90, 85, 80) == 50
    assert nutrition.progress_percent(90, 95, 80) == 0


@pytest.mark.parametrize("text, ml", [
    ("+300", 300), ("+300 мл", 300), ("300мл", 300), ("0,5 л", 500), ("+1.5л", 1500),
    ("300", None), ("+0", None), ("+9000", None), ("привет", None),
])
def test_parse_water(text, ml):
    assert parsing.parse_water(text) == ml


@pytest.mark.parametrize("text, kg", [
    ("вес 82,5", 82.5), ("Вес: 80 кг", 80), ("вес 5", None), ("82", None),
])
def test_parse_weight(text, kg):
    assert parsing.parse_weight(text) == kg


def test_parse_times_validates_and_sorts():
    assert parsing.parse_times("20:00, 8:00") == ["08:00", "20:00"]
    assert parsing.parse_times("25:00") is None
    assert parsing.parse_times("утром") is None


@pytest.mark.parametrize("text, kind, day, weekdays", [
    ("завтра", "once", date(2026, 11, 3), ""),
    ("чт", "once", date(2026, 11, 5), ""),
    ("пн", "once", TODAY, ""),
    ("12.10", "once", date(2027, 10, 12), ""),
    ("12.12", "once", date(2026, 12, 12), ""),
    ("пн,ср", "weekly", None, "0,2"),
    ("каждую пятницу", "weekly", None, "4"),
    ("каждый день", "daily", None, ""),
])
def test_parse_when(text, kind, day, weekdays):
    assert parsing.parse_when(text, TODAY) == parsing.When(kind, day, weekdays)


@pytest.mark.parametrize("text", ["31.02", "когда-нибудь", "18"])
def test_parse_when_rejects_garbage(text):
    assert parsing.parse_when(text, TODAY) is None


def test_parse_task():
    when, title = parsing.parse_task("чт: забрать посылку", TODAY)
    assert title == "забрать посылку" and when.date == date(2026, 11, 5)
    assert parsing.parse_task("просто текст", TODAY) is None
    assert parsing.parse_task("18:30 встреча", TODAY) is None


def test_parse_remind():
    when, time, text = parsing.parse_remind("пн,ср 19:00 тренировка", TODAY)
    assert (when.kind, when.weekdays, time, text) == ("weekly", "0,2", "19:00", "тренировка")
    assert parsing.parse_remind("8:30 позвонить", TODAY)[0].kind == "daily"
    assert parsing.parse_remind("25:00 нельзя", TODAY) is None


def test_course_end_counts_today_only_if_dose_is_ahead():
    assert parsing.course_end(7, TODAY, ["08:00", "20:00"], "12:00") == date(2026, 11, 8)
    assert parsing.course_end(7, TODAY, ["08:00"], "12:00") == date(2026, 11, 9)
    assert parsing.course_end(1, TODAY, ["13:00"], "12:00") == TODAY


@pytest.mark.parametrize("text, days", [("14", 14), ("0", None), ("абв", None), ("99999", None)])
def test_parse_course_days(text, days):
    assert parsing.parse_course_days(text) == days


def test_parse_meal():
    assert parsing.parse_meal("Гречка; 350")["kcal"] == 350
    assert parsing.parse_meal("Гречка; 350; 12; 4; 60")["carbs"] == 60
    assert parsing.parse_meal("Гречка; 350; 12") is None
    assert parsing.parse_meal("Гречка; много") is None


def test_parse_corrections():
    aliases = {"ккал": "kcal", "вес": "grams", "название": "name"}
    result = parsing.parse_corrections("ккал 350, вес 82,5, название Плов 2", aliases)
    assert result == {"kcal": 350, "grams": 82.5, "name": "Плов 2"}


def test_gemini_normalize_rejects_bad_answers():
    assert gemini.normalize({"type": "food", "kcal": "много"}) == {"type": "other"}
    assert gemini.normalize({"type": "scale", "weight_kg": 5000}) == {"type": "other"}
    assert gemini.normalize({"type": "virus"}) == {"type": "other"}
    food = gemini.normalize({"type": "food", "name": "Суп", "kcal": 200, "fat": -1, "x": 1})
    assert food["fat"] is None and "x" not in food


def test_gemini_extract_json():
    assert gemini.extract_json('```json\n{"type": "other"}\n```') == {"type": "other"}
    with pytest.raises(gemini.RecognitionError):
        gemini.extract_json("нет данных")
