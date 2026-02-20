import asyncio
import aiohttp
from bs4 import BeautifulSoup
import json
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ContentType

try:
    import drombot_config
except ImportError:
    print("ОШИБКА: Файл config.py не найден! Скопируйте config_sample.py в config.py и заполните данные.")
    exit()

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = drombot_config.BOT_TOKEN
USER_ID = drombot_config.USER_ID
SEARCH_CODES = drombot_config.SEARCH_CODES
CHECK_INTERVAL = drombot_config.CHECK_INTERVAL

# Имя файла для сохранения "уже виденных" объявлений
CACHE_FILE = "seen_ads.json"

# Заголовки, чтобы сайт думал, что мы обычный браузер
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
}

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ФУНКЦИИ РАБОТЫ С КЭШЕМ ---
def load_seen_ads():
    if not os.path.exists(CACHE_FILE):
        return set()
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return set(json.load(f))
    except:
        return set()

def save_seen_ads(seen_set):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(seen_set), f)

# --- ПАРСИНГ DROM.RU ---
async def fetch_drom_ads(session, code):
    url = f"https://baza.drom.ru/leningradskaya-obl/sell_spare_parts/?query={code}"
    new_ads = []
    
    try:
        async with session.get(url, headers=HEADERS, timeout=20) as response:
            print(f"  [DEBUG] Код ответа сервера: {response.status}")

            if response.status != 200:
                print(f"Ошибка доступа: статус {response.status}")
                return []
            
            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            
            # --- ИЗМЕНЕНИЕ ЛОГИКИ ---
            # 1. Сначала ищем все якоря (ID объявлений). Они уникальны и точно разделяют объявления.
            id_tags = soup.find_all('a', attrs={'name': True})
            
            print(f"  [DEBUG] Найдено якорей (ID): {len(id_tags)}")

            for id_tag in id_tags:
                try:
                    # Получаем ID
                    ad_id = id_tag.get('name')
                    
                    # 2. Находим родительский блок, который содержит и ID, и данные
                    # Поднимаемся на несколько уровней вверх, чтобы захватить весь блок объявления
                    # Обычно это 2-3 уровня вверх от якоря
                    container = id_tag.find_parent('div', class_='bull-item-content')
                    
                    # Если стандартный класс не найден, берем просто "дедушку" якоря (универсальный fallback)
                    if not container:
                        container = id_tag.find_parent().find_parent()

                    # 3. Ищем ссылку строго ВНУТРИ этого контейнера
                    link_tag = container.find('a', class_='bull-item__self-link')
                    
                    # Если ссылки нет (например, это рекламный блок без name, но с name), пропускаем
                    # Но обычно name только у объявлений. Проверка на всякий случай:
                    if not link_tag:
                        # Иногда ссылка может быть до якоря, проверим ближайших соседей
                        link_tag = container.find('a', class_='bulletinLink')

                    if not link_tag:
                        continue

                    href = link_tag.get('href')
                    if href.startswith('/'):
                        link = f"https://baza.drom.ru{href}"
                    else:
                        link = href
                    title = link_tag.text.strip()

                    # 4. Ищем цену строго ВНУТРИ этого же контейнера
                    price_tag = container.find('div', class_='price-block__price')
                    
                    if price_tag:
                        price = price_tag.get_text(strip=True).replace('\xa0', ' ')
                    else:
                        # Если цены нет в этом блоке, ставим заглушку, НЕ берем из предыдущего!
                        price = "Цена не указана"
                    
#                    print(f"  [DEBUG] -> Собрано: ID={ad_id} | Цена={price}")

                    ad_data = {
                        'id': ad_id,
                        'title': title,
                        'price': price,
                        'link': link,
                        'code': code
                    }
                    new_ads.append(ad_data)

                except Exception as e:
                    print(f"  [DEBUG] Ошибка при разборе элемента: {e}")
                    continue

    except Exception as e:
        print(f"Ошибка запроса: {e}")
        
    return new_ads

# --- ФОНОВАЯ ЗАДАЧА МОНИТОРИНГА ---
async def monitoring_task():
    seen_ads = load_seen_ads()
    
    async with aiohttp.ClientSession() as session:
        while True:
            print(f"--- Запуск проверки списка кодов ---")
            
            for code in SEARCH_CODES:
                print(f" -> Проверяем код: {code}")
                
                # Запускаем парсинг
                ads = await fetch_drom_ads(session, code)
                
                # --- ДИАГНОСТИКА: Сколько нашли? ---
                print(f"    [ИТОГ] Для кода '{code}' найдено объявлений: {len(ads)}")
                
                # Обработка найденных объявлений
                new_ads_count = 0
                for ad in ads:
                    if ad['id'] not in seen_ads:
                        print(f"    >>> НОВОЕ! ID={ad['id']} (отправка в Telegram)")
                        
                        message = (
                            f"🆕 *Новое объявление по коду `{code}`!*\n\n"
                            f"📦 *Заголовок:* {ad['title']}\n"
                            f"💰 *Цена:* {ad['price']}\n"
                            f"🔗 [Ссылка на объявление]({ad['link']})"
                        )
                        
                        try:
                            await bot.send_message(
                                USER_ID, 
                                message, 
                                parse_mode="Markdown",
                                disable_web_page_preview=False
                            )
                            seen_ads.add(ad['id'])
                            save_seen_ads(seen_ads)
                            new_ads_count += 1
                            await asyncio.sleep(1) 
                            
                        except Exception as e:
                            print(f"    !!! Ошибка отправки: {e}")
                    else:
                        # Если хотите видеть, что бот пропускает старые объявления, раскомментируйте строку ниже:
                        # print(f"    (пропуск старого ID: {ad['id']})")
                        pass
                
                if new_ads_count == 0 and len(ads) > 0:
                    print(f"    Все найденные объявления для '{code}' уже были в базе.")
                elif new_ads_count == 0 and len(ads) == 0:
                    print(f"    Нет объявлений или ошибка парсинга для '{code}'.")

            print(f"--- Проверка завершена. Ждем {CHECK_INTERVAL} секунд... ---")
            await asyncio.sleep(CHECK_INTERVAL)

# --- КОМАНДЫ БОТА ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.from_user.id == USER_ID:
        await message.answer("Бот мониторинга Drom.ru запущен! Я буду проверять запчасти каждые 10 минут.")
    else:
        await message.answer("Нет доступа.")

# --- ЗАПУСК ---
async def main():
    # Запускаем мониторинг параллельно с ботом
    asyncio.create_task(monitoring_task())
    
    # Запускаем поллинг бота
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")