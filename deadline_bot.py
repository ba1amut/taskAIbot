import asyncio
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date
import logging
import re
import os

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# --- КОНФИГУРАЦИЯ И ЛОГИРОВАНИЕ ---

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('task_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# --- НАСТРОЙКИ ---
try:
    from config import TG_TOKEN_DL, SPREADSHEET_ID_DL
except ImportError:
    # Если файла нет (например, на сервере), переменные будут None, бот упадет с ошибкой
    print("Ошибка: не найден файл config.py или в нем нет переменных!")
    exit()


# 1. Вставьте сюда токен вашего Telegram бота (получить у @BotFather)
BOT_TOKEN = TG_TOKEN_DL

# 2. ID вашей Google Таблицы (берется из URL таблицы)
# Пример: https://docs.google.com/spreadsheets/d/ВОТ_ЭТОТ_ДЛИННЫЙ_ID/edit
SPREADSHEET_ID = SPREADSHEET_ID_DL

# Имя файла с ключами (он должен лежать в той же папке)
CREDENTIALS_FILE = 'credentials.json'

# --- ИНИЦИАЛИЗАЦИЯ ---


# --- ПОДКЛЮЧЕНИЕ К GOOGLE SHEETS ---

scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
try:
    if not os.path.exists(CREDENTIALS_FILE):
        logger.critical(f"Файл {CREDENTIALS_FILE} не найден!")
        exit(1)
        
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    logger.info("Успешное подключение к Google Sheets")
except Exception as e:
    logger.critical(f"Ошибка подключения к Google Sheets: {e}")
    exit(1)

# --- ИНИЦИАЛИЗАЦИЯ AIogram ---

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- КЛАВИАТУРЫ ---

# Создаем кнопки меню
kb_main = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text='📋 Все задачи'), KeyboardButton(text='🔴 Открытые задачи')]
    ],
    resize_keyboard=True
)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_next_number():
    col_values = sheet.col_values(1)
    if len(col_values) <= 1:
        return 1
    return len(col_values)

def parse_date_safe(date_str):
    if not date_str: return None
    for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d.%m.%y'):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            pass
    return None

def get_status_icon(status, deadline_str):
    if status == "Закрыто":
        return "🟢"
    if status == "Открыто":
        dl_date = parse_date_safe(deadline_str)
        today = date.today()
        if dl_date:
            if dl_date < today:
                return "🔴"
            else:
                return "🟡"
    return "⚪️"

# --- ОБРАБОТЧИКИ КОМАНД ---

@dp.message(Command("start", "help"))
async def cmd_start(message: types.Message):
    text = (
        "Привет! Я бот для учета задач.\n\n"
        "Используйте кнопки меню для просмотра отчетов.\n\n"
        "<b>Как добавить задачу:</b>\n"
        "Напишите: <code>Наименование, Срок</code>\n"
        "Пример: <code>Сделать отчет, 25.10.2023</code>\n\n"
        "<b>Как закрыть задачу:</b>\n"
        "Напишите: <code>5 закрыть</code>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb_main)

# Обработчик текстовых сообщений (кнопки и команды создания/закрытия)
@dp.message()
async def handle_text(message: types.Message):
    text = message.text.strip()
    
    # 1. Обработка кнопок меню
    if text == '📋 Все задачи':
        await show_all_tasks(message)
        return
    elif text == '🔴 Открытые задачи':
        await show_open_tasks(message)
        return
        
    # 2. Обработка команды закрытия
    match_close = re.match(r'^(\d+)\s+закрыть$', text, re.IGNORECASE)
    if match_close:
        task_id = int(match_close.group(1))
        await close_task(message, task_id)
        return

    # 3. Обработка создания задачи
    if ',' in text:
        parts = text.split(',', 1)
        name = parts[0].strip()
        deadline = parts[1].strip()
        
        if name and deadline:
            await create_task(message, name, deadline)
            return

    await message.answer("Не понял команду. Формат:\n<code>Задача, Срок</code>\nили <code>Номер закрыть</code>", parse_mode='HTML')

# --- ФУНКЦИИ ДЕЙСТВИЙ ---

async def show_all_tasks(message: types.Message):
    try:
        records = sheet.get_all_records()
        if not records:
            await message.answer("Задач пока нет.")
            return

        response = "<b>📋 Все задачи:</b>\n\n"
        for row in records:
            icon = get_status_icon(row.get('Статус'), row.get('Плановый срок'))
            response += (
                f"{icon} <b>№{row.get('№', '?')}: {row.get('Наименование', '?')}</b>\n"
                f"Статус: {row.get('Статус', '?')} | Срок: {row.get('Плановый срок', '?')}\n"
                f"───────────────\n"
            )
            if len(response) > 3900:
                response += "... (превышен лимит символов)"
                break
        
        await message.answer(response, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка при чтении таблицы: {e}")
        await message.answer(f"Ошибка при чтении таблицы: {e}")

async def show_open_tasks(message: types.Message):
    try:
        records = sheet.get_all_records()
        open_tasks = [r for r in records if r.get('Статус') == 'Открыто']
        
        if not open_tasks:
            await message.answer("Открытых задач нет! ✅")
            return

        response = "<b>🔴 Открытые задачи:</b>\n\n"
        for row in open_tasks:
            icon = get_status_icon(row.get('Статус'), row.get('Плановый срок'))
            response += (
                f"{icon} <b>№{row.get('№', '?')}: {row.get('Наименование', '?')}</b>\n"
                f"Срок: {row.get('Плановый срок', '?')}\n"
                f"───────────────\n"
            )
            
        await message.answer(response, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await message.answer(f"Ошибка: {e}")

async def create_task(message: types.Message, name: str, deadline: str):
    try:
        next_id = get_next_number()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "Открыто"
        
        row_data = [next_id, now, name, deadline, status, ""]
        sheet.append_row(row_data)
        
        await message.answer(f"✅ Задача №{next_id} добавлена.")
        logger.info(f"Добавлена задача №{next_id}")
    except Exception as e:
        logger.error(f"Ошибка при создании: {e}")
        await message.answer(f"Ошибка при создании: {e}")

async def close_task(message: types.Message, task_id: int):
    try:
        cell = sheet.find(str(task_id), in_column=1)
        
        if not cell:
            await message.answer(f"Задача с номером {task_id} не найдена.")
            return
        
        row_number = cell.row
        current_status = sheet.cell(row_number, 5).value
        
        if current_status == "Закрыто":
            await message.answer("Эта задача уже закрыта.")
            return
            
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        sheet.update_cell(row_number, 5, "Закрыто")
        sheet.update_cell(row_number, 6, now)
        
        await message.answer(f"🏁 Задача №{task_id} закрыта.")
        logger.info(f"Задача №{task_id} закрыта")
        
    except Exception as e:
        logger.error(f"Ошибка при закрытии: {e}")
        await message.answer(f"Ошибка при закрытии: {e}")

# --- ЗАПУСК ---

async def main():
    logger.info("Запуск бота задач...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен.")