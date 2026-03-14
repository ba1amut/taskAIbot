import asyncio
import aiohttp
from bs4 import BeautifulSoup
import json
import os
import logging  # Добавлено для логов
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
# Пишем логи и в файл, и в консоль (чтобы видеть их через journalctl)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('drom_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

try:
    import drombot_config
except ImportError:
    logger.critical("ОШИБКА: Файл drombot_config.py не найден!")
    logger.critical("Создайте файл drombot_config.py рядом с ботом и пропишите в нем BOT_TOKEN, USER_ID, SEARCH_CODES.")
    exit(1)

# --- КОНФИГУРАЦИЯ ---
try:
    BOT_TOKEN = drombot_config.BOT_TOKEN
    USER_ID = drombot_config.USER_ID
    SEARCH_CODES = drombot_config.SEARCH_CODES
    CHECK_INTERVAL = drombot_config.CHECK_INTERVAL
    logger.info(f"Конфиг загружен. Ищем коды: {SEARCH_CODES}")
except AttributeError as e:
    logger.critical(f"Ошибка в конфигурации! Проверьте переменные в drombot_config.py: {e}")
    exit(1)

CACHE_FILE = "seen_ads.json"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ФУНКЦИИ РАБОТЫ С КЭШЕМ ---
def load_seen_ads():
    if not os.path.exists(CACHE_FILE):
        return set()
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return set(json.load(f))
    except Exception as e:
        logger.error(f"Ошибка чтения кэша: {e}")
        return set()

def save_seen_ads(seen_set):
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(seen_set), f)
    except Exception as e:
        logger.error(f"Ошибка сохранения кэша: {e}")

# --- ПАРСИНГ DROM.RU ---
async def fetch_drom_ads(session, code):
    url = f"https://baza.drom.ru/leningradskaya-obl/sell_spare_parts/?query={code}"
    new_ads = []
    
    try:
        async with session.get(url, headers=HEADERS, timeout=20) as response:
            logger.info(f"Запрос к Drom: {url} | Статус: {response.status}")

            if response.status != 200:
                logger.error(f"Сайт вернул ошибку: {response.status}")
                return []
            
            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            
            id_tags = soup.find_all('a', attrs={'name': True})
            logger.info(f"Найдено потенциальных блоков (якорей): {len(id_tags)}")

            for id_tag in id_tags:
                try:
                    ad_id = id_tag.get('name')
                    
                    # Поиск родительского контейнера
                    container = id_tag.find_parent('div', class_='bull-item-content')
                    if not container:
                        container = id_tag.find_parent().find_parent()

                    # Поиск ссылки
                    link_tag = container.find('a', class_='bull-item__self-link')
                    if not link_tag:
                        link_tag = container.find('a', class_='bulletinLink')
                    
                    if not link_tag:
                        continue

                    href = link_tag.get('href')
                    link = f"https://baza.drom.ru{href}" if href.startswith('/') else href
                    title = link_tag.text.strip()

                    # Поиск цены
                    price_tag = container.find('div', class_='price-block__price')
                    price = price_tag.get_text(strip=True).replace('\xa0', ' ') if price_tag else "Цена не указана"

                    ad_data = {
                        'id': ad_id,
                        'title': title,
                        'price': price,
                        'link': link,
                        'code': code
                    }
                    new_ads.append(ad_data)

                except Exception as e:
                    logger.warning(f"Ошибка при разборе элемента: {e}")
                    continue

    except asyncio.TimeoutError:
        logger.error("Тайм-аут при подключении к сайту")
    except Exception as e:
        logger.error(f"Ошибка запроса: {e}")
        
    return new_ads

# --- ФОНОВАЯ ЗАДАЧА МОНИТОРИНГА ---
async def monitoring_task():
    logger.info("Фоновая задача мониторинга запущена")
    # Отправляем тестовое сообщение при старте
    try:
        await bot.send_message(USER_ID, "🚀 Бот Drom.ru запущен и начал мониторинг.")
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение при старте: {e}")

    seen_ads = load_seen_ads()
    
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                logger.info(f"--- Начало цикла проверки ---")
                
                for code in SEARCH_CODES:
                    logger.info(f"Проверка кода: {code}")
                    ads = await fetch_drom_ads(session, code)
                    
                    logger.info(f"Обработано объявлений: {len(ads)}")
                    
                    new_ads_count = 0
                    for ad in ads:
                        if ad['id'] not in seen_ads:
                            logger.info(f"НОВОЕ! ID={ad['id']}")
                            
                            message = (
                                f"🆕 *Новое объявление по коду `{code}`!*\n\n"
                                f"📦 *Заголовок:* {ad['title']}\n"
                                f"💰 *Цена:* {ad['price']}\n"
                                f"🔗 [Ссылка на объявление]({ad['link']})"
                            )
                            
                            try:
                                await bot.send_message(USER_ID, message, parse_mode="Markdown")
                                seen_ads.add(ad['id'])
                                save_seen_ads(seen_ads)
                                new_ads_count += 1
                                await asyncio.sleep(1) 
                            except Exception as e:
                                logger.error(f"Ошибка отправки в Telegram: {e}")
                    
                    if new_ads_count == 0:
                        logger.info("Новых объявлений не найдено.")

                logger.info(f"--- Цикл завершен. Ожидание {CHECK_INTERVAL} сек. ---")
                await asyncio.sleep(CHECK_INTERVAL)

            except Exception as e:
                logger.critical(f"Ошибка в главном цикле: {e}")
                await asyncio.sleep(60)

# --- КОМАНДЫ БОТА ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.from_user.id == USER_ID:
        await message.answer("Бот мониторинга Drom.ru запущен!")
    else:
        await message.answer("Нет доступа.")

# --- ЗАПУСК ---
async def main():
    logger.info("Запуск бота...")
    asyncio.create_task(monitoring_task())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен.")