import os
import telebot
import requests
import io
import html
import re
import datetime
import urllib.parse
import sqlite3  # Подключаем встроенную БД
from bs4 import BeautifulSoup
from telebot import types
from google import genai

# Инициализация токенов и клиентов
TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

GEMINI_API_KEY = os.environ.get("GEMINI_KEY", "YOUR_GEMINI_API_KEY")
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# Аккаунты Rutracker
RUTRACKER_LOGIN = os.environ.get("RUTRACKER_LOGIN", "YOUR_RUTRACKER_LOGIN")
RUTRACKER_PASSWORD = os.environ.get("RUTRACKER_PASSWORD", "YOUR_RUTRACKER_PASSWORD")

# Модераторы/Администраторы бота
MODERATORS = [1662438615]  # Твой Telegram ID успешно добавлен!

# Настройки Rutracker
RUTRACKER_URL = "https://rutracker.org/forum/tracker.php"
RUTRACKER_LOGIN_URL = "https://ssl.rutracker.org/forum/login.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ==========================================
# ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ (SQLite)
# ==========================================
DB_FILE = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Таблица пользователей: лимиты, язык, статус премиума и дата окончания подписки
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            lang TEXT DEFAULT 'ru',
            max_limit INTEGER DEFAULT 3,
            used_today INTEGER DEFAULT 0,
            total_searches INTEGER DEFAULT 0,
            is_premium INTEGER DEFAULT 0,
            premium_till TEXT DEFAULT NULL  -- Может быть датой (YYYY-MM-DD) или 'forever'
        )
    ''')
    
    # Таблица рефералов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            referrer_id INTEGER,
            referred_id INTEGER,
            PRIMARY KEY (referrer_id, referred_id)
        )
    ''')
    
    # Таблица системного состояния (дата последнего сброса лимитов)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO system_state (key, value) VALUES (?, ?)", 
                   ("last_reset_date", str(datetime.date.today())))
    
    conn.commit()
    conn.close()

# Запускаем создание БД
init_db()

# ==========================================
# ФУНКЦИИ-ПОМОЩНИКИ ДЛЯ РАБОТЫ С БД
# ==========================================
def ensure_user_exists(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def get_user_field(user_id, field, default):
    ensure_user_exists(user_id)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f"SELECT {field} FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row and row[0] is not None else default

def set_user_field(user_id, field, value):
    ensure_user_exists(user_id)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()

def add_referral_to_db(referrer_id, referred_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (referrer_id, referred_id))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success

def get_referrals_count(referrer_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (referrer_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

# Оперативные хранилища (не требующие сохранения на диск)
user_messages_to_delete = {}
user_searches = {}
admin_state = {}  # Для админ-панели

# Строки локализации
STRINGS = {
    'ru': {
        'welcome': "<b>Добро пожаловать в Torrent AI Bot!</b> 🚀\n\nЯ помогу вам найти нужные раздачи на Rutracker и предоставлю выжимку отзывов от нейросети Gemini.\n\nИспользуйте кнопку ниже для поиска.",
        'search_btn': "🔍 Поиск раздач",
        'profile_btn': "👤 Профиль",
        'premium_btn': "🌟 Купить Premium",
        'lang_btn': "🌐 Изменить язык",
        'enter_query': "Введите ваш поисковый запрос (например: <code>The Witcher 3</code>):",
        'searching': "🔍 Ищу раздачи на Rutracker, пожалуйста, подождите...",
        'no_results': "❌ Ничего не найдено по вашему запросу.",
        'results_title': "📋 <b>Результаты поиска по запросу:</b> \"{query}\"\nСтраница {page}/{total_pages}\n\n",
        'author': "Автор",
        'size': "Размер",
        'seeds': "Сиды",
        'leech': "Личи",
        'downloads': "Скачан",
        'get_torrent': "📥 Скачать .torrent",
        'ai_review': "🤖 Выжимка ИИ",
        'next_page': "Вперед ➡️",
        'prev_page': "⬅️ Назад",
        'close': "❌ Закрыть",
        'fetching_torrent': "⏳ Скачиваю торрент-файл...",
        'error_torrent': "❌ Не удалось скачать торрент-файл. Возможно, сессия устарела.",
        'ai_processing': "⏳ Нейросеть Gemini анализирует отзывы пользователей, подождите...",
        'ai_error': "❌ Не удалось получить выжимку отзывов от ИИ.",
        'ai_summary_title': "🤖 <b>Выжимка отзывов ИИ для:</b>\n<i>{title}</i>\n\n",
        'profile_title': "👤 <b>Ваш профиль:</b>\n\nID: <code>{uid}</code>\nСтатус: {status}\nДоступно поисков сегодня: <b>{left}/{max}</b>\nВсего поисков: <b>{total}</b>\n\nПриглашено друзей: <b>{ref_count}</b>\nВаша реферальная ссылка:\n<code>https://t.me/{bot_username}?start={uid}</code>\n\n<i>За каждого приглашенного друга лимит увеличивается на +1 поиск в сутки навсегда!</i>",
        'status_free': "Обычный 🆓",
        'status_premium': "Premium 🌟",
        'premium_buy': "🌟 <b>Преимущества Premium-подписки:</b>\n\n• Полное отключение суточных лимитов на поиск\n• Максимальный приоритет обработки запросов ИИ\n• Доступ к скрытым функциям\n\nСтоимость: <b>25 Telegram Stars</b> в месяц.",
        'premium_active': "🌟 <b>Ваш Premium статус активен!</b>\n\nСуточные лимиты полностью отключены. Спасибо за поддержку проекта!",
        'buy_btn': "🔥 Купить Premium за 25 ⭐️",
        'drop_sub_btn': "⚙️ Сбросить подписку (Тест)",
        'limit_exceeded': "⚠️ <b>Суточный лимит исчерпан!</b>\n\nВы израсходовали свои {max} поиска на сегодня.\n\nЧтобы искать без ограничений, приобретите <b>Premium подписку</b> за Stars или приглашайте друзей по реферальной ссылке в профиле!",
        'payment_title': "Покупка Premium подписки",
        'payment_desc': "Активация Premium статуса в боте на 30 дней.",
        'pay_success': "🎉 <b>Спасибо за покупку!</b>\n\nPremium статус успешно активирован. Приятного пользования!"
    },
    'en': {
        'welcome': "<b>Welcome to Torrent AI Bot!</b> 🚀\n\nI will help you find torrents on Rutracker and provide a summary of user reviews using Gemini AI.\n\nUse the buttons below.",
        'search_btn': "🔍 Search Torrents",
        'profile_btn': "👤 Profile",
        'premium_btn': "🌟 Buy Premium",
        'lang_btn': "🌐 Change Language",
        'enter_query': "Enter your search query (e.g.: <code>The Witcher 3</code>):",
        'searching': "🔍 Searching Rutracker, please wait...",
        'no_results': "❌ No results found for your query.",
        'results_title': "📋 <b>Search results for:</b> \"{query}\"\nPage {page}/{total_pages}\n\n",
        'author': "Author",
        'size': "Size",
        'seeds': "Seeds",
        'leech': "Leech",
        'downloads': "Downloaded",
        'get_torrent': "📥 Download .torrent",
        'ai_review': "🤖 AI Summary",
        'next_page': "Next ➡️",
        'prev_page': "⬅️ Back",
        'close': "❌ Close",
        'fetching_torrent': "⏳ Downloading torrent file...",
        'error_torrent': "❌ Failed to download torrent file. Session might be expired.",
        'ai_processing': "⏳ Gemini AI is analyzing user reviews, please wait...",
        'ai_error': "❌ Failed to get review summary from AI.",
        'ai_summary_title': "🤖 <b>AI Review Summary for:</b>\n<i>{title}</i>\n\n",
        'profile_title': "👤 <b>Your Profile:</b>\n\nID: <code>{uid}</code>\nStatus: {status}\nSearches left today: <b>{left}/{max}</b>\nTotal searches: <b>{total}</b>\n\nFriends invited: <b>{ref_count}</b>\nYour referral link:\n<code>https://t.me/{bot_username}?start={uid}</code>\n\n<i>For each invited friend, your daily limit increases by +1 search forever!</i>",
        'status_free': "Free 🆓",
        'status_premium': "Premium 🌟",
        'premium_buy': "🌟 <b>Premium Subscription Advantages:</b>\n\n• Completely remove daily search limits\n• Maximum priority for AI responses\n• Access to hidden features\n\nCost: <b>25 Telegram Stars</b> per month.",
        'premium_active': "🌟 <b>Your Premium status is active!</b>\n\nDaily limits are completely disabled. Thanks for supporting the project!",
        'buy_btn': "🔥 Buy Premium for 25 ⭐️",
        'drop_sub_btn': "⚙️ Drop Subscription (Test)",
        'limit_exceeded': "⚠️ <b>Daily limit reached!</b>\n\nYou have used your {max} searches for today.\n\nTo search without limits, buy <b>Premium subscription</b> for Stars or invite friends using the link in your profile!",
        'payment_title': "Buy Premium Subscription",
        'payment_desc': "Activation of Premium status in the bot for 30 days.",
        'pay_success': "🎉 <b>Thank you for your purchase!</b>\n\nPremium status has been successfully activated. Enjoy!"
    }
}

session = requests.Session()

def check_moderator(user_obj):
    return user_obj.id in MODERATORS

def login_rutracker():
    try:
        data = {"login_username": RUTRACKER_LOGIN, "login_password": RUTRACKER_PASSWORD, "login": "%C2%F5%EE%E4"}
        res = session.post(RUTRACKER_LOGIN_URL, data=data, headers=HEADERS, timeout=10)
        if "login_username" in res.text:
            print("❌ Ошибка авторизации на Rutracker. Проверьте логин/пароль.")
            return False
        print("✅ Успешная авторизация на Rutracker.")
        return True
    except Exception as e:
        print(f"❌ Ошибка сети при авторизации: {e}")
        return False

# Первая авторизация при запуске
login_rutracker()

# ==========================================
# ИСПРАВЛЕННАЯ СИСТЕМА ЛИМИТОВ С БД И СРОКАМИ
# ==========================================
def check_and_increment_limit(user_obj, chat_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Автосброс лимитов при наступлении нового дня
    cursor.execute("SELECT value FROM system_state WHERE key = 'last_reset_date'")
    last_reset_str = cursor.fetchone()[0]
    today_str = str(datetime.date.today())
    
    if today_str != last_reset_str:
        cursor.execute("UPDATE users SET used_today = 0")
        cursor.execute("UPDATE system_state SET value = ? WHERE key = 'last_reset_date'", (today_str,))
        conn.commit()
        print(f"🔄 Смена суток. Суточные лимиты в БД обнулены.")
        
    conn.close()

    if check_moderator(user_obj):
        return True
        
    # Проверка активности и срока годности Premium
    is_premium = get_user_field(chat_id, "is_premium", 0)
    premium_till = get_user_field(chat_id, "premium_till", None)
    
    if is_premium == 1:
        if premium_till and premium_till != 'forever':
            # Проверяем, не истек ли срок
            till_date = datetime.datetime.strptime(premium_till, "%Y-%m-%d").date()
            if datetime.date.today() > till_date:
                # Подписка кончилась
                set_user_field(chat_id, "is_premium", 0)
                set_user_field(chat_id, "premium_till", None)
                is_premium = 0
                print(f"🗑 У пользователя {chat_id} истек срок Premium.")
            else:
                return True
        else:
            return True

    # Работа с обычными лимитами
    max_limit = get_user_field(chat_id, "max_limit", 3)
    used_today = get_user_field(chat_id, "used_today", 0)
    
    if used_today >= max_limit:
        return False
        
    set_user_field(chat_id, "used_today", used_today + 1)
    total_s = get_user_field(chat_id, "total_searches", 0)
    set_user_field(chat_id, "total_searches", total_s + 1)
    return True

def clear_previous_interface_messages(chat_id):
    if chat_id in user_messages_to_delete:
        for mid in user_messages_to_delete[chat_id]:
            try:
                bot.delete_message(chat_id, mid)
            except Exception:
                pass
        user_messages_to_delete[chat_id] = []

def get_main_keyboard(lang):
    kb = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    kb.add(
        types.KeyboardButton(STRINGS[lang]['search_btn']),
        types.KeyboardButton(STRINGS[lang]['profile_btn']),
        types.KeyboardButton(STRINGS[lang]['premium_btn']),
        types.KeyboardButton(STRINGS[lang]['lang_btn'])
    )
    return kb

@bot.message_handler(commands=['start'])
def send_welcome(m):
    cid = m.chat.id
    ensure_user_exists(cid)
    
    # Обработка реферальной системы
    args = m.text.split()
    if len(args) > 1:
        try:
            referrer_id = int(args[1])
            if referrer_id != cid:
                # Пробуем добавить в базу
                if add_referral_to_db(referrer_id, cid):
                    # Если связь успешно добавлена, увеличиваем лимит рефереру
                    current_max = get_user_field(referrer_id, "max_limit", 3)
                    set_user_field(referrer_id, "max_limit", current_max + 1)
                    try:
                        bot.send_message(referrer_id, f"🎉 По вашей ссылке зарегистрировался друг! Ваш суточный лимит увеличен до <b>{current_max + 1}</b> поисков.", parse_mode="HTML")
                    except Exception:
                        pass
        except ValueError:
            pass

    lang = get_user_field(cid, "lang", "ru")
    clear_previous_interface_messages(cid)
    bot.send_message(cid, STRINGS[lang]['welcome'], reply_markup=get_main_keyboard(lang), parse_mode="HTML")

# ==========================================
# КОД АДМИН-ПАНЕЛИ (УПРАВЛЕНИЕ ПОДПИСКАМИ)
# ==========================================
@bot.message_handler(commands=['admin'])
def admin_panel(m):
    if not check_moderator(m.from_user):
        return
    
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🌟 Выдать Premium", callback_data="admin_give_prem"),
        types.InlineKeyboardButton("❌ Забрать Premium", callback_data="admin_take_prem"),
        types.InlineKeyboardButton("📊 Статистика базы", callback_data="admin_stats"),
        types.InlineKeyboardButton("❌ Закрыть", callback_data="admin_close")
    )
    bot.send_message(m.chat.id, "🛠 <b>Админ-панель управления ботом</b>\nВыберите действие:", reply_markup=kb, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callbacks(call):
    if not check_moderator(call.from_user):
        return
        
    cid = call.message.chat.id
    mid = call.message.message_id
    
    if call.data == "admin_close":
        bot.delete_message(cid, mid)
        
    elif call.data == "admin_stats":
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1")
        premium_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM referrals")
        total_refs = cursor.fetchone()[0]
        conn.close()
        
        text = f"📊 <b>Статистика бота из БД:</b>\n\n" \
               f"👥 Всего пользователей: <b>{total_users}</b>\n" \
               f"🌟 С Премиумом: <b>{premium_users}</b>\n" \
               f"🔗 Всего реферальных связей: <b>{total_refs}</b>"
               
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_back"))
        bot.edit_message_text(text, cid, mid, reply_markup=kb, parse_mode="HTML")
        
    elif call.data == "admin_back":
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("🌟 Выдать Premium", callback_data="admin_give_prem"),
            types.InlineKeyboardButton("❌ Забрать Premium", callback_data="admin_take_prem"),
            types.InlineKeyboardButton("📊 Статистика базы", callback_data="admin_stats"),
            types.InlineKeyboardButton("❌ Закрыть", callback_data="admin_close")
        )
        bot.edit_message_text("🛠 <b>Админ-панель управления ботом</b>\nВыберите действие:", cid, mid, reply_markup=kb, parse_mode="HTML")
        
    elif call.data == "admin_give_prem":
        admin_state[cid] = {'action': 'give_id'}
        msg = bot.send_message(cid, "Введите Telegram ID пользователя, которому хотите <b>выдать</b> Premium:")
        bot.register_next_step_handler(msg, admin_process_id)
        
    elif call.data == "admin_take_prem":
        admin_state[cid] = {'action': 'take_id'}
        msg = bot.send_message(cid, "Введите Telegram ID пользователя, у которого хотите <b>забрать</b> Premium:")
        bot.register_next_step_handler(msg, admin_process_id)

def admin_process_id(m):
    if not check_moderator(m.from_user):
        return
    cid = m.chat.id
    try:
        target_id = int(m.text.strip())
    except ValueError:
        bot.send_message(cid, "❌ Ошибка: ID должен состоять только из цифр. Попробуйте снова через /admin")
        return

    state = admin_state.get(cid, {})
    if state.get('action') == 'take_id':
        set_user_field(target_id, "is_premium", 0)
        set_user_field(target_id, "premium_till", None)
        bot.send_message(cid, f"✅ С пользователя <code>{target_id}</code> успешно снят Premium статус.", parse_mode="HTML")
        try:
            bot.send_message(target_id, "🔴 Администратор аннулировал ваш Premium-статус.")
        except Exception:
            pass
        del admin_state[cid]
    elif state.get('action') == 'give_id':
        admin_state[cid]['target_id'] = target_id
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("🗓 На 30 дней", callback_data="duration_30"),
            types.InlineKeyboardButton("♾ Навсегда", callback_data="duration_forever")
        )
        bot.send_message(cid, f"Выберите срок действия подписки для <code>{target_id}</code>:", reply_markup=kb, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith('duration_'))
def admin_set_duration(call):
    if not check_moderator(call.from_user):
        return
    cid = call.message.chat.id
    mid = call.message.message_id
    
    state = admin_state.get(cid)
    if not state or 'target_id' not in state:
        bot.send_message(cid, "❌ Ошибка сессии. Зайдите в админку заново.")
        return
        
    target_id = state['target_id']
    
    if call.data == "duration_forever":
        set_user_field(target_id, "is_premium", 1)
        set_user_field(target_id, "premium_till", "forever")
        bot.edit_message_text(f"✅ Пользователю <code>{target_id}</code> выдан бессрочный Premium!", cid, mid, parse_mode="HTML")
        try:
            bot.send_message(target_id, "🌟 Администратор выдал вам <b>вечный Premium статус</b>! Все лимиты отключены.", parse_mode="HTML")
        except Exception:
            pass
            
    elif call.data == "duration_30":
        end_date = str(datetime.date.today() + datetime.timedelta(days=30))
        set_user_field(target_id, "is_premium", 1)
        set_user_field(target_id, "premium_till", end_date)
        bot.edit_message_text(f"✅ Пользователю <code>{target_id}</code> выдан Premium до <b>{end_date}</b>", cid, mid, parse_mode="HTML")
        try:
            bot.send_message(target_id, f"🌟 Администратор выдал вам <b>Premium статус на 30 дней</b> (до {end_date})! Все лимиты отключены.", parse_mode="HTML")
        except Exception:
            pass
            
    del admin_state[cid]

# ==========================================
# ОСНОВНОЙ ФУНКЦИОНАЛ БОТА
# ==========================================
@bot.message_handler(func=lambda m: True)
def handle_text(m):
    cid = m.chat.id
    lang = get_user_field(cid, "lang", "ru")
    text = m.text

    if text == STRINGS[lang]['search_btn']:
        clear_previous_interface_messages(cid)
        msg = bot.send_message(cid, STRINGS[lang]['enter_query'], parse_mode="HTML", reply_markup=types.ForceReply(selective=True))
        user_messages_to_delete.setdefault(cid, []).append(msg.message_id)
        bot.register_next_step_handler(msg, process_search_query)
        
    elif text == STRINGS[lang]['profile_btn']:
        clear_previous_interface_messages(cid)
        is_premium = get_user_field(cid, "is_premium", 0)
        status = STRINGS[lang]['status_premium'] if is_premium == 1 else STRINGS[lang]['status_free']
        max_lim = get_user_field(cid, "max_limit", 3)
        used = get_user_field(cid, "used_today", 0)
        total = get_user_field(cid, "total_searches", 0)
        ref_count = get_referrals_count(cid)
        bot_info = bot.get_me()
        
        left = max(0, max_lim - used) if is_premium == 0 else "∞"
        max_str = str(max_lim) if is_premium == 0 else "∞"
        
        p_text = STRINGS[lang]['profile_title'].format(
            uid=cid, status=status, left=left, max=max_str, total=total, ref_count=ref_count, bot_username=bot_info.username
        )
        bot.send_message(cid, p_text, parse_mode="HTML", reply_markup=get_main_keyboard(lang))
        
    elif text == STRINGS[lang]['premium_btn']:
        show_premium(m)
        
    elif text == STRINGS[lang]['lang_btn']:
        clear_previous_interface_messages(cid)
        kb = types.InlineKeyboardMarkup()
        kb.add(
            types.InlineKeyboardButton("Русский 🇷🇺", callback_data="set_lang_ru"),
            types.InlineKeyboardButton("English 🇬🇧", callback_data="set_lang_en")
        )
        bot.send_message(cid, "Выберите язык интерфейса / Choose interface language:", reply_markup=kb)

def show_premium(m):
    cid = m.chat.id
    lang = get_user_field(cid, "lang", "ru")
    clear_previous_interface_messages(cid)
    kb = types.InlineKeyboardMarkup()
    
    is_premium = get_user_field(cid, "is_premium", 0)
    
    # Кнопку удаления/теста убираем для обычных людей. Она видна только модераторам
    if check_moderator(m.from_user):
        if is_premium == 1 or check_moderator(m.from_user):
            kb.add(types.InlineKeyboardButton(STRINGS[lang]['drop_sub_btn'], callback_data="test_drop_my_sub"))
            bot.send_message(cid, STRINGS[lang]['premium_active'], reply_markup=kb, parse_mode="HTML")
    else:
        # Обычный сценарий без кнопки удаления
        if is_premium == 1:
            bot.send_message(cid, STRINGS[lang]['premium_active'], reply_markup=kb, parse_mode="HTML")
        else:
            kb.add(types.InlineKeyboardButton(STRINGS[lang]['buy_btn'], callback_data="buy_premium"))
            bot.send_message(cid, STRINGS[lang]['premium_buy'], reply_markup=kb, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_lang_'))
def callback_language(call):
    cid = call.message.chat.id
    new_lang = call.data.split('_')[2]
    set_user_field(cid, "lang", new_lang)
    bot.delete_message(cid, call.message.message_id)
    bot.send_message(cid, STRINGS[new_lang]['welcome'], reply_markup=get_main_keyboard(new_lang), parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "buy_premium")
def callback_buy(call):
    cid = call.message.chat.id
    lang = get_user_field(cid, "lang", "ru")
    bot.answer_callback_query(call.id)
    
    prices = [types.LabeledPrice(label="Premium 30 Days", amount=25)]
    bot.send_invoice(
        cid,
        title=STRINGS[lang]['payment_title'],
        description=STRINGS[lang]['payment_desc'],
        invoice_payload="premium_subscription_payload",
        provider_token="",  # Пусто для Telegram Stars
        currency="XTR",
        prices=prices,
        start_parameter="premium-buy"
    )

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout_process(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def payment_success(m):
    cid = m.chat.id
    lang = get_user_field(cid, "lang", "ru")
    
    end_date = str(datetime.date.today() + datetime.timedelta(days=30))
    set_user_field(cid, "is_premium", 1)
    set_user_field(cid, "premium_till", end_date)
    
    bot.send_message(cid, STRINGS[lang]['pay_success'], parse_mode="HTML", reply_markup=get_main_keyboard(lang))

@bot.callback_query_handler(func=lambda call: call.data == "test_drop_my_sub")
def callback_drop_sub(call):
    cid = call.message.chat.id
    # Функция сброса доступна только модераторам для тестов
    if check_moderator(call.from_user):
        set_user_field(cid, "is_premium", 0)
        set_user_field(cid, "premium_till", None)
        bot.answer_callback_query(call.id, "Подписка сброшена (Тест)")
        show_premium(call.message)

def process_search_query(m):
    cid = m.chat.id
    lang = get_user_field(cid, "lang", "ru")
    query = m.text

    if not query or query in [STRINGS[lang]['search_btn'], STRINGS[lang]['profile_btn'], STRINGS[lang]['premium_btn'], STRINGS[lang]['lang_btn']]:
        return

    # Проверка лимитов перед обработкой
    if not check_and_increment_limit(m.from_user, cid):
        max_lim = get_user_field(cid, "max_limit", 3)
        bot.send_message(cid, STRINGS[lang]['limit_exceeded'].format(max=max_lim), parse_mode="HTML")
        return

    status_msg = bot.send_message(cid, STRINGS[lang]['searching'])
    
    try:
        results = search_rutracker(query)
        bot.delete_message(cid, status_msg.message_id)
        
        if not results:
            bot.send_message(cid, STRINGS[lang]['no_results'])
            return
            
        user_searches[cid] = {'query': query, 'results': results, 'page': 1}
        send_search_results_page(cid, 1)
        
    except Exception as e:
        try:
            bot.delete_message(cid, status_msg.message_id)
        except Exception:
            pass
        bot.send_message(cid, f"❌ Произошла ошибка при поиске: {e}")

def search_rutracker(query):
    # Код парсинга Rutracker
    params = {"nm": query}
    response = session.get(RUTRACKER_URL, params=params, headers=HEADERS, timeout=15)
    
    if "Перед входом на сайт" in response.text or "login.php" in response.url:
        print("🔄 Сессия устарела. Пробую перелогиниться...")
        if login_rutracker():
            response = session.get(RUTRACKER_URL, params=params, headers=HEADERS, timeout=15)
        else:
            raise Exception("Не удалось пройти авторизацию на трекере.")

    soup = BeautifulSoup(response.content, "html.parser", from_encoding="windows-1251")
    tracker_table = soup.find("table", id="tor-tbl")
    
    if not tracker_table:
        return []
        
    rows = tracker_table.find_all("tr", class_="tCenter")
    parsed_results = []
    
    for row in rows:
        try:
            cells = row.find_all("td")
            if len(cells) < 10:
                continue
                
            category = cells[2].text.strip()
            title_cell = cells[3].find("a", class_="tLink")
            if not title_cell:
                continue
                
            title = title_cell.text.strip()
            topic_id = title_cell["href"].split("?t=")[1]
            
            author = cells[4].text.strip()
            size_bytes = cells[5].get("data-ts_text", "0")
            size_text = cells[5].text.strip().replace(" ", " ")
            
            seeds = int(cells[6].find("b").text.strip() if cells[6].find("b") else cells[6].text.strip() or 0)
            leech = int(cells[7].text.strip() or 0)
            downloads = cells[8].text.strip()
            
            parsed_results.append({
                'topic_id': topic_id,
                'category': category,
                'title': title,
                'author': author,
                'size_text': size_text,
                'seeds': seeds,
                'leech': leech,
                'downloads': downloads
            })
        except Exception as e:
            print(f"Ошибка парсинга строки: {e}")
            continue
            
    return parsed_results

def send_search_results_page(chat_id, page):
    lang = get_user_field(chat_id, "lang", "ru")
    search_data = user_searches.get(chat_id)
    if not search_data:
        return
        
    results = search_data['results']
    query = search_data['query']
    
    items_per_page = 4
    total_pages = (len(results) + items_per_page - 1) // items_per_page
    
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_items = results[start_idx:end_idx]
    
    text = STRINGS[lang]['results_title'].format(query=query, page=page, total_pages=total_pages)
    kb = types.InlineKeyboardMarkup(row_width=1)
    
    for idx, item in enumerate(page_items, start=start_idx):
        text += f"<b>{idx+1}. {html.escape(item['title'])}</b>\n"
        text += f"📂 {html.escape(item['category'])}\n"
        text += f"👤 {STRINGS[lang]['author']}: {html.escape(item['author'])} | 💾 {item['size_text']}\n"
        text += f"🔼 {item['seeds']} | 🔽 {item['leech']} | ✅ {item['downloads']}\n\n"
        
        btn_text = f"📥 #{idx+1} | {item['size_text']}"
        kb.add(types.InlineKeyboardButton(btn_text, callback_data=f"open_{idx}"))
        
    nav_buttons = []
    if page > 1:
        nav_buttons.append(types.InlineKeyboardButton(STRINGS[lang]['prev_page'], callback_data=f"page_{page-1}"))
    if page < total_pages:
        nav_buttons.append(types.InlineKeyboardButton(STRINGS[lang]['next_page'], callback_data=f"page_{page+1}"))
        
    if nav_buttons:
        kb.row(*nav_buttons)
    kb.add(types.InlineKeyboardButton(STRINGS[lang]['close'], callback_data="close_search"))
    
    clear_previous_interface_messages(chat_id)
    msg = bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")
    user_messages_to_delete.setdefault(chat_id, []).append(msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('page_'))
def callback_pagination(call):
    cid = call.message.chat.id
    next_page = int(call.data.split('_')[1])
    if cid in user_searches:
        user_searches[cid]['page'] = next_page
        send_search_results_page(cid, next_page)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "close_search")
def callback_close_search(call):
    cid = call.message.chat.id
    clear_previous_interface_messages(cid)
    if cid in user_searches:
        del user_searches[cid]
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('open_'))
def callback_open_item(call):
    cid = call.message.chat.id
    lang = get_user_field(cid, "lang", "ru")
    idx = int(call.data.split('_')[1])
    
    search_data = user_searches.get(cid)
    if not search_data or idx >= len(search_data['results']):
        bot.answer_callback_query(call.id, "Данные поиска устарели.")
        return
        
    item = search_data['results'][idx]
    bot.answer_callback_query(call.id)
    
    text = f"<b>{html.escape(item['title'])}</b>\n\n"
    text += f"📂 Категория: {html.escape(item['category'])}\n"
    text += f"👤 Автор: {html.escape(item['author'])}\n"
    text += f"💾 Размер: {item['size_text']}\n"
    text += f"🔼 Сиды: {item['seeds']} | 🔽 Личи: {item['leech']}\n"
    text += f"✅ Скачиваний: {item['downloads']}\n"
    
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(STRINGS[lang]['get_torrent'], callback_data=f"dl_{item['topic_id']}"),
        types.InlineKeyboardButton(STRINGS[lang]['ai_review'], callback_data=f"ai_{item['topic_id']}_{idx}"),
        types.InlineKeyboardButton(STRINGS[lang]['prev_page'], callback_data=f"page_{search_data['page']}")
    )
    
    clear_previous_interface_messages(cid)
    msg = bot.send_message(cid, text, reply_markup=kb, parse_mode="HTML")
    user_messages_to_delete.setdefault(cid, []).append(msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('dl_'))
def callback_download_torrent(call):
    cid = call.message.chat.id
    lang = get_user_field(cid, "lang", "ru")
    topic_id = call.data.split('_')[1]
    bot.answer_callback_query(call.id)
    
    status_msg = bot.send_message(cid, STRINGS[lang]['fetching_torrent'])
    try:
        dl_url = f"https://rutracker.org/forum/dl.php?t={topic_id}"
        res = session.get(dl_url, headers=HEADERS, timeout=15)
        
        if len(res.content) < 1000 and "login.php" in res.url:
            login_rutracker()
            res = session.get(dl_url, headers=HEADERS, timeout=15)
            
        bot.delete_message(cid, status_msg.message_id)
        
        if len(res.content) > 1000:
            file_io = io.BytesIO(res.content)
            file_io.name = f"rutracker_{topic_id}.torrent"
            bot.send_document(cid, file_io)
        else:
            bot.send_message(cid, STRINGS[lang]['error_torrent'])
    except Exception as e:
        try:
            bot.delete_message(cid, status_msg.message_id)
        except Exception:
            pass
        bot.send_message(cid, f"❌ Ошибка загрузки файла: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('ai_'))
def callback_ai_review(call):
    cid = call.message.chat.id
    lang = get_user_field(cid, "lang", "ru")
    parts = call.data.split('_')
    topic_id = parts[1]
    back_idx = int(parts[2])
    
    bot.answer_callback_query(call.id)
    status_msg = bot.send_message(cid, STRINGS[lang]['ai_processing'])
    
    try:
        comments = fetch_topic_comments(topic_id)
        if not comments:
            bot.delete_message(cid, status_msg.message_id)
            bot.send_message(cid, "❌ Отзывов на этой раздаче пока нет.")
            return
            
        summary = generate_gemini_summary(comments, lang)
        bot.delete_message(cid, status_msg.message_id)
        
        search_data = user_searches.get(cid)
        title = search_data['results'][back_idx]['title'] if search_data else "Раздача"
        
        response_text = STRINGS[lang]['ai_summary_title'].format(title=html.escape(title)) + summary
        
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(STRINGS[lang]['prev_page'], callback_data=f"open_{back_idx}"))
        
        msg = bot.send_message(cid, response_text, reply_markup=kb, parse_mode="HTML")
        user_messages_to_delete.setdefault(cid, []).append(msg.message_id)
        
    except Exception as e:
        try:
            bot.delete_message(cid, status_msg.message_id)
        except Exception:
            pass
        bot.send_message(cid, STRINGS[lang]['ai_error'] + f" ({e})")

def fetch_topic_comments(topic_id):
    url = f"https://rutracker.org/forum/viewtopic.php?t={topic_id}"
    res = session.get(url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(res.content, "html.parser", from_encoding="windows-1251")
    
    post_bodies = soup.find_all("div", class_="post_body")
    comments = []
    
    for body in post_bodies:
        # Убираем цитаты, чтобы ИИ анализировал только чистый текст текущего юзера
        for quote in body.find_all("q", class_="q"):
            quote.decompose()
        text = body.text.strip()
        if text:
            comments.append(text)
            
    return comments[:20]  # Анализируем первые 20 содержательных комментариев

def generate_gemini_summary(comments, lang):
    compiled_comments = "\n---\n".join(comments)
    
    if lang == 'ru':
        prompt = f"Проанализируй следующие отзывы пользователей о раздаче торрента. Сделай краткую, емкую выжимку на русском языке. Напиши, рабочая ли раздача, какое качество, есть ли баги/проблемы в установке, и каково общее мнение людей. Используй HTML теги для форматирования (строгие правила: только <b>для жирного</b>, <i>для курсива</i>, <code>для кода</code>). Не используй markdown вроде ** или списка через дефисы, делай красивые абзацы.\n\nОтзывы:\n{compiled_comments}"
    else:
        prompt = f"Analyze the following user reviews about a torrent release. Make a short, concise summary in English. Tell if it works, the quality, if there are any bugs/installation issues, and the general consensus. Use HTML tags for formatting (strict rule: only <b>for bold</b>, <i>for italic</i>, <code>for code</code>). Do not use markdown like ** or hyphens for lists, make beautiful paragraphs.\n\nReviews:\n{compiled_comments}"

    response = ai_client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
    )
    
    clean_text = response.text.replace("```html", "").replace("```", "").strip()
    return clean_text

if __name__ == '__main__':
    print("🚀 Бот переведен на SQLite и успешно запущен локально!")
    bot.infinity_polling()
