import os

# Значения задаются до импорта bot.config, поэтому тесты не читают настоящий .env.
os.environ["BOT_TOKEN"] = "123456:TEST_TOKEN_FOR_TESTS_ONLY"
os.environ["ALLOWED_USER_ID"] = "1000"
os.environ["TIMEZONE"] = "Europe/Moscow"
os.environ["GEMINI_API_KEY"] = ""
os.environ["GEMINI_PROXY"] = ""
