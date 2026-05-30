# EAST PAY Bot — инструкция запуска

## 1. Создать бота в Telegram

1. Открой Telegram, найди @BotFather
2. Отправь `/newbot`
3. Придумай имя (например: `East Pay Manager Bot`)
4. Придумай username (например: `eastpay_manager_bot`)
5. Скопируй токен вида `7123456789:AAF...`

## 2. Включить инлайн-режим

В @BotFather:
```
/setinline → выбери своего бота → введи любой placeholder, например: "введите формулу"
```

## 3. Установка на Mac

```bash
# Открой Терминал и выполни по очереди:

cd ~/Desktop          # или куда хочешь положить бота
git clone . eastpay-bot   # или просто скопируй папку
cd eastpay-bot

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

## 4. Настройка

Открой `config.py` и вставь токен:
```python
BOT_TOKEN = "7123456789:AAF..."   # ← твой токен
```

Или через переменную окружения (рекомендуется):
```bash
export BOT_TOKEN="7123456789:AAF..."
```

## 5. Добавить себя как администратора

В `config.py`:
```python
ADMIN_IDS = [123456789]   # твой Telegram user_id
```

Свой ID можно узнать написав @userinfobot в Telegram.

## 6. Запуск

```bash
source venv/bin/activate   # если терминал новый
python3 bot.py
```

Должно появиться:
```
INFO: База данных инициализирована
INFO: Бот запущен. Нажми Ctrl+C для остановки.
```

## 7. Проверка

- Найди своего бота в Telegram по username
- Напиши /start
- В любом чате напиши @твой_бот_username garus

## 8. Google Sheets (опционально)

Можно настроить позже. Сделки будут сохраняться в БД даже без Google Sheets.

Если нужно:
1. Зайди на console.cloud.google.com
2. Создай проект → включи Google Sheets API
3. Создай Service Account → скачай JSON
4. Переименуй в `google_creds.json` и положи рядом с bot.py
5. Вставь ID таблицы в config.py

## Структура команд

| Команда | Описание |
|---------|----------|
| @bot формула | Инлайн-калькулятор |
| @bot garus | Текущий курс Garantex |
| @bot garus+1%+0.5% | Курс с процентами |
| /b | Все балансы |
| /b usd 100 | Добавить к балансу |
| /b usd -100*7 | Вычесть 700 |
| /b stat usd | История по валюте |
| /deal | Создать сделку |
| /deals | Реестр сделок |
| /rates | Курсы валют |
| /setrate JPY transfer 155.21 | Установить курс (админ) |
| /formula buy garus-1.5% | Создать личную формулу |
| /track АДРЕС | Мониторинг BTC |
| /address | Список кошельков |
