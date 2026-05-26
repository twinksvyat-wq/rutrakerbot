import os
import telebot
import requests
import io
import html
import re
import datetime
import urllib.parse
from bs4 import BeautifulSoup
from telebot import types
from google import genai

# ==========================================
# НАСТРОЙКА КОНФИГУРАЦИИ И СЕКРЕТОВ
# ==========================================
TOKEN = os.environ.get("TELEGRAM_TOKEN")
R_LOGIN = os.environ.get("RUTRACKER_LOGIN")
R_PASSWORD = os.environ.get("RUTRACKER_PASSWORD")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

if not all([TOKEN, R_LOGIN, R_PASSWORD]):
    print("❌ КРИТИЧЕСКАЯ ОШИБКА: Проверьте переменные окружения!")
    exit(1)

if GEMINI_KEY:
    ai_client = genai.Client(api_key=GEMINI_KEY)
else:
    ai_client = None

bot = telebot.TeleBot(TOKEN)
r_session = requests.Session()
r_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
})

DOMAINS = ["https://rutracker.net", "https://rutracker.org", "https://rutracker.nl"]
BASE_URL = DOMAINS[0]

CAT_MAP = {
    "🎬 Кино": "7",
    "📺 Сериалы": "189",
    "🎮 Игры": "9",
    "📚 Книги": "10"
}

MODERATORS = ["Ki_l1"]

# ==========================================
# МОДУЛЬ ЛОКАЛИЗАЦИИ И СЛОВАРЕЙ (RU / EN)
# ==========================================
MENU_BUTTONS = {
    'ru': {
        'search': '🔍 Поиск релизов',
        'catalog': '📂 Каталог тем',
        'limits': '👥 Рефералы и Лимиты',
        'premium': '⭐ Безлимитный доступ',
        'menu': '🏠 Главное меню',
        'lang': '🌐 Язык / Language'
    },
    'en': {
        'search': '🔍 Search Releases',
        'catalog': '📂 Topic Catalog',
        'limits': '👥 Referrals & Limits',
        'premium': '⭐ Unlimited Access',
        'menu': '🏠 Main Menu',
        'lang': '🌐 Language / Язык'
    }
}

STRINGS = {
    'ru': {
        'welcome': "🛸 <b>Torrent Archive активен</b>\n\nЯ индексирую раздачи и выдаю файлы напрямую в обход блокировок.\n\n⚡️ <i>Используйте нижнее меню для работы с поиском.</i>",
        'dev_mode': "\n\n👑 <b>Режим разработчика: Безлимит активирован.</b>",
        'ask_search': "✏️ Введи название релиза для поиска в архиве:",
        'show_cat': "📂 Выберите категорию для быстрого просмотра:",
        'search_status': "🔎 Сверяю индексы базы данных...",
        'no_results': "❌ По данному запросу ничего не найдено.",
        'limit_exceeded': "⚠️ Суточный лимит исчерпан. Обновите подписку или пригласите друзей.",
        'card_loading': "⏳ <i>Формирую карточку релиза и опрашиваю Gemini ИИ...</i>",
        'verdict_title': "🤖 <b>Вердикт ИИ по отзывам:</b>",
        'details_title': "📋 <b>Детали сборки:</b>",
        'download_btn': "📥 Скачать .torrent",
        'ref_btn': "👥 Рефка",
        'sub_btn': "⭐️ Подписка",
        'torrent_success': "✅ Торрент-файл успешно сгенерирован.",
        'torrent_fail': "❌ Не удалось скачать файл с трекера.",
        'premium_active': "⭐ <b>Ваш Premium активен!</b>\nСуточные лимиты отключены.",
        'premium_buy': "⭐ <b>Premium доступ</b>\n\nСнимает любые ограничения на поиск и запускает анализ раздач через Gemini нейросеть.",
        'buy_btn': "⭐️ Купить Premium за 25 Звезд",
        'drop_sub_btn': "🗑 Сбросить подписку (Тест)",
        'lang_select': "🌐 Выберите язык интерфейса / Select interface language:",
        'lang_changed': "✅ Язык успешно изменен на Русский!",
        'ref_link_msg': "🔗 <b>Реферальная ссылка:</b>\n",
        'card_err': "Не удалось загрузить страницу топика.",
        'parse_err': "Ошибка обработки контента страницы.",
        'card_btn': "📄 Открыть карточку релиза",
        'weight': "Вес",
        'prev_btn': "⬅️ Назад",
        'next_btn': "Вперед ➡️",
        'search_header': "🔍 <b>Результаты поиска (Страница {current} из {total}):</b>\nВыбери релиз для открытия карточки:"
    },
    'en': {
        'welcome': "🛸 <b>Torrent Archive is active</b>\n\nI index releases and provide files directly bypassing blocks.\n\n⚡️ <i>Use the bottom menu to search.</i>",
        'dev_mode': "\n\n👑 <b>Developer Mode: Unlimited activated.</b>",
        'ask_search': "✏️ Enter the release name to search the archive:",
        'show_cat': "📂 Select a category for quick browsing:",
        'search_status': "🔎 Checking database matrix...",
        'no_results': "❌ Nothing found for this request.",
        'limit_exceeded': "⚠️ Daily limit exceeded. Upgrade your subscription or invite friends.",
        'card_loading': "⏳ <i>Generating release card and querying Gemini AI...</i>",
        'verdict_title': "🤖 <b>AI Verdict based on reviews:</b>",
        'details_title': "📋 <b>Build Details:</b>",
        'download_btn': "📥 Download .torrent",
        'ref_btn': "👥 Ref Link",
        'sub_btn': "⭐️ Subscription",
        'torrent_success': "✅ Torrent file successfully generated.",
        'torrent_fail': "❌ Failed to download file from tracker.",
        'premium_active': "⭐ <b>Your Premium is active!</b>\nDaily limits are disabled.",
        'premium_buy': "⭐ <b>Premium Access</b>\n\nRemoves all search limitations and enables release review analysis via Gemini AI.",
        'buy_btn': "⭐️ Buy Premium for 25 Stars",
        'drop_sub_btn': "🗑 Reset subscription (Test)",
        'lang_select': "🌐 Select interface language / Выберите язык интерфейса:",
        'lang_changed': "✅ Language successfully changed to English!",
        'ref_link_msg': "🔗 <b>Referral link:</b>\n",
        'card_err': "Failed to load topic page.",
        'parse_err': "Error processing page content.",
        'card_btn': "📄 Open release card",
        'weight': "Weight",
        'prev_btn': "⬅️ Back",
        'next_btn': "Forward ➡️",
        'search_header': "🔍 <b>Search Results (Page {current} of {total}):</b>\nSelect a release to view details:"
    }
}

# ==========================================
# ХРАНИЛИЩА ДАННЫХ В ПАМЯТИ (ОПЕРАТИВКА)
# ==========================================
user_lang = {}              
total_users = set()
total_requests_count = 0
referrals = {}      
user_limits = {}    
user_usage = {}     

premium_users = set()       
premium_dates = {}         
user_total_searches = {}   

user_messages_to_delete = {}
user_searches = {}  

# ==========================================
# СИСТЕМА УПРАВЛЕНИЯ ИНТЕРФЕЙСОМ (ОЧИСТКА)
# ==========================================
def register_msg_for_deletion(chat_id, message_id):
    if chat_id not in user_messages_to_delete:
        user_messages_to_delete[chat_id] = []
    user_messages_to_delete[chat_id].append(message_id)

def clear_previous_interface_messages(chat_id):
    if chat_id in user_messages_to_delete:
        for msg_id in user_messages_to_delete[chat_id]:
            try:
                bot.delete_message(chat_id, msg_id)
            except Exception:
                pass
        user_messages_to_delete[chat_id] = []

# ==========================================
# АВТОРИЗАЦИЯ И СЕССИЯ RUTRACKER
# ==========================================
def login():
    global BASE_URL
    print("⏳ Попытка авторизации на зеркалах Rutracker...")
    for domain in DOMAINS:
        try:
            data = {
                'login_username': R_LOGIN,
                'login_password': R_PASSWORD,
                'login': 'Вход'
            }
            res = r_session.post(f"{domain}/forum/login.php", data=data, timeout=15)
            if "login_username" not in res.text and res.status_code == 200:
                BASE_URL = domain
                print(f"✅ Успешный вход! Активное зеркало: {BASE_URL}")
                return True
        except Exception as e:
            print(f"⚠️ Зеркало {domain} недоступно: {e}")
    return False

def clean_html(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    return html.escape(text)

def check_moderator(user_obj):
    if not user_obj:
        return False
    username = getattr(user_obj, 'username', None)
    if username and username.lower() in [m.lower() for m in MODERATORS]:
        return True
    return False

# ==========================================
# НАДЁЖНЫЙ ПАРСЕР ПОИСКОВОЙ ВЫДАЧИ
# ==========================================
def parse_rutracker(query_text, category_id=None, retry=True):
    try:
        if query_text:
            encoded_query = urllib.parse.quote(query_text.encode('windows-1251'))
            url = f"{BASE_URL}/forum/tracker.php?nm={encoded_query}"
        elif category_id:
            url = f"{BASE_URL}/forum/tracker.php?f={category_id}"
        else:
            return []

        resp = r_session.get(url, timeout=25)
        resp.encoding = 'windows-1251'
        
        if resp.status_code != 200 or "login_username" in resp.text or "ddos" in resp.text.lower():
            if retry:
                if login():
                    return parse_rutracker(query_text, category_id, retry=False)
            return []
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        results = []
        
        rows = soup.find_all('tr', class_='tCenter')
        if not rows:
            rows = soup.find_all('tr')
        
        for row in rows:
            links = [l for l in row.find_all('a', href=True) if "viewtopic.php?t=" in l['href']]
            if not links:
                continue
                
            title = links[0].get_text(strip=True)[:55]
            tid = links[0]['href'].split('t=')[-1]
            size = "---"
            
            for td in row.find_all('td'):
                td_text = td.get_text().upper()
                if any(u in td_text for u in ['GB', 'MB', 'ГБ', 'МБ']):
                    size = td.get_text(strip=True).split('↓')[0].strip()
                    break
                    
            results.append({'title': title, 'tid': tid, 'size': size})
        
        unique = []
        seen = set()
        for r in results:
            if r['tid'] not in seen: 
                unique.append(r)
                seen.add(r['tid'])
                
        if not unique and retry:
            if login():
                return parse_rutracker(query_text, category_id, retry=False)
                
        return unique[:40]
    except Exception as e:
        print(f"❌ Системная ошибка поиска: {e}")
        return []

# ==========================================
# НОВЫЙ АВТОНОМНЫЙ ПАРСЕР СТРАНИЦЫ РАЗДАЧИ
# ==========================================
def parse_topic_details(tid):
    try:
        url = f"{BASE_URL}/forum/viewtopic.php?t={tid}"
        resp = r_session.get(url, timeout=20)
        if resp.status_code != 200:
            return None, "Не удалось загрузить страницу топика.", []
            
        resp.encoding = 'windows-1251'
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Получение постера
        img_url = None
        img_tag = soup.find('var', class_='postImg')
        if img_tag and img_tag.get('title'):
            img_url = img_tag['title']

        # Извлекаем основной контейнер раздачи на Rutracker
        postbody = soup.find('span', class_='postbody')
        if not postbody:
            postbody = soup.find('td', class_='message')
        
        description_text = ""
        if postbody:
            post_copy = BeautifulSoup(str(postbody), 'html.parser')
            
            # Важно: Вырезаем все спойлеры, чтобы убрать скриншоты и логи установки
            for sp in post_copy.find_all('div', class_='sp-wrap'):
                sp.decompose()
                
            full_text = post_copy.get_text()
            lines = [l.strip() for l in full_text.split('\n') if l.strip()]
            
            # Сбор структурированных характеристик
            details = {}
            for line in lines:
                line_lower = line.lower()
                if 'жанр' in line_lower and 'жанр' not in details:
                    details['жанр'] = line.split(':', 1)[-1].strip()
                elif ('версия' in line_lower or 'v/' in line_lower or 'update' in line_lower) and 'версия' not in details:
                    details['версия'] = line.split(':', 1)[-1].strip()
                elif ('размер' in line_lower or 'вес' in line_lower) and 'вес' not in details:
                    details['вес'] = line.split(':', 1)[-1].strip()
                elif 'язык' in line_lower and 'язык' not in details:
                    details['язык'] = line.split(':', 1)[-1].strip()
                elif ('таблетка' in line_lower or 'лекарство' in line_lower or 'crack' in line_lower) and 'таблетка' not in details:
                    details['таблетка'] = line.split(':', 1)[-1].strip()
                elif ('разработчик' in line_lower or 'издатель' in line_lower) and 'разработчик' not in details:
                    details['разработчик'] = line.split(':', 1)[-1].strip()

            info_blocks = []
            if 'жанр' in details: info_blocks.append(f"🎮 <b>Жанр:</b> {details['жанр']}")
            if 'версия' in details: info_blocks.append(f"ℹ️ <b>Версия:</b> {details['версия']}")
            if 'вес' in details: info_blocks.append(f"💼 <b>Размер / Вес:</b> {details['вес']}")
            if 'язык' in details: info_blocks.append(f"🗣 <b>Язык:</b> {details['язык']}")
            if 'таблетка' in details: info_blocks.append(f"🏴‍☠️ <b>Таблетка:</b> {details['таблетка']}")
            if 'разработчик' in details: info_blocks.append(f"👨‍💻 <b>Разработчик:</b> {details['разработчик']}")

            # Если структурированные параметры не поймались — берем текстовое превью раздачи
            if len(info_blocks) < 2:
                fallback_lines = []
                for l in lines:
                    if len(l) > 12 and not l.startswith('[') and not l.endswith(']'):
                        fallback_lines.append(l)
                    if len(fallback_lines) >= 8: # Ограничиваемся 8 красивыми строками описания
                        break
                if fallback_lines:
                    description_text = "\n".join(fallback_lines)
                else:
                    description_text = "Техническая сводка доступна непосредственно внутри загружаемого торрент-файла."
            else:
                description_text = "\n".join(info_blocks)
        else:
            description_text = "Описание релиза не найдено или скрыто трекером."

        # Сбор комментариев для ИИ
        comments = []
        all_posts = soup.find_all('tr', class_=re.compile(r'prow\d+'))
        if len(all_posts) > 1:
            for post_row in all_posts[1:]:
                msg_body = post_row.find('td', class_='message')
                if msg_body:
                    msg_copy = BeautifulSoup(str(msg_body), 'html.parser')
                    for q in msg_copy.find_all('table', class_='forumline'): 
                        q.decompose()
                    txt = msg_copy.get_text().strip()
                    txt = re.sub(r'\[[^>]+\]', '', txt)
                    txt = " ".join(txt.split())
                    if len(txt) > 25 and not any(w in txt.lower() for w in ['спасибо', 'благодарю', 'обновил']):
                        comments.append(txt[:300])
                if len(comments) >= 10: 
                    break

        return img_url, description_text, comments
    except Exception as e:
        print(f"❌ Ошибка парсера страниц: {e}")
        return None, "Ошибка обработки текстового контента страницы.", []

# ==========================================
# ИНТЕГРАЦИЯ С GEMINI AI API
# ==========================================
def get_ai_summary(comments):
    if not ai_client or not comments:
        return "Отзывы к релизу отсутствуют или в ветке пока нет обсуждений."
    raw_text = "\n".join([f"- {c}" for c in comments])
    prompt = (
        "Ты — ИИ-модератор торрент-трекера. Оцени качество релиза по комментариям пользователей.\n"
        "Выдай ультра-короткий вердикт (строго до 2 предложений): работает ли игра/программа, стабильный ли FPS, "
        "нет ли критических багов, вылетов на Win 11 или скрытых вирусов. Пиши сразу факты, без воды."
        f"\n\nКомментарии пользователей:\n{raw_text}"
    )
    try:
        response = ai_client.models.generate_content(model='gemini-1.5-flash', contents=prompt)
        if response.text: return response.text.strip()
        return "Не удалось проанализировать отзывы."
    except Exception: 
        return "Ошибка генерации вердикта ИИ."

# ==========================================
# ГЕНЕРАТОРЫ ИНТЕРФЕЙСА И ПАГИНАЦИИ
# ==========================================
def get_main_keyboard(chat_id):
    lang = user_lang.get(chat_id, 'ru')
    b = MENU_BUTTONS[lang]
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(b['search'], b['catalog'])
    kb.row(b['limits'], b['premium'])
    kb.row(b['menu'], b['lang'])
    return kb

def check_and_increment_limit(user_obj, chat_id):
    if check_moderator(user_obj) or chat_id in premium_users: 
        return True
    max_limit = user_limits.get(chat_id, 3)
    used_today = user_usage.get(chat_id, 0)
    if used_today >= max_limit: 
        return False
    user_usage[chat_id] = used_today + 1
    return True

def render_search_page(chat_id, message_id=None):
    lang = user_lang.get(chat_id, 'ru')
    state = user_searches.get(chat_id)
    if not state or not state["results"]:
        bot.send_message(chat_id, STRINGS[lang]['no_results'], reply_markup=get_main_keyboard(chat_id))
        return

    results = state["results"]
    page = state["page"]
    start_idx = page * 5
    end_idx = start_idx + 5
    page_items = results[start_idx:end_idx]
    total_items = len(results)
    total_pages = (total_items + 4) // 5

    kb = types.InlineKeyboardMarkup(row_width=1)
    for item in page_items:
        lbl = STRINGS[lang]['weight']
        btn_text = f"📄 {clean_html(item['title'])} [{lbl}: {clean_html(item['size'])}]"
        kb.add(types.InlineKeyboardButton(btn_text, callback_data=f"v{item['tid']}"))
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton(STRINGS[lang]['prev_btn'], callback_data="nav_prev"))
    if end_idx < total_items:
        nav_buttons.append(types.InlineKeyboardButton(STRINGS[lang]['next_btn'], callback_data="nav_next"))
    
    if nav_buttons:
        kb.row(*nav_buttons)

    header = STRINGS[lang]['search_header'].format(current=page + 1, total=total_pages)
    if message_id:
        try: bot.edit_message_text(header, chat_id, message_id, reply_markup=kb, parse_mode="HTML")
        except Exception:
            msg = bot.send_message(chat_id, header, reply_markup=kb, parse_mode="HTML")
            register_msg_for_deletion(chat_id, msg.message_id)
    else:
        msg = bot.send_message(chat_id, header, reply_markup=kb, parse_mode="HTML")
        register_msg_for_deletion(chat_id, msg.message_id)

def show_welcome_after_lang(chat_id, from_user):
    lang = user_lang.get(chat_id, 'ru')
    welcome = STRINGS[lang]['welcome']
    if check_moderator(from_user): welcome += STRINGS[lang]['dev_mode']
    bot.send_message(chat_id, welcome, reply_markup=get_main_keyboard(chat_id), parse_mode="HTML")

# ==========================================
# ХЕНДЛЕРЫ КНОПОК И КОМАНД
# ==========================================
@bot.message_handler(commands=['start'])
def start_cmd(m):
    total_users.add(m.chat.id)
    if m.chat.id not in user_limits: user_limits[m.chat.id] = 3
    if m.chat.id not in user_usage: user_usage[m.chat.id] = 0
    if m.chat.id not in user_total_searches: user_total_searches[m.chat.id] = 0
    clear_previous_interface_messages(m.chat.id)
    
    args = m.text.split()
    if len(args) > 1 and args[1].startswith('ref'):
        try:
            referrer_id = int(args[1].replace('ref', ''))
            if referrer_id != m.chat.id and m.chat.id not in referrals.get(referrer_id, []):
                if referrer_id not in referrals: referrals[referrer_id] = []
                referrals[referrer_id].append(m.chat.id)
                user_limits[referrer_id] = user_limits.get(referrer_id, 3) + 2
                try: 
                    lang = user_lang.get(referrer_id, 'ru')
                    msg_text = "🎉 Новое приглашение! Ваш суточный лимит увеличен на +2." if lang == 'ru' else "🎉 New referral! Your daily limit increased by +2."
                    bot.send_message(referrer_id, msg_text)
                except: pass
        except: pass

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🇷🇺 Русский", callback_data="init_lang_ru"))
    kb.add(types.InlineKeyboardButton("🇬🇧 English", callback_data="init_lang_en"))
    bot.send_message(m.chat.id, "🌐 Выберите язык интерфейса / Select interface language:", reply_markup=kb)

@bot.message_handler(commands=['force_pay_test'])
def force_pay_test(m):
    if check_moderator(m.from_user):
        global premium_users, premium_dates
        premium_users.add(m.chat.id)
        premium_dates[m.chat.id] = datetime.datetime.now()
        bot.send_message(m.chat.id, "🪄 <b>Симулятор оплаты сработал! Тебе выдан Premium.</b>", parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text in [MENU_BUTTONS['ru']['menu'], MENU_BUTTONS['en']['menu'], '🏠 Главное меню', 'Меню', '/menu'])
def menu_redirect(m): 
    if m.chat.id not in user_lang: user_lang[m.chat.id] = 'ru'
    show_welcome_after_lang(m.chat.id, m.from_user)

@bot.message_handler(func=lambda m: m.text in [MENU_BUTTONS['ru']['search'], MENU_BUTTONS['en']['search'], '🔍 Поиск релизов', 'Поиск'])
def ask_search(m):
    lang = user_lang.get(m.chat.id, 'ru')
    clear_previous_interface_messages(m.chat.id)
    bot.send_message(m.chat.id, STRINGS[lang]['ask_search'], reply_markup=get_main_keyboard(m.chat.id))

@bot.message_handler(func=lambda m: m.text in [MENU_BUTTONS['ru']['catalog'], MENU_BUTTONS['en']['catalog'], '📂 Каталог тем', 'Каталог'])
def show_cat(m):
    lang = user_lang.get(m.chat.id, 'ru')
    clear_previous_interface_messages(m.chat.id)
    kb = types.InlineKeyboardMarkup(row_width=2)
    for name, fid in CAT_MAP.items(): 
        kb.add(types.InlineKeyboardButton(name, callback_data=f"c{fid}"))
    msg = bot.send_message(m.chat.id, STRINGS[lang]['show_cat'], reply_markup=kb)
    register_msg_for_deletion(m.chat.id, msg.message_id)

@bot.message_handler(func=lambda m: m.text in [MENU_BUTTONS['ru']['limits'], MENU_BUTTONS['en']['limits']])
def show_ref(m):
    lang = user_lang.get(m.chat.id, 'ru')
    clear_previous_interface_messages(m.chat.id)
    bot_info = bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref{m.chat.id}"
    
    if check_moderator(m.from_user) or m.chat.id in premium_users:
        status = "<b>∞ Безлимит</b>" if lang == 'ru' else "<b>∞ Unlimited</b>"
    else:
        status = f"<b>{user_usage.get(m.chat.id, 0)} из {user_limits.get(m.chat.id, 3)}</b>" if lang == 'ru' else f"<b>{user_usage.get(m.chat.id, 0)} of {user_limits.get(m.chat.id, 3)}</b>"
        
    if lang == 'ru':
        text = (
            "👥 <b>Лимиты аккаунта</b>\n\n"
            f"▪️ Использовано сегодня: {status}\n"
            f"▪️ Всего приглашено: <b>{len(referrals.get(m.chat.id, []))}</b>\n\n"
            f"🔗 Реферальный инвайт:\n<code>{ref_link}</code>"
        )
    else:
        text = (
            "👥 <b>Account Limits</b>\n\n"
            f"▪️ Used today: {status}\n"
            f"▪️ Total invited: <b>{len(referrals.get(m.chat.id, []))}</b>\n\n"
            f"🔗 Referral Invite:\n<code>{ref_link}</code>"
        )
    bot.send_message(m.chat.id, text, reply_markup=get_main_keyboard(m.chat.id), parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text in [MENU_BUTTONS['ru']['premium'], MENU_BUTTONS['en']['premium']])
def show_premium(m):
    lang = user_lang.get(m.chat.id, 'ru')
    clear_previous_interface_messages(m.chat.id)
    cid = m.chat.id
    kb = types.InlineKeyboardMarkup()
    
    if check_moderator(m.from_user) or cid in premium_users:
        kb.add(types.InlineKeyboardButton(STRINGS[lang]['drop_sub_btn'], callback_data="test_drop_my_sub"))
        bot.send_message(cid, STRINGS[lang]['premium_active'], reply_markup=kb, parse_mode="HTML")
    else:
        kb.add(types.InlineKeyboardButton(STRINGS[lang]['buy_btn'], callback_data="buy_premium"))
        bot.send_message(cid, STRINGS[lang]['premium_buy'], reply_markup=kb, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text in [MENU_BUTTONS['ru']['lang'], MENU_BUTTONS['en']['lang']])
def show_lang_menu(m):
    lang = user_lang.get(m.chat.id, 'ru')
    clear_previous_interface_messages(m.chat.id)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🇷🇺 Русский", callback_data="set_lang_ru"))
    kb.add(types.InlineKeyboardButton("🇬🇧 English", callback_data="set_lang_en"))
    bot.send_message(m.chat.id, STRINGS[lang]['lang_select'], reply_markup=kb)

# ==========================================
# ОБРАБОТЧИК КОРНЕВОГО ПОИСКА
# ==========================================
BLACKLIST_TEXTS = ['🏠 Главное меню', 'Меню', '/menu', 'Поиск', 'Каталог', '/start', '/force_pay_test']
for sub_dict in MENU_BUTTONS.values():
    for btn_name in sub_dict.values(): BLACKLIST_TEXTS.append(btn_name)

@bot.message_handler(func=lambda m: m.text not in BLACKLIST_TEXTS)
def handle_text(m):
    lang = user_lang.get(m.chat.id, 'ru')
    global total_requests_count, user_total_searches
    
    if not check_and_increment_limit(m.from_user, m.chat.id):
        bot.send_message(m.chat.id, STRINGS[lang]['limit_exceeded'])
        return

    clear_previous_interface_messages(m.chat.id)
    total_requests_count += 1
    user_total_searches[m.chat.id] = user_total_searches.get(m.chat.id, 0) + 1
    
    status_msg = bot.send_message(m.chat.id, STRINGS[lang]['search_status'])
    results = parse_rutracker(query_text=m.text)
    
    try: bot.delete_message(m.chat.id, status_msg.message_id)
    except: pass
    
    if results:
        user_searches[m.chat.id] = {"results": results, "page": 0}
        render_search_page(m.chat.id)
    else:
        bot.send_message(m.chat.id, STRINGS[lang]['no_results'], reply_markup=get_main_keyboard(m.chat.id))

# ==========================================
# СИСТЕМА ОБРАБОТКИ CALLBACK ДЕЙСТВИЙ
# ==========================================
@bot.callback_query_handler(func=lambda c: True)
def callbacks(c):
    global user_total_searches, premium_users, premium_dates
    cid = c.message.chat.id
    bot.answer_callback_query(c.id)
    lang = user_lang.get(cid, 'ru')
    
    if c.data == "init_lang_ru":
        user_lang[cid] = 'ru'
        try: bot.delete_message(cid, c.message.message_id)
        except: pass
        show_welcome_after_lang(cid, c.from_user)
    elif c.data == "init_lang_en":
        user_lang[cid] = 'en'
        try: bot.delete_message(cid, c.message.message_id)
        except: pass
        show_welcome_after_lang(cid, c.from_user)
        
    elif c.data == "set_lang_ru":
        user_lang[cid] = 'ru'
        bot.send_message(cid, STRINGS['ru']['lang_changed'], reply_markup=get_main_keyboard(cid))
    elif c.data == "set_lang_en":
        user_lang[cid] = 'en'
        bot.send_message(cid, STRINGS['en']['lang_changed'], reply_markup=get_main_keyboard(cid))
        
    elif c.data == "nav_prev":
        if cid in user_searches and user_searches[cid]["page"] > 0:
            user_searches[cid]["page"] -= 1
            render_search_page(cid, c.message.message_id)
            
    elif c.data == "nav_next":
        if cid in user_searches:
            state = user_searches[cid]
            if (state["page"] + 1) * 5 < len(state["results"]):
                state["page"] += 1
                render_search_page(cid, c.message.message_id)

    elif c.data.startswith('c'):
        if not check_and_increment_limit(c.from_user, cid): return
        clear_previous_interface_messages(cid)
        results = parse_rutracker(query_text=None, category_id=c.data[1:])
        if results:
            user_total_searches[cid] = user_total_searches.get(cid, 0) + 1
            user_searches[cid] = {"results": results, "page": 0}
            render_search_page(cid)

    elif c.data.startswith('d'):
        tid = c.data[1:]
        try:
            r = r_session.get(f"{BASE_URL}/forum/dl.php?t={tid}", headers={'Referer': f"{BASE_URL}/forum/viewtopic.php?t={tid}"}, timeout=20)
            f = io.BytesIO(r.content)
            f.name = f"{tid}.torrent"
            bot.send_document(cid, f, caption=STRINGS[lang]['torrent_success'])
            clear_previous_interface_messages(cid)
        except Exception: 
            bot.send_message(cid, STRINGS[lang]['torrent_fail'])
    
    elif c.data.startswith('v'):
        if not check_and_increment_limit(c.from_user, cid): return
        tid = c.data[1:]
        clear_previous_interface_messages(cid)

        wait_msg = bot.send_message(cid, STRINGS[lang]['card_loading'], parse_mode="HTML")
        img_url, description, comments = parse_topic_details(tid)
        summary = get_ai_summary(comments)
        
        try: bot.delete_message(cid, wait_msg.message_id)
        except: pass
        
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton(STRINGS[lang]['download_btn'], callback_data=f"d{tid}"))
        kb.add(types.InlineKeyboardButton(STRINGS[lang]['ref_btn'], callback_data="inline_ref"))
        kb.add(types.InlineKeyboardButton(STRINGS[lang]['sub_btn'], callback_data="inline_sub"))
        
        title_text = "Release Card" if lang == 'en' else "Карточка релиза"
        card_text = f"📦 <b>{title_text}</b>\n\n{STRINGS[lang]['details_title']}\n{description}\n\n{STRINGS[lang]['verdict_title']}\n<blockquote>{clean_html(summary)}</blockquote>"
        
        try:
            if img_url and (img_url.startswith('http://') or img_url.startswith('https://')):
                msg = bot.send_photo(cid, img_url, caption=card_text[:1024], reply_markup=kb, parse_mode="HTML")
            else:
                msg = bot.send_message(cid, card_text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            msg = bot.send_message(cid, card_text, reply_markup=kb, parse_mode="HTML")
            
        if msg: register_msg_for_deletion(cid, msg.message_id)
            
    elif c.data in ['buy_premium', 'inline_sub']:
        if cid in premium_users: return
        prices = [types.LabeledPrice(label='Premium (1 month)', amount=25)]
        try:
            desc = "Premium access and Gemini AI reviews analysis" if lang == 'en' else "Снятие лимитов и активация ИИ-анализа комментариев."
            bot.send_invoice(
                chat_id=cid, title="⭐ Premium Access", description=desc,
                invoice_payload="monthly_premium_stars", provider_token="", 
                currency="XTR", prices=prices, start_parameter="premium-sub"
            )
        except Exception as e: 
            bot.send_message(cid, f"❌ Invoice Error: {e}")
        
    elif c.data == 'inline_ref':
        bot_info = bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref{cid}"
        bot.send_message(cid, f"{STRINGS[lang]['ref_link_msg']}<code>{ref_link}</code>", parse_mode="HTML")

    elif c.data == "test_drop_my_sub":
        if cid in premium_users: premium_users.remove(cid)
        user_usage[cid] = 0 
        bot.send_message(cid, "🗑 Sub dropped." if lang == 'en' else "🗑 Подписка сброшена.")
        show_premium(c.message)

# ==========================================
# ПРОВЕРКА ПЛАТЕЖЕЙ STARS (XTR)
# ==========================================
@bot.pre_checkout_query_handler(func=lambda query: True)
def process_pre_checkout(pre_query):
    bot.answer_pre_checkout_query(pre_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def payment_success(m):
    global premium_users, premium_dates
    if m.successful_payment.invoice_payload == "monthly_premium_stars":
        premium_users.add(m.chat.id)
        premium_dates[m.chat.id] = datetime.datetime.now()
        lang = user_lang.get(m.chat.id, 'ru')
        ok_msg = "🎉 Premium successfully activated!" if lang == 'en' else "🎉 Premium успешно подключен!"
        bot.send_message(m.chat.id, ok_msg, reply_markup=get_main_keyboard(m.chat.id), parse_mode="HTML")

# ==========================================
# ТОЧКА ВХОДА В ПРИЛОЖЕНИЕ (INFINITY POLLING)
# ==========================================
if __name__ == '__main__':
    if login():
        print("🚀 Бот запущен. Автономные описания и пагинация активны.")
        bot.infinity_polling(timeout=15, long_polling_timeout=5)
