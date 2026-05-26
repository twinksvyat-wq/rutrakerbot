import os, telebot, requests, io, html, re, datetime
from bs4 import BeautifulSoup
from telebot import types
from google import genai
import urllib.parse

# Настройка секретов и ключей
TOKEN = os.environ.get("TELEGRAM_TOKEN")
R_LOGIN = os.environ.get("RUTRACKER_LOGIN")
R_PASSWORD = os.environ.get("RUTRACKER_PASSWORD")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

if not all([TOKEN, R_LOGIN, R_PASSWORD]):
    print("❌ ОШИБКА: Не настроены обязательные секреты!"); exit(1)

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

CAT_MAP = {"🎬 Кино": "7", "📺 Сериалы": "189", "🎮 Игры": "9", "📚 Книги": "10"}
MODERATORS = ["Ki_l1"]

total_users = set()
total_requests_count = 0
referrals = {}      
user_limits = {}    
user_usage = {}     

premium_users = set()       
premium_dates = {}         
user_total_searches = {}   

user_messages_to_delete = {}

def register_msg_for_deletion(chat_id, message_id):
    if chat_id not in user_messages_to_delete:
        user_messages_to_delete[chat_id] = []
    user_messages_to_delete[chat_id].append(message_id)

def clear_previous_interface_messages(chat_id):
    if chat_id in user_messages_to_delete:
        for msg_id in user_messages_to_delete[chat_id]:
            try: bot.delete_message(chat_id, msg_id)
            except: pass
        user_messages_to_delete[chat_id] = []

def login():
    global BASE_URL
    for domain in DOMAINS:
        try:
            data = {'login_username': R_LOGIN, 'login_password': R_PASSWORD, 'login': 'Вход'}
            res = r_session.post(f"{domain}/forum/login.php", data=data, timeout=15)
            if "login_username" not in res.text and res.status_code == 200:
                BASE_URL = domain; return True
        except: pass
    return False

def clean_html(text):
    if not text: return ""
    text = re.sub(r'<[^>]+>', '', text)
    return html.escape(text)

def check_moderator(user_obj):
    if not user_obj: return False
    username = getattr(user_obj, 'username', None)
    return username and username.lower() in [m.lower() for m in MODERATORS]

def parse_rutracker(query_text, category_id=None):
    try:
        if query_text:
            encoded_query = urllib.parse.quote(query_text.encode('windows-1251'))
            url = f"{BASE_URL}/forum/tracker.php?nm={encoded_query}"
        elif category_id:
            url = f"{BASE_URL}/forum/tracker.php?f={category_id}"
        else: return []

        resp = r_session.get(url, timeout=25)
        if resp.status_code != 200 or "ddos" in resp.text.lower(): return []
        resp.encoding = 'windows-1251'
        soup = BeautifulSoup(resp.text, 'html.parser')
        results = []
        for row in soup.find_all('tr'):
            links = [l for l in row.find_all('a', href=True) if "viewtopic.php?t=" in l['href']]
            if not links: continue
            title = links[0].get_text(strip=True)[:65]
            tid = links[0]['href'].split('t=')[-1]
            size = "---"
            for td in row.find_all('td'):
                if any(u in td.get_text().upper() for u in ['GB', 'MB', 'ГБ', 'МБ']):
                    size = td.get_text(strip=True).split('↓')[0].strip(); break
            results.append({'title': title, 'tid': tid, 'size': size})
        
        unique = []
        seen = set()
        for r in results:
            if r['tid'] not in seen: 
                unique.append(r)
                seen.add(r['tid'])
        return unique[:10]
    except: return []

# 🔥 ПОЛНОСТЬЮ ПЕРЕРАБОТАННЫЙ СКРЕЙПЕР ДЕТАЛЕЙ ТЕМЫ
def parse_topic_details(tid):
    try:
        url = f"{BASE_URL}/forum/viewtopic.php?t={tid}"
        resp = r_session.get(url, timeout=20)
        if resp.status_code != 200:
            return None, "Не удалось загрузить страницу топика.", []
            
        resp.encoding = 'windows-1251'
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 1. Поиск постера
        img_url = None
        img_tag = soup.find('var', class_='postImg')
        if img_tag and img_tag.get('title'):
            img_url = img_tag['title']

        # 2. Извлечение деталей релиза через регулярные выражения (Решает проблему табличной верстки)
        description_text = ""
        main_post = soup.find('td', class_='message', id=re.compile(r'^p-\d+'))
        
        if main_post:
            full_text = main_post.get_text()
            # Убираем лишние пробелы и пустые строки
            lines = [l.strip() for l in full_text.split('\n') if l.strip()]
            
            # Ищем точечные параметры раздачи
            details = {}
            patterns = {
                'версия': re.compile(r'(ℹ️|▪️)?\s*(оф\s+)?(патч\s+)?(версия|v|update)\s*:\s*([^\n]+)', re.IGNORECASE),
                'вес': re.compile(r'(размер|вес)\s*(раздачи|файла)?\s*:\s*([^\n]+)', re.IGNORECASE),
                'таблетка': re.compile(r'(таблетка|лекарство|crack|защита)\s*:\s*([^\n]+)', re.IGNORECASE),
                'язык': re.compile(r'язык\s*(интерфейса|озвучки)?\s*:\s*([^\n]+)', re.IGNORECASE),
                'жанр': re.compile(r'жанр\s*:\s*([^\n]+)', re.IGNORECASE),
                'разработчик': re.compile(r'(разработчик|издатель)\s*:\s*([^\n]+)', re.IGNORECASE)
            }
            
            for line in lines:
                for key, pattern in patterns.items():
                    if key not in details:
                        match = pattern.search(line)
                        if match:
                            # Забираем очищенный хвост совпадения
                            val = line.split(':', 1)[-1].strip()
                            details[key] = re.sub(r'\[[^>]+\]', '', val)[:80] # Режем BB-коды

            # Формируем красивый блок тех. описания
            info_blocks = []
            if 'жанр' in details: info_blocks.append(f"🎮 <b>Жанр:</b> {details['жанр']}")
            if 'версия' in details: info_blocks.append(f"ℹ️ <b>Версия сборки:</b> {details['версия']}")
            if 'вес' in details: info_blocks.append(f"💼 <b>Размер / Вес:</b> {details['вес']}")
            if 'язык' in details: info_blocks.append(f"🗣 <b>Язык:</b> {details['язык']}")
            if 'таблетка' in details: info_blocks.append(f"🏴‍☠️ <b>Таблетка:</b> {details['таблетка']}")
            if 'разработчик' in details: info_blocks.append(f"👨‍💻 <b>Разработчик:</b> {details['разработчик']}")

            # Если регулярками ничего не выцепилось, берем первые 4 читаемые строки раздачи
            if not info_blocks:
                fallback_lines = [l for l in lines if len(l) > 15 and not l.startswith('[')][:4]
                if fallback_lines:
                    description_text = "\n".join(fallback_lines)
                else:
                    description_text = "Технические детали доступны внутри .torrent файла."
            else:
                description_text = "\n".join(info_blocks)
        else:
            description_text = "Не удалось прочитать описание топика."

        # 3. Извлечение комментариев
        comments = []
        all_posts = soup.find_all('tr', class_=re.compile(r'prow\d+'))
        
        # Пропускаем самый первый пост (это сама раздача)
        if len(all_posts) > 1:
            for post_row in all_posts[1:]:
                msg_body = post_row.find('td', class_='message')
                if msg_body:
                    # Клонируем и чистим только цитаты, чтобы не портить остальной текст
                    msg_copy = BeautifulSoup(str(msg_body), 'html.parser')
                    for q in msg_copy.find_all('table', class_='forumline'): q.decompose()
                    
                    txt = msg_copy.get_text().strip()
                    txt = re.sub(r'\[[^>]+\]', '', txt) # Чистка BB-кодов
                    txt = " ".join(txt.split())
                    
                    if len(txt) > 25 and not any(word in txt.lower() for word in ['спасибо', 'благодарю', 'обновил']):
                        comments.append(txt[:300])
                if len(comments) >= 10: break

        return img_url, description_text, comments
    except Exception as e:
        print(f"❌ Критическая ошибка парсера: {e}")
        return None, "Ошибка обработки контента страницы.", []

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
        return response.text.strip() if response.text else "Не удалось проанализировать отзывы."
    except: return "Ошибка генерации вердикта ИИ."

def get_main_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row('🔍 Поиск релизов', '📂 Каталог тем')
    kb.row('👥 Рефералы и Лимиты', '⭐ Безлимитный доступ')
    kb.row('🏠 Главное меню')
    return kb

def check_and_increment_limit(user_obj, chat_id):
    if check_moderator(user_obj) or chat_id in premium_users: return True
    max_limit = user_limits.get(chat_id, 3)
    used_today = user_usage.get(chat_id, 0)
    if used_today >= max_limit: return False
    user_usage[chat_id] = used_today + 1
    return True

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
                try: bot.send_message(referrer_id, "🎉 Новое приглашение! Ваш суточный лимит увеличен на +2.")
                except: pass
        except: pass

    welcome = (
        "🛸 <b>Torrent Archive активен</b>\n\n"
        "Я индексирую раздачи и выдаю файлы напрямую в обход блокировок.\n\n"
        "⚡️ <i>Используйте нижнее меню для работы с поиском.</i>"
    )
    if check_moderator(m.from_user):
        welcome += "\n\n👑 <b>Режим разработчика: Безлимит активирован.</b>"
    bot.send_message(m.chat.id, welcome, reply_markup=get_main_keyboard(), parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text in ['🏠 Главное меню', 'Меню', '/menu'])
def menu_redirect(m): start_cmd(m)

@bot.message_handler(func=lambda m: m.text in ['🔍 Поиск релизов', 'Поиск'])
def ask_search(m):
    clear_previous_interface_messages(m.chat.id)
    bot.send_message(m.chat.id, "✏️ Введи название релиза для поиска в архиве:", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda m: m.text in ['📂 Каталог тем', 'Каталог'])
def show_cat(m):
    clear_previous_interface_messages(m.chat.id)
    kb = types.InlineKeyboardMarkup(row_width=2)
    for name, fid in CAT_MAP.items(): kb.add(types.InlineKeyboardButton(name, callback_data=f"c{fid}"))
    msg = bot.send_message(m.chat.id, "📂 Выберите категорию для быстрого просмотра:", reply_markup=kb)
    register_msg_for_deletion(m.chat.id, msg.message_id)

@bot.message_handler(func=lambda m: m.text == '👥 Рефералы и Лимиты')
def show_ref(m):
    clear_previous_interface_messages(m.chat.id)
    bot_info = bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref{m.chat.id}"
    status = "<b>∞ Безлимит</b>" if (check_moderator(m.from_user) or m.chat.id in premium_users) else f"<b>{user_usage.get(m.chat.id, 0)} из {user_limits.get(m.chat.id, 3)} запросов</b>"
    text = (
        "👥 <b>Лимиты аккаунта</b>\n\n"
        f"▪️ Использовано сегодня: {status}\n"
        f"▪️ Всего приглашено: <b>{len(referrals.get(m.chat.id, []))}</b>\n\n"
        f"🔗 Реферальный инвайт:\n<code>{ref_link}</code>"
    )
    bot.send_message(m.chat.id, text, reply_markup=get_main_keyboard(), parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == '⭐ Безлимитный доступ')
def show_premium(m):
    clear_previous_interface_messages(m.chat.id)
    cid = m.chat.id
    kb = types.InlineKeyboardMarkup()
    if check_moderator(m.from_user) or cid in premium_users:
        kb.add(types.InlineKeyboardButton("🗑 Сбросить подписку (Тест)", callback_data="test_drop_my_sub"))
        bot.send_message(cid, "⭐ <b>Ваш Premium активен!</b>\nСуточные лимиты полностью отключены.", reply_markup=kb, parse_mode="HTML")
    else:
        kb.add(types.InlineKeyboardButton("⭐️ Купить Premium за 25 Звезд", callback_data="buy_premium"))
        bot.send_message(cid, "⭐ <b>Premium доступ</b>\n\nСнимает любые ограничения на поиск и запускает анализ раздач через Gemini нейросеть.", reply_markup=kb, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text not in ['🔍 Поиск релизов', '📂 Каталог тем', '👥 Рефералы и Лимиты', '⭐ Безлимитный доступ', '🏠 Главное меню', '/start', 'Поиск', 'Каталог', 'Меню'])
def handle_text(m):
    global total_requests_count, user_total_searches
    if not check_and_increment_limit(m.from_user, m.chat.id):
        bot.send_message(m.chat.id, "⚠️ Суточный лимит исчерпан. Обновите подписку или пригласите друзей.")
        return

    clear_previous_interface_messages(m.chat.id)
    total_requests_count += 1
    user_total_searches[m.chat.id] = user_total_searches.get(m.chat.id, 0) + 1
    
    status_msg = bot.send_message(m.chat.id, "🔎 Сверяю индексы базы данных...")
    results = parse_rutracker(query_text=m.text)
    
    try: bot.delete_message(m.chat.id, status_msg.message_id)
    except: pass
    
    if results:
        for item in results:
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("📄 Открыть карточку релиза", callback_data=f"v{item['tid']}"))
            text = f"▪️ <b>{clean_html(item['title'])}</b>\n└ 💼 Вес: <code>{clean_html(item['size'])}</code>"
            try:
                msg = bot.send_message(m.chat.id, text, reply_markup=kb, parse_mode="HTML")
                register_msg_for_deletion(m.chat.id, msg.message_id)
            except: pass
    else:
        bot.send_message(m.chat.id, "❌ По данному запросу ничего не найдено.", reply_markup=get_main_keyboard())

@bot.callback_query_handler(func=lambda c: True)
def callbacks(c):
    global user_total_searches, premium_users, premium_dates
    cid = c.message.chat.id
    bot.answer_callback_query(c.id)
    
    if c.data.startswith('c'):
        if not check_and_increment_limit(c.from_user, cid): return
        clear_previous_interface_messages(cid)
        results = parse_rutracker(query_text=None, category_id=c.data[1:])
        if results:
            user_total_searches[cid] = user_total_searches.get(cid, 0) + 1
            for item in results:
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton("📄 Открыть карточку релиза", callback_data=f"v{item['tid']}"))
                text = f"▪️ <b>{clean_html(item['title'])}</b>\n└ 💼 Вес: <code>{clean_html(item['size'])}</code>"
                try:
                    msg = bot.send_message(cid, text, reply_markup=kb, parse_mode="HTML")
                    register_msg_for_deletion(cid, msg.message_id)
                except: pass

    elif c.data.startswith('d'):
        tid = c.data[1:]
        try:
            r = r_session.get(f"{BASE_URL}/forum/dl.php?t={tid}", headers={'Referer': f"{BASE_URL}/forum/viewtopic.php?t={tid}"}, timeout=20)
            f = io.BytesIO(r.content); f.name = f"{tid}.torrent"
            bot.send_document(cid, f, caption="✅ Торрент-файл успешно сгенерирован.")
            clear_previous_interface_messages(cid)
        except: bot.send_message(cid, "❌ Не удалось скачать файл с трекера.")
    
    elif c.data.startswith('v'):
        if not check_and_increment_limit(c.from_user, cid): return
        tid = c.data[1:]
        clear_previous_interface_messages(cid)

        wait_msg = bot.send_message(cid, "⏳ <i>Формирую карточку релиза и опрашиваю Gemini ИИ...</i>", parse_mode="HTML")
        img_url, description, comments = parse_topic_details(tid)
        summary = get_ai_summary(comments)
        
        try: bot.delete_message(cid, wait_msg.message_id)
        except: pass
        
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("📥 Скачать .torrent", callback_data=f"d{tid}"))
        kb.add(types.InlineKeyboardButton("👥 Рефка", callback_data="inline_ref"), types.InlineKeyboardButton("⭐️ Подписка", callback_data="inline_sub"))
        
        title_text = clean_html(c.message.text.split('\n')[0].replace('▪️ ', '')) if c.message.text else "Карточка релиза"
        card_text = f"📦 <b>{title_text}</b>\n\n📋 <b>Детали сборки:</b>\n{description}\n\n🤖 <b>Вердикт ИИ по отзывам:</b>\n<blockquote>{clean_html(summary)}</blockquote>"
        
        try:
            if img_url and (img_url.startswith('http://') or img_url.startswith('https://')):
                msg = bot.send_photo(cid, img_url, caption=card_text[:1024], reply_markup=kb, parse_mode="HTML")
            else: msg = bot.send_message(cid, card_text, reply_markup=kb, parse_mode="HTML")
        except: msg = bot.send_message(cid, card
