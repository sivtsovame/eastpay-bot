import logging
import gspread
from google.oauth2.service_account import Credentials
from config import GOOGLE_SHEET_ID, GOOGLE_CREDS_FILE
import os

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_client: gspread.Client | None = None


def _get_client() -> gspread.Client:
    global _client
    if _client is None:
        if not os.path.exists(GOOGLE_CREDS_FILE):
            raise FileNotFoundError(
                f"Файл {GOOGLE_CREDS_FILE} не найден. "
                "Создай сервисный аккаунт Google и положи JSON рядом с ботом."
            )
        creds = Credentials.from_service_account_file(GOOGLE_CREDS_FILE, scopes=SCOPES)
        _client = gspread.authorize(creds)
    return _client


async def append_deal_to_sheet(deal: dict):
    """Добавляет строку сделки в Google Таблицу."""
    if not GOOGLE_SHEET_ID:
        logger.warning("GOOGLE_SHEET_ID не задан — пропускаю запись в таблицу")
        return
    try:
        client = _get_client()
        sh = client.open_by_key(GOOGLE_SHEET_ID)
        ws = sh.sheet1

        # Если таблица пустая — добавим заголовки
        if ws.row_count < 1 or not ws.row_values(1):
            ws.append_row([
                "№", "Дата", "Менеджер",
                "Валюта", "Тип", "Город",
                "Сумма валюты", "Сумма RUB", "Курс", "Статус"
            ])

        from datetime import datetime
        ws.append_row([
            deal["id"],
            datetime.now().strftime("%d.%m.%Y %H:%M"),
            deal.get("manager_name", "—"),
            deal["currency"],
            "Безнал" if deal["currency_type"] == "transfer" else "Нал",
            deal["city"],
            deal["amount_foreign"],
            deal["amount_rub"],
            deal["rate_used"],
            deal.get("status", "pending"),
        ])
        logger.info(f"Сделка #{deal['id']} записана в Google Sheets")
    except Exception as e:
        logger.error(f"Ошибка записи в Google Sheets: {e}")
