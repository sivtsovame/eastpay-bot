import os

# Загружаем переменные окружения из .env, если файл существует.
# Это позволяет запускать бота без ручного экспорта переменных.
ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

# ── Вставь свой токен от BotFather ──────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# ── Google Sheets (заполни после настройки Google API) ───────────────────────
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")          # ID таблицы из URL
GOOGLE_CREDS_FILE = "google_creds.json"                      # Файл с ключами сервисного аккаунта

# ── Garantex ─────────────────────────────────────────────────────────────────
GARANTEX_URL = "https://garantex.cc/api/v2/depth?market=usdtrub"

# ── Города и их ставки (%) ───────────────────────────────────────────────────
CITY_RATES = {
    "москва":      0.3,
    "владивосток": 0.5,
    "уфа":         1.2,
    # Добавляй новые города сюда
}

# ── Прибыль компании со сделки (%) ───────────────────────────────────────────
COMPANY_PROFIT = 1.0

# ── Администраторы бота (могут вносить курсы валют) ──────────────────────────
# Добавь Telegram user_id администраторов
ADMIN_IDS = [640353809]
