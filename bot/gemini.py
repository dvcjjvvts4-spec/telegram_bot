"""Распознавание фото. Остальной бот вызывает только recognize и normalize,
поэтому Gemini можно заменить, переписав один этот файл."""

import base64
import json
import re
import ssl

import aiohttp
import certifi

from bot.config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_PROXY

# Python с python.org не видит сертификаты macOS, поэтому берём список из certifi.
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PROMPT = """Определи тип изображения и верни только JSON без пояснений.
Типы:
- food: еда. Поля: name (название по-русски), grams, kcal, protein, fat, carbs. Оцени порцию целиком.
- scale: скриншот приложения умных весов. Поля: weight_kg, fat_pct, muscle_kg.
- watch: скриншот активности с часов. Поля: steps, active_kcal, workouts (строка).
- other: всё остальное.
Формат: {"type": "food", "name": "...", "grams": 0, ...}.
Если значения не видно, укажи null. Не выдумывай числа на скриншотах."""

FIELDS = {
    "food": {"name": str, "grams": float, "kcal": float, "protein": float, "fat": float, "carbs": float},
    "scale": {"weight_kg": float, "fat_pct": float, "muscle_kg": float},
    "watch": {"steps": float, "active_kcal": float, "workouts": str},
}


class RecognitionError(Exception):
    pass


def extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise RecognitionError("ответ не содержит JSON")
    try:
        data = json.loads(match[0])
    except json.JSONDecodeError as error:
        raise RecognitionError("ответ содержит неверный JSON") from error
    if not isinstance(data, dict):
        raise RecognitionError("ответ имеет неверный формат")
    return data


def normalize(data: dict) -> dict:
    """Оставляет известные поля и проверяет значения: ответу модели нельзя доверять слепо."""
    kind = data.get("type")
    if kind not in FIELDS:
        return {"type": "other"}
    result: dict = {"type": kind}
    for field, field_type in FIELDS[kind].items():
        value = data.get(field)
        if field_type is float:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                value = None
        elif not isinstance(value, str) or not value.strip():
            value = None
        result[field] = value

    if kind == "food" and result["kcal"] is None:
        return {"type": "other"}
    if kind == "scale" and not (result["weight_kg"] and 20 <= result["weight_kg"] <= 400):
        return {"type": "other"}
    if kind == "watch" and not any(result[f] is not None for f in FIELDS["watch"]):
        return {"type": "other"}
    return result


async def recognize(image: bytes, mime_type: str = "image/jpeg") -> dict:
    if not GEMINI_API_KEY:
        raise RecognitionError("не задан GEMINI_API_KEY")
    body = {
        "contents": [{"parts": [
            {"text": PROMPT},
            {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(image).decode()}},
        ]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    # Ключ передаётся в заголовке, а не в адресе: адреса попадают в логи.
    headers = {"x-goog-api-key": GEMINI_API_KEY}
    timeout = aiohttp.ClientTimeout(total=60)
    url = API_URL.format(model=GEMINI_MODEL)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=body, headers=headers, proxy=GEMINI_PROXY, ssl=SSL_CONTEXT) as response:
                if response.status != 200:
                    raise RecognitionError(f"Gemini вернул код {response.status}")
                payload = await response.json()
    except (aiohttp.ClientError, TimeoutError) as error:
        raise RecognitionError(f"нет связи с Gemini ({type(error).__name__})") from error

    try:
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as error:
        raise RecognitionError("Gemini не вернул результат") from error
    return normalize(extract_json(text))
