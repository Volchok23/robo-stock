
import telebot
import requests
from bs4 import BeautifulSoup
import time
import threading
import logging
import logging.handlers
import sqlite3
import html
import schedule
import pytz
from telebot import types
import json
import re
import os

# Настройки логирования
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "bot.log")
LOG_LEVEL = logging.INFO
LOG_MAX_BYTES = 1024 * 1024  # 1MB
LOG_BACKUP_COUNT = 5

# Создаем logger
logger = logging.getLogger(__name__)
logger.setLevel(LOG_LEVEL)

# Создаем RotatingFileHandler
handler = logging.handlers.RotatingFileHandler(
    LOG_FILE,
    maxBytes=LOG_MAX_BYTES,
    backupCount=LOG_BACKUP_COUNT,
    encoding='utf-8'  # Важно указать кодировку
)

# Форматтер
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

# Добавляем handler к logger
logger.addHandler(handler)

# Замените 'YOUR_BOT_TOKEN' на токен вашего бота
BOT_TOKEN = "8006907240:AAFRU7SK1fED5XZw9XgKXBC6t8G0JAGhfd0"
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
SITE_URL = "https://fruityblox.com/stock"
KEYWORDS = ["Dragon", "Kitsune"]
LAST_ITEMS_FILE = os.path.join(BASE_DIR, "last_items.txt") #Абсолютный путь
DATABASE_FILE = os.path.join(BASE_DIR, "bot_database.db") #Абсолютный путь
CHECK_INTERVAL = 300
LAST_ITEMS = []

def fetch_items():
    try:
        response = requests.get(SITE_URL, timeout=10)  # Добавлен таймаут
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        normal_stock_section = soup.find("h2", string="NORMAL STOCK")
        if not normal_stock_section:
            logger.warning("Секция 'NORMAL STOCK' не найдена на сайте.")
            return []

        normal_stock_container = normal_stock_section.find_parent("div")
        if not normal_stock_container:
            logger.warning("Не найден контейнер для Normal Stock")
            return []

        item_elements = normal_stock_container.find_all("a")

        items = []
        for item_element in item_elements:
            try:
                item_div = item_element.find("div", class_="relative flex flex-row gap-4 p-3 items-center justify-between hover:cursor-pointer animate-cardFade")
                if item_div:
                    title = item_div.find("h3", class_="text-xl font-bold").get_text(strip=True)
                    price = item_div.find("p", class_="text-lg text-[#21C55D] font-bold").get_text(strip=True)
                    items.append({"title": title, "price": price})
            except AttributeError as e:
                logger.error(f"Не удалось спарсить название или цену товара: {e}")
                continue

        logger.info(f"fetch_items(): Получено {len(items)} элементов с сайта.")  # Добавлено логирование
        return items
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при запросе сайта: {e}")
        return []
    except Exception as e:
        logger.exception(f"Непредвиденная ошибка в fetch_items: {e}") #Логирование всех исключений
        return []

def load_last_items():
    try:
        if not os.path.exists(LAST_ITEMS_FILE):
            logger.info(f"load_last_items(): Файл {LAST_ITEMS_FILE} не найден.")
            return []

        with open(LAST_ITEMS_FILE, "r", encoding="utf-8") as f:
            items = []
            for line in f:
                line = line.strip()  # Удаляем пробелы в начале и конце строки
                if not line:  # Пропускаем пустые строки
                    continue

                # Используем регулярное выражение для удаления всех символов, кроме букв, цифр, пробелов и ":"
                cleaned_line = re.sub(r'[^\w\s:]', '', line)
                try:
                    title, price = cleaned_line.split(":")
                    items.append({"title": title, "price": price})
                except ValueError as e:
                    logger.warning(f"Не удалось распарсить строку из файла: {line}. Очищенная строка: {cleaned_line}. Ошибка: {e}")
                    continue
            logger.info(f"load_last_items(): Загружено {len(items)} элементов из файла.")
            return items
    except FileNotFoundError:
        logger.info("load_last_items(): Файл не найден.")
        return []
    except Exception as e:
        logger.error(f"Ошибка при загрузке LAST_ITEMS: {e}")
        return []

def save_last_items(items):
    try:
        with open(LAST_ITEMS_FILE, "w", encoding="utf-8") as f:
            for item in items:
                f.write(f"{item['title']}:{item['price']}\n")
        logger.info(f"save_last_items(): Сохранено {len(items)} элементов в файл.")  # Добавлено логирование
    except Exception as e:
        logger.error(f"Ошибка при сохранении LAST_ITEMS: {e}")

def send_item_message(chat_id, item):
    try:
        title = item['title']
        price = item['price']
        message_text = f"<b>✨ {html.escape(title)} ✨</b>\n"
        message_text += f"<b>Цена: {html.escape(price)}</b>"
        if any(keyword in title for keyword in KEYWORDS):
            bot.send_message(chat_id, " ❗", message_text + " ❗", parse_mode="HTML")
        else:
            bot.send_message(chat_id, message_text, parse_mode="HTML")
    except Exception as e:
        logger.exception(f"Ошибка при отправке сообщения: {e}") # Логирование ошибок

# Вспомогательная функция для преобразования списка словарей в множество кортежей (для сравнения)
def items_to_set(items):
    return {tuple(item.items()) for item in items}

def check_new_items():
    global LAST_ITEMS
    try:
        items = fetch_items()
        if not items:
            logger.warning("Не удалось получить данные о товарах при автоматической проверке.")
            return None

        # Преобразуем списки в множества кортежей для сравнения
        current_items_set = items_to_set(items)
        last_items_set = items_to_set(LAST_ITEMS)

        # Определяем новые элементы
        new_items = [item for item in items if tuple(item.items()) not in last_items_set]

        if new_items:
            LAST_ITEMS = items
            save_last_items(items)
            logger.info("Список предметов обновлен и отправлен (автоматически).")
            return new_items
        else:
            logger.info("Изменений в списке предметов не найдено (автоматически).")
            return None
    except Exception as e:
        logger.exception(f"Ошибка в check_new_items: {e}")
        return None

def create_connection():
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        return conn
    except sqlite3.Error as e:
        logger.error(f"Ошибка при подключении к базе данных: {e}")
        return None

def create_table():
    conn = create_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_ids (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT UNIQUE NOT NULL
                )
            """)
            conn.commit()
            logger.info("Таблица chat_ids успешно создана (или уже существовала).")
        except sqlite3.Error as e:
            logger.error(f"Ошибка при создании таблицы: {e}")
        finally:
            conn.close()
    else:
        logger.error("Не удалось создать подключение к базе данных.")

def load_chat_ids():
    conn = create_connection()
    chat_ids = []
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT chat_id FROM chat_ids")
            rows = cursor.fetchall()
            chat_ids = [row[0] for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Ошибка при загрузке chat_id: {e}")
        finally:
            conn.close()
    return chat_ids

def save_chat_id(chat_id):
    conn = create_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO chat_ids (chat_id) VALUES (?)", (chat_id,))
            conn.commit()
            logger.info(f"Добавлен новый chat_id: {chat_id}")
        except sqlite3.Error as e:
            logger.error(f"Ошибка при записи chat_id в базу данных: {e}")
        finally:
            conn.close()

def clear_item_lists():
    global LAST_ITEMS
    LAST_ITEMS = []
    try:
        with open(LAST_ITEMS_FILE, "w", encoding="utf-8") as f:
            f.write("")
        logger.info("Список последних предметов очищен.")
    except Exception as e:
        logger.error(f"Ошибка при очистке списка последних предметов: {e}")

@bot.message_handler(commands=['start'])
def start(message):
    try:
        markup = types.InlineKeyboardMarkup()
        button1 = types.InlineKeyboardButton("Обновить список товаров", callback_data="update_items")
        markup.add(button1)
        bot.send_message(message.chat.id, "Привет! Я буду присылать тебе новые названия предметов из Normal Stock с сайта fruityblox.com.\nНажми кнопку, чтобы обновить список товаров, или я буду проверять автоматически каждые 5 минут.", reply_markup=markup)
        save_chat_id(str(message.chat.id))
    except Exception as e:
        logger.exception(f"Ошибка в обработчике /start: {e}") #Логирование исключений

@bot.callback_query_handler(func=lambda call: call.data == "update_items")
def callback_query(call):
    try:
        bot.answer_callback_query(call.id, "Обновляю список товаров...")
        global LAST_ITEMS
        items = fetch_items()

        if not items:
            bot.send_message(call.message.chat.id, "Не удалось получить данные о товарах.", parse_mode="HTML")
            return

        logger.info(f"callback_query(): Получено {len(items)} элементов с сайта.")  # Логируем количество полученных элементов

        if not LAST_ITEMS:
            LAST_ITEMS = items
            save_last_items(items)
            message_text = "Первоначальный список товаров:\n"
            for item in items:
                message_text += f"<b>✨ {html.escape(item['title'])} ✨</b> - <b>Цена: {html.escape(item['price'])}</b>\n"
            bot.send_message(call.message.chat.id, message_text, parse_mode="HTML")
            logger.info("callback_query(): Отправлен первоначальный список.")  # Логируем отправку первоначального списка
        else:
            # Преобразуем списки в множества кортежей для сравнения
            current_items_set = items_to_set(items)
            last_items_set = items_to_set(LAST_ITEMS)

            # Определяем новые элементы
            new_items = [item for item in items if tuple(item.items()) not in last_items_set]

            if new_items:
                LAST_ITEMS = items
                save_last_items(items)
                message_text = "Обновлен список товаров, появились новые предметы:\n"
                for item in new_items:
                    message_text += f"<b>✨ {html.escape(item['title'])} ✨</b> - <b>Цена: {html.escape(item['price'])}</b>\n"
                bot.send_message(call.message.chat.id, message_text, parse_mode="HTML")
                for item in new_items:
                    send_item_message(call.message.chat.id, item)
                logger.info("callback_query(): Отправлен список новых предметов.")  # Логируем отправку новых элементов
            else:
                message_text = "Предметы не изменились. Текущие предметы:\n"
                for item in LAST_ITEMS:
                    message_text += f"<b>✨ {html.escape(item['title'])} ✨</b> - <b>Цена: {html.escape(item['price'])}</b>\n"
                bot.send_message(call.message.chat.id, message_text, parse_mode="HTML")
                logger.info("callback_query(): Отправлен список текущих предметов (изменений нет).")  # Логируем отправку текущих элементов
    except Exception as e:
        logger.exception(f"Ошибка в обработчике callback_query: {e}")

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    try:
        save_chat_id(str(message.chat.id))
    except Exception as e:
        logger.exception(f"Ошибка в обработчике echo_all: {e}")

def periodic_check():
    global LAST_ITEMS
    while True:
        try:
            chat_ids = load_chat_ids()
            items = fetch_items()

            if not items:
                logger.warning("Не удалось получить данные о товарах при автоматической проверке.")
                time.sleep(CHECK_INTERVAL)
                continue

            # Преобразуем списки в множества кортежей для сравнения
            current_items_set = items_to_set(items)
            last_items_set = items_to_set(LAST_ITEMS)

            # Определяем новые элементы
            new_items = [item for item in items if tuple(item.items()) not in last_items_set]

            if new_items:
                LAST_ITEMS = items
                save_last_items(items)
                for chat_id in chat_ids:
                    for item in new_items:
                        send_item_message(chat_id, item)
        except Exception as e:
            logger.exception(f"Ошибка в periodic_check: {e}")
        finally:
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    print("Бот запущен...")

    create_table()

    # Инициализация LAST_ITEMS при запуске
    LAST_ITEMS = load_last_items()

    check_thread = threading.Thread(target=periodic_check)
    check_thread.daemon = True
    check_thread.start()

    # Schedule Clearing
    timezone = pytz.timezone('Europe/Moscow')
    def schedule_clear():
        clear_item_lists()
        logger.info("Список очищен по расписанию (00:00 МСК)")

    # Убедитесь, что функция schedule_clear вызывается с правильным аргументом timezone
    schedule.every().day.at("00:00").do(schedule_clear).timezone = timezone

    def run_scheduler():
        while True:
            schedule.run_pending()
            time.sleep(1)

    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()

    bot.infinity_polling()
