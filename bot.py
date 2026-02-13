import asyncio
import gspread
import requests
import json
import io # Нужно для работы с файлами в памяти
from oauth2client.service_account import ServiceAccountCredentials
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from datetime import datetime

# --- НАСТРОЙКИ ---
try:
    from config import TG_TOKEN, SPREADSHEET_ID, YANDEX_API_KEY, YANDEX_FOLDER_ID
except ImportError:
    # Если файла нет (например, на сервере), переменные будут None, бот упадет с ошибкой
    print("Ошибка: не найден файл config.py или в нем нет переменных!")
    exit()
    
CREDENTIALS_FILE = 'credentials.json'
# --- ПОДКЛЮЧЕНИЕ К GOOGLE ---
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID).sheet1

# --- НАСТРОЙКА БОТА ---
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# Клавиатура с кнопками
keyboard = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="/start"), KeyboardButton(text="/today")],
    [KeyboardButton(text="/date")] 
], resize_keyboard=True)

# --- ФУНКЦИЯ ИИ (YandexGPT) ---
async def parse_task_with_ai(text):
    """
    Отправляет текст в YandexGPT и просит вернуть JSON с данными задачи.
    """
    current_date = datetime.now().strftime("%Y-%m-%d")
    prompt = f"""
    Ты — умный помощник по планированию. Твоя задача: извлечь из текста пользователя данные.
    
    ВАЖНО: Сегодняшняя дата: {current_date}.
    Используй эту дату для вычисления относительных сроков (завтра, в пятницу, через неделю).
    
    Текст пользователя: "{text}"
    
    Верни ответ ТОЛЬКО в формате JSON (без markdown, просто текст):
    {{
        "task": "Название задачи",
        "assignee": "Имя исполнителя (если нет, то 'Я')",
        "deadline": "Дата дедлайна в формате ГГГГ-ММ-ДД (если нет, напиши null)"
    }}
    """
    
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    headers = {
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt/latest",
        "completionOptions": {
            "stream": False,
            "temperature": 0.1,
            "maxTokens": "2000"
        },
        "messages": [
            {
                "role": "system",
                "text": "Ты json-генератор. Ты строго следуешь формату. Ты точно знаешь сегодняшнюю дату."
            },
            {
                "role": "user",
                "text": prompt
            }
        ]
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        
        ai_text = result['result']['alternatives'][0]['message']['text']
        
        # Убираем возможные артефакты форматирования
        clean_json = ai_text.replace('\n', '').replace('```json', '').replace('```', '').strip()
        task_data = json.loads(clean_json)
        return task_data
        
    except Exception as e:
        print(f"Ошибка ИИ: {e}")
        return None

# --- ФУНКЦИЯ РАСПОЗНАВАНИЯ ГОЛОСА (Yandex SpeechKit) ---
async def recognize_speech(voice_file):
    try:
        # Скачиваем файл в буфер памяти
        audio_bytes = io.BytesIO()
        file_info = await bot.get_file(voice_file.file_id)
        await bot.download_file(file_info.file_path, audio_bytes)
        
        url = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
        headers = {"Authorization": f"Api-Key {YANDEX_API_KEY}"}
        params = {
            "lang": "ru-RU",
            "folderId": YANDEX_FOLDER_ID
        }
        
        audio_bytes.seek(0)
        response = requests.post(url, headers=headers, params=params, data=audio_bytes)
        
        if response.status_code == 200:
            result = response.json()
            return result.get('result')
        else:
            print(f"Ошибка SpeechKit: {response.text}")
            return None
    except Exception as e:
        print(f"Ошибка скачивания/распознавания: {e}")
        return None

# --- ОБРАБОТЧИКИ КОМАНД ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я ваш умный помощник.\n\n"
        "📝 Напишите текст задачи или надиктуйте голосовое сообщение.\n"
        "📅 Используйте /today для просмотра задач на сегодня.\n"
        "📅 Используйте /date ДД.ММ для поиска задач по дате.",
        reply_markup=keyboard
    )

@dp.message(Command("today"))
async def cmd_today(message: types.Message):
    try:
        today_str = datetime.now().strftime("%d.%m.%Y")
        
        records = sheet.get_all_records()
        tasks_found = []
        
        for row in records:
            deadline = row.get('Дедлайн', '')
            intermediate = row.get('Промежуточные контроли', '')
            
            if today_str in deadline or today_str in intermediate:
                task_text = row.get('Задача', 'Без названия')
                assignee = row.get('Исполнитель', '')
                status = row.get('Статус', '')
                tasks_found.append(f"🔹 {task_text}\n   👤 {assignee} | 📊 {status}")
        
        if tasks_found:
            answer = f"📋 Задачи на сегодня ({today_str}):\n\n" + "\n\n".join(tasks_found)
        else:
            answer = f"🎉 На сегодня ({today_str}) задач не найдено."
            
        await message.answer(answer)
    except Exception as e:
        await message.answer(f"Ошибка при чтении таблицы: {e}")

@dp.message(Command("date"))
async def cmd_date(message: types.Message):
    args = message.text.split(maxsplit=1)
    
    if len(args) == 1:
        await message.answer("📅 Введите дату после команды.\nПример: `/date 15.05` или `/date 20.12.2024`", parse_mode="Markdown")
        return

    date_input = args[1].strip()
    
    try:
        if len(date_input) <= 5: 
            current_year = datetime.now().year
            search_date = datetime.strptime(f"{date_input}.{current_year}", "%d.%m.%Y").strftime("%d.%m.%Y")
        else:
            search_date = datetime.strptime(date_input, "%d.%m.%Y").strftime("%d.%m.%Y")
            
    except ValueError:
        await message.answer("❌ Неверный формат даты. Используйте ДД.ММ или ДД.ММ.ГГГГ")
        return

    try:
        records = sheet.get_all_records()
        tasks_found = []
        
        for row in records:
            deadline = row.get('Дедлайн', '')
            intermediate = row.get('Промежуточные контроли', '')
            
            if search_date in deadline or search_date in intermediate:
                task_text = row.get('Задача', 'Без названия')
                assignee = row.get('Исполнитель', '')
                status = row.get('Статус', '')
                tasks_found.append(f"🔹 {task_text}\n   👤 {assignee} | 📊 {status}")
        
        if tasks_found:
            answer = f"📅 Задачи на {search_date}:\n\n" + "\n\n".join(tasks_found)
        else:
            answer = f"🎉 На {search_date} задач не найдено."
            
        await message.answer(answer)
        
    except Exception as e:
        await message.answer(f"Ошибка при чтении таблицы: {e}")

# Обработка ГОЛОСОВЫХ сообщений
@dp.message(F.voice)
async def voice_handler(message: types.Message):
    status_msg = await message.answer("🎧 Обрабатываю голосовое сообщение...")
    
    text = await recognize_speech(message.voice)
    
    if not text:
        await status_msg.edit_text("❌ Не удалось распознать речь.")
        return
        
    await status_msg.edit_text(f'🎤 Распознано: "{text}". Анализирую...')
    
    parsed_data = await parse_task_with_ai(text)
    
    if parsed_data:
        task_name = parsed_data.get('task', text)
        assignee = parsed_data.get('assignee', 'Я')
        deadline_raw = parsed_data.get('deadline')
        
        deadline_final = "Не указан"
        if deadline_raw and deadline_raw != 'null':
            try:
                dt = datetime.strptime(deadline_raw, "%Y-%m-%d")
                deadline_final = dt.strftime("%d.%m.%Y")
            except:
                deadline_final = deadline_raw

        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        row = [now, task_name, assignee, deadline_final, "", "Новая", ""]
        sheet.insert_row(row, 2)
        
        response_text = (
            f"✅ Задача сохранена!\n"
            f"📝 Текст: {task_name}\n"
            f"👤 Исполнитель: {assignee}\n"
            f"📅 Срок: {deadline_final}"
        )
        await status_msg.edit_text(response_text)
    else:
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        sheet.insert_row([now, text, "Я", "Не указан", "", "Новая", ""], 2)
        await status_msg.edit_text("⚠️ Не удалось разобрать детали, но сохранил задачу как есть.")

# Обработка ТЕКСТОВЫХ сообщений
@dp.message(F.text)
async def save_task(message: types.Message):
    user_text = message.text
    
    # Проверка: если текст похож на дату (например, "15.05"), то ищем задачи
    is_date_like = False
    try:
        # Если короткий формат ДД.ММ
        if len(user_text) <= 5 and "." in user_text:
            datetime.strptime(f"{user_text}.{datetime.now().year}", "%d.%m.%Y")
            is_date_like = True
        # Если полный формат ДД.ММ.ГГГГ
        elif len(user_text) == 10 and "." in user_text:
            datetime.strptime(user_text, "%d.%m.%Y")
            is_date_like = True
    except:
        pass # Это не дата

    if is_date_like:
        # Выполняем поиск
        try:
            if len(user_text) <= 5:
                 search_date = datetime.strptime(f"{user_text}.{datetime.now().year}", "%d.%m.%Y").strftime("%d.%m.%Y")
            else:
                 search_date = datetime.strptime(user_text, "%d.%m.%Y").strftime("%d.%m.%Y")
            
            records = sheet.get_all_records()
            tasks_found = []
            for row in records:
                dl = row.get('Дедлайн', '')
                inter = row.get('Промежуточные контроли', '')
                if search_date in dl or search_date in inter:
                    tasks_found.append(f"🔹 {row.get('Задача')} | 👤 {row.get('Исполнитель')} | 📊 {row.get('Статус')}")
            
            if tasks_found:
                await message.answer(f"📅 Задачи на {search_date}:\n\n" + "\n".join(tasks_found))
            else:
                await message.answer(f"🎉 На {search_date} задач не найдено.")
            return # Не сохраняем дату как задачу
        except Exception as e:
            print(f"Ошибка поиска по дате: {e}")
            # Если ошибка, идем дальше сохранять как задачу

    # Стандартная логика сохранения задачи
    await message.answer("🧠 Анализирую задачу...")
    
    parsed_data = await parse_task_with_ai(user_text)
    
    if parsed_data:
        task_name = parsed_data.get('task', user_text)
        assignee = parsed_data.get('assignee', 'Я')
        deadline_raw = parsed_data.get('deadline')
        
        deadline_final = "Не указан"
        if deadline_raw and deadline_raw != 'null':
            try:
                dt = datetime.strptime(deadline_raw, "%Y-%m-%d")
                deadline_final = dt.strftime("%d.%m.%Y")
            except:
                deadline_final = deadline_raw

        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        row = [now, task_name, assignee, deadline_final, "", "Новая", ""]
        sheet.insert_row(row, 2)
        
        response_text = (
            f"✅ Задача сохранена!\n"
            f"📝 Текст: {task_name}\n"
            f"👤 Исполнитель: {assignee}\n"
            f"📅 Срок: {deadline_final}"
        )
        await message.answer(response_text)
    else:
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        sheet.insert_row([now, user_text, "Я", "Не указан", "", "Новая", ""], 2)
        await message.answer("⚠️ Не удалось разобрать детали, но сохранил задачу как есть.")

# --- ЗАПУСК БОТА ---
async def main():
    print("Бот запущен и готов к работе...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())