import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date
import re
import os 

# --- КОНФИГУРАЦИЯ ---


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

bot = telebot.TeleBot(BOT_TOKEN)

# Подключение к Google Sheets
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
try:
    # Проверяем, существует ли файл
    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(f"Файл {CREDENTIALS_FILE} не найден!")

    # ИЗМЕНЕНИЕ ЗДЕСЬ: используем from_json_keyfile_name вместо from_json_keyfile_dict
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    print("Успешное подключение к Google Sheets")
except Exception as e:
    print(f"Критическая ошибка подключения к Google Sheets: {e}")
    # Можно выйти, если подключение не удалось
    exit()

# --- КЛАВИАТУРЫ ---

# Создаем главное меню
main_menu_markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
btn_all = telebot.types.KeyboardButton('📋 Все задачи')
btn_open = telebot.types.KeyboardButton('🔴 Открытые задачи')
main_menu_markup.add(btn_all, btn_open)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_next_number():
    col_values = sheet.col_values(1)
    if len(col_values) <= 1:
        return 1
    return len(col_values)

def parse_date_safe(date_str):
    """Попытка преобразовать строку даты в объект date."""
    if not date_str: return None
    # Пробуем разные форматы
    for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d.%m.%y'):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            pass
    return None

def get_status_icon(status, deadline_str):
    """Определяет эмодзи для статуса."""
    if status == "Закрыто":
        return "🟢" # Зеленый для закрытых
    
    if status == "Открыто":
        dl_date = parse_date_safe(deadline_str)
        today = date.today()
        
        if dl_date:
            if dl_date < today:
                return "🔴" # Красный (просрочено)
            else:
                return "🟡" # Желтый (в срок)
    
    return "⚪️" # Если не понятно

# --- ОБРАБОТЧИКИ ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    text = (
        "Привет! Я бот для учета задач.\n\n"
        "Используйте кнопки меню для просмотра отчетов.\n\n"
        "<b>Как добавить задачу:</b>\n"
        "Напишите: <code>Наименование, Срок</code>\n"
        "Пример: <code>Сделать отчет, 25.10.2023</code>\n\n"
        "<b>Как закрыть задачу:</b>\n"
        "Напишите: <code>5 закрыть</code>"
    )
    bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=main_menu_markup)

# Обработчик текстовых сообщений (кнопки и команды создания/закрытия)
@bot.message_handler(content_types=['text'])
def handle_text(message):
    text = message.text.strip()
    
    # 1. Обработка кнопок меню
    if text == '📋 Все задачи':
        show_all_tasks(message)
        return
    elif text == '🔴 Открытые задачи':
        show_open_tasks(message)
        return
        
    # 2. Обработка команды закрытия
    match_close = re.match(r'^(\d+)\s+закрыть$', text, re.IGNORECASE)
    if match_close:
        task_id = int(match_close.group(1))
        close_task(message, task_id)
        return

    # 3. Обработка создания задачи
    if ',' in text:
        parts = text.split(',', 1)
        name = parts[0].strip()
        deadline = parts[1].strip()
        
        if name and deadline:
            create_task(message, name, deadline)
            return

    bot.send_message(message.chat.id, "Не понял команду. Формат:\n<code>Задача, Срок</code>\nили <code>Номер закрыть</code>", parse_mode='HTML')

# --- ФУНКЦИИ ОТЧЕТОВ ---

def show_all_tasks(message):
    try:
        records = sheet.get_all_records()
        if not records:
            bot.send_message(message.chat.id, "Задач пока нет.")
            return

        response = "<b>📋 Все задачи:</b>\n\n"
        for row in records:
            # Определяем иконку
            icon = get_status_icon(row.get('Статус'), row.get('Плановый срок'))
            
            response += (
                f"{icon} <b>{row.get('№', '?')}: {row.get('Наименование', '?')}</b>\n"
                f"Статус: {row.get('Статус', '?')} | Срок: {row.get('Плановый срок', '?')}\n"
                f"───────────────\n"
            )
            if len(response) > 3900:
                response += "... (превышен лимит символов)"
                break
        
        bot.send_message(message.chat.id, response, parse_mode='HTML')
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка при чтении таблицы: {e}")

def show_open_tasks(message):
    try:
        records = sheet.get_all_records()
        # Фильтруем только открытые
        open_tasks = [r for r in records if r.get('Статус') == 'Открыто']
        
        if not open_tasks:
            bot.send_message(message.chat.id, "Открытых задач нет! ✅")
            return

        response = "<b>🔴 Открытые задачи:</b>\n\n"
        for row in open_tasks:
            # Тоже используем иконки для наглядности просроченности
            icon = get_status_icon(row.get('Статус'), row.get('Плановый срок'))
            
            response += (
                f"{icon} <b>{row.get('№', '?')}: {row.get('Наименование', '?')}</b>\n"
                f"Срок: {row.get('Плановый срок', '?')}\n"
                f"───────────────\n"
            )
            
        bot.send_message(message.chat.id, response, parse_mode='HTML')
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка: {e}")

# --- ФУНКЦИИ ДЕЙСТВИЙ ---

def create_task(message, name, deadline):
    try:
        next_id = get_next_number()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "Открыто"
        
        row_data = [next_id, now, name, deadline, status, ""]
        sheet.append_row(row_data)
        
        bot.send_message(message.chat.id, f"✅ Задача №{next_id} добавлена.")
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка при создании: {e}")

def close_task(message, task_id):
    try:
        cell = sheet.find(str(task_id), in_column=1)
        
        if not cell:
            bot.send_message(message.chat.id, f"Задача с номером {task_id} не найдена.")
            return
        
        row_number = cell.row
        
        # Проверяем статус (колонка E - номер 5)
        current_status = sheet.cell(row_number, 5).value
        if current_status == "Закрыто":
            bot.send_message(message.chat.id, "Эта задача уже закрыта.")
            return
            
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        sheet.update_cell(row_number, 5, "Закрыто")
        sheet.update_cell(row_number, 6, now)
        
        bot.send_message(message.chat.id, f"🏁 Задача №{task_id} закрыта.")
        
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка при закрытии: {e}")

# --- ЗАПУСК ---
if __name__ == '__main__':
    print("Бот запущен...")
    bot.infinity_polling()