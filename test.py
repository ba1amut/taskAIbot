import gspread
from oauth2client.service_account import ServiceAccountCredentials

# 1. Настройка доступа
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
client = gspread.authorize(creds)

# 2. Открытие таблицы
# Вставьте сюда ваш ID таблицы из адресной строки
SPREADSHEET_ID = '1TQrJ-Nu5vuSBXAsBXe3WrJrXMs6pMQRbUTlUkiOigTU' 
sheet = client.open_by_key(SPREADSHEET_ID).sheet1

# 3. Тестовая запись
print("Попытка записи в таблицу...")
# Записываем во вторую строку (первая занята заголовками)
# Формат: (Дата, Задача, Исполнитель, Дедлайн, Контроли, Статус, Ожид. статус)
row = ["01.01.2024", "Тестовая задача из Python", "Я", "02.01.2024", "Нет", "Новая", "Сделано"]
sheet.insert_row(row, 2)

print("Готово! Проверьте Google Таблицу.")