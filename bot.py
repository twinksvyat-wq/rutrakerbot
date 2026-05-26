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
    print("❌ ОШИБКА: Не настроены обязательные секреты GitHub!"); exit(1)

if GEMINI_KEY:
    ai_client = genai.Client(api_key=GEMINI_KEY)
else:
    ai_client = None

bot = telebot.TeleBot(TOKEN)
r_session = requests.Session()
r_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept-Charset': 'windows-1251,utf-8;q=0.7,*;q=0.7' # Принудительно просим рутрекер отдавать верную кодировку
})

DOMAINS = ["https://rutracker.net", "https://rutracker.org", "https://rutracker.nl"]
BASE_URL = DOMAINS[0]

CAT_MAP = {"🎬 Кино": "7", "📺 Сериалы": "189", "🎮 Игры": "9", "📚 Книги": "10"}
MODERATORS = ["Ki_l1"]

# Глобальные хранилища данных
total_users = set()
total_requests_count = 0
referrals = {}      
user_limits = {}    
user_usage = {}     

premium_users = set()       
premium_dates = {}         
user_total_searches = {}   

# Хранилище ID сообщений для пакетной очистки интерфейса поиска
user_messages_to_delete = {}

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

# ✅ НОВЫЙ ИСПРАВЛЕННЫЙ ПАРСЕР ПОДРОБНОСТЕЙ
def parse_topic_details(tid):
    try:
        url = f"{BASE_URL}/forum/viewtopic.php?t={tid}"
        resp = r_session.get(url, timeout=20)
        
        if resp.status_code != 200:
            return None, "Не удалось загрузить страницу топика.", []
            
        resp.encoding = 'windows-1251' # Rutracker всегда в windows-1251
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 1. ПОИСК ПОСТЕРА
        img_url = None
        img_tag = soup.find('var', class_='postImg')
        if img_tag and img_tag.get('title'):
            img_url = img_tag['title']

        # 2. ИСПРАВЛЕННЫЙ ПОИСК ОПИСАНИЯ + Тех. детали
        description = "Описание релиза недоступно."
        
        # Основной пост раздачи на Rutracker лежит внутри td с class='message' и id='p-XXXXXX'
        # Нам нужен самый первый такой блок на странице
        main_post_td = soup.find('td', class_='message', id=re.compile(r'^p-\d+'))
        
        if main_post_td:
            # Делаем глубокую копию, чтобы decompose() не поломал нам комменты
            post_copy = BeautifulSoup(str(main_post_td), 'html.parser')
            
            # Удаляем мусор: тех. таблицы, спойлеры и шапки спойлеров
            for r_tag in post_copy.find_all(['table', 'div', 'fieldset'], class_=['sp-wrap', 'sp-body', 'sp-head', 'forumline', 'genmed']):
                r_tag.decompose()
            
            # Чистим текст от BB-кодов [center], [left] и тд.
            clean_raw_text = post_copy.get_text()
            clean_raw_text = re.sub(r'\[[^>]+\]', '', clean_raw_text)
            
            lines = [line.strip() for line in clean_raw_text.split('\n') if line.strip()]
            
            # Ищем технические ключи для описания
            final_desc_parts = []
            keys_to_find = ['Версия:', 'Вес:', 'Язык интерфейса:', 'Таблетка:', 'Жанр:', 'Разработчик:']
            for line in lines:
                if final_desc_parts and len(final_desc_parts) >= 6: break # Нам хватит 6 тех. деталей
                
                # Если строка начинается с одного из тех ключей, добавляем её
                if any(line.lower().startswith(k.lower()) for k in keys_to_find):
                    final_desc_parts.append(f"▪️ {line}")
            
            # Если тех. детали не нашли, пробуем взять просто первые содержательные строки
            if not final_desc_parts:
                clean_lines = [l for l in lines if len(l) > 20 and not l.startswith('[')]
                if clean_lines:
                    description = "\n".join(clean_lines[:3])[:380] + "..."
            else:
                description = "\n".join(final_desc_parts)

        # 3. ИСПРАВЛЕННЫЙ ПОИСК КОММЕНТАРИЕВ
        comments = []
        posts_tds = soup.find_all('td', class_='message', id=re.compile(r'^p-\d+'))
        
        # Если комментарии есть (len > 1), пропускаем шапку раздачи (posts[0])
        if posts_tds and len(posts_tds) > 1:
            for post_td in posts_tds[1:]: 
                # Удаляем цитаты других пользователей
                for quote in post_td.find_all('table', class_='forumline'):
                    quote.decompose()
                # Удаляем спойлеры внутри комментов
                for spoiler in post_td.find_all('div', class_='sp-wrap'):
                    spoiler.decompose()
                    
                text = post_td.get_text(strip=True)
                # Чистим от BB-кодов
                text = re.sub(r'\[[^>]+\]', '', text)
                
                # Игнорируем совсем короткие комменты ("спасибо" и тд)
                if text and len(text) > 20:
                    clean_text = " ".join(text.split())
                    comments.append(clean_text[:250])
                    
                # Хватит 10 комментов для ИИ
                if len(comments) >= 10: break

        return img_url, description, comments
        
    except Exception as e:
        print(f"❌ Ошибка парсинга топика {tid}: {e}")
        return None, "Внутренняя ошибка разбора топика.", []

def get_ai_summary(comments):
    if not ai_client or not comments:
        return "Отзывы к релизу отсутствуют или в ветке пока нет обсуждений."
    
    raw_text = "\n".join([f"- {c}" for c in comments])
    prompt = (
        "Ты — технический ассистент торрент-бота Torrent Archive. Твоя задача — прочитать отзывы пользователей "
        "и составить ультра-краткое резюме (максимум 2 предложения).\n"
        "Напиши четко: рабочая ли раздача, какое качество, нет ли вирусов или вылетов на Windows 11.\n"
        "Пиши сразу суть, без вводных фраз.\n\n"
        f"Вот комментарии:\n{raw_text}"
    )
    try:
        response = ai_client.models.generate_content(model='gemini-1.5-flash', contents=prompt)
        result = response.text.strip()
        return result if result else "Не удалось сформировать однозначный вердикт."
    except Exception as e: 
        print(f"Ошибка Gemini API: {e}")
        return "Не удалось сгенерировать вердикт ИИ."

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
    
    try: bot.set_chat_menu_button(m.chat.id, types.MenuButtonDefault())
    except: pass
        
    args = m.text.split()
    if len(args) > 1 and args[1].startswith('ref'):
        try:
            referrer_id = int(args[1].replace('ref', ''))
            if referrer_id != m.chat.id:
                if referrer_id not in referrals: referrals[referrer_id] = []
                if m.chat.id not in referrals[referrer_id]:
                    referrals[referrer_id].append(m.chat.id)
                    user_limits[referrer_id] = user_limits.get(referrer_id, 3) + 2
                    try: bot.send_message(referrer_id, f"🎉 Новый реферал! Лимит увеличен на +2 запроса.")
                    except: pass
        except: pass

    welcome_text = (
        "🛸 <b>Torrent Archive активен</b>\n\n"
        "Я нахожу, индексирую и отдаю торрент-файлы любых мировых релизов напрямую в чат.\n\n"
        "⚡️ <i>Используй интерактивное меню ниже для управления.</i>"
    )
    if check_moderator(m.from_user):
        welcome_text += "\n\n👑 <b>Обнаружен статус модератора. Полный безлимит включен.</b>"
        
    bot.send_message(m.chat.id, welcome_text, reply_markup=get_main_keyboard(), parse_mode="HTML")

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
    msg = bot.send_message(m.chat.id, "📂 Выберите категорию:", reply_markup=kb)
    register_msg_for_deletion(m.chat.id, msg.message_id)

@bot.message_handler(func=lambda m: m.text == '👥 Рефералы и Лимиты')
def show_ref(m):
    clear_previous_interface_messages(m.chat.id)
    bot_info = bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref{m.chat.id}"
    invited = len(referrals.get(m.chat.id, []))
    status_text = "<b>∞ Безлимит</b>" if (check_moderator(m.from_user) or m.chat.id in premium_users) else f"<b>{user_usage.get(m.chat.id, 0)} из {user_limits.get(m.chat.id, 3)} запросов сегодня</b>"

    text = (
        "👥 <b>Реферальная система и Лимиты</b>\n\n"
        f"▪️ Текущий статус: {status_text}\n"
        f"▪️ Приглашено друзей: <b>{invited}</b>\n\n"
        f"🔗 Ваша реф. ссылка:\n<code>{ref_link}</code>\n\n"
        "💡 <i>Каждый друг навсегда добавляет +2 поисковых запроса к вашему суточному лимиту!</i>"
    )
    bot.send_message(m.chat.id, text, reply_markup=get_main_keyboard(), parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == '⭐ Безлимитный доступ')
def show_premium(m):
    clear_previous_interface_messages(m.chat.id)
    cid = m.chat.id
    total_searches = user_total_searches.get(cid, 0)
    kb = types.InlineKeyboardMarkup()
    
    if check_moderator(m.from_user) or cid in premium_users:
        sub_text = "👑 <b>Статус: Вечный безлимит</b>\n" if check_moderator(m.from_user) else f"⭐ <b>Статус: Подписка Активна</b>\n📅 Дата: <code>{premium_dates.get(cid, datetime.datetime.now()).strftime('%d.%m.%Y')}</code>\n"
        kb.add(types.InlineKeyboardButton("🛠 Сбросить мою подписку (Тест)", callback_data="test_drop_my_sub"))
        text = f"{sub_text}📊 Потрачено: <b>{total_searches} запросов</b>\n\n🚀 Суточные лимиты полностью сняты!"
        bot.send_message(cid, text, reply_markup=kb, parse_mode="HTML")
    else:
        kb.add(types.InlineKeyboardButton("⭐️ Оформить Premium за 25 Звезд", callback_data="buy_premium"))
        text = (
            "⭐ <b>Полный Безлимит за Telegram Stars</b>\n\n"
            "Подписка полностью отключает суточные лимиты, открывает бесконечный поиск релизов и моментальный ИИ-анализ комментариев.\n\n"
            f"📈 Твоя статистика поисков: <b>{total_searches} запросов</b>.\n"
        )
        bot.send_message(cid, text, reply_markup=kb, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text not in ['🔍 Поиск релизов', '📂 Каталог тем', '👥 Рефералы и Лимиты', '⭐ Безлимитный доступ', '🏠 Главное меню', '/start', 'Поиск', 'Каталог', 'Menu', 'Меню'])
def handle_text(m):
    global total_requests_count, user_total_searches
    if not check_and_increment_limit(m.from_user, m.chat.id):
        bot.send_message(m.chat.id, "⚠️ Суточный лимит исчерпан. Расширь его через друзей или оформи подписку.")
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
            safe_title = clean_html(item['title'])
            safe_size = clean_html(item['size'])
            text = f"▪️ <b>{safe_title}</b>\n└ 💼 Вес: <code>{safe_size}</code>"
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
            bot.send_document(cid, f, caption="✅ Файл готов.")
            clear_previous_interface_messages(cid)
        except: bot.send_message(cid, "❌ Ошибка загрузки торрента.")
    
    elif c.data.startswith('v'):
        if not check_and_increment_limit(c.from_user, cid): return
        tid = c.data[1:]
        clear_previous_interface_messages(cid)

        wait_msg = bot.send_message(cid, "⏳ <i>Загружаю карточку релиза и генерирую отзыв ИИ...</i>", parse_mode="HTML")
        img_url, description, comments = parse_topic_details(tid)
        summary = get_ai_summary(comments)
        
        try: bot.delete_message(cid, wait_msg.message_id)
        except: pass
        
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("📥 Скачать .torrent", callback_data=f"d{tid}"))
        kb.add(types.InlineKeyboardButton("👥 Рефка", callback_data="inline_ref"), types.InlineKeyboardButton("⭐️ Подписка", callback_data="inline_sub"))
        
        title_text = clean_html(c.message.text.split('\n')[0].replace('▪️ ', '')) if c.message.text else "Детали релиза"
        card_text = f"📦 <b>{title_text}</b>\n\n📋 <b>Детали релиза:</b>\n<i>{clean_html(description)}</i>\n\n🤖 <b>Вердикт ИИ по комментариям:</b>\n<blockquote>{clean_html(summary)}</blockquote>"
        
        try:
            if img_url and (img_url.startswith('http://') or img_url.startswith('https://')):
                msg = bot.send_photo(cid, img_url, caption=card_text[:1024], reply_markup=kb, parse_mode="HTML")
            else: msg = bot.send_message(cid, card_text, reply_markup=kb, parse_mode="HTML")
        except: msg = bot.send_message(cid, card_text, reply_markup=kb, parse_mode="HTML")
            
        if msg: register_msg_for_deletion(cid, msg.message_id)
            
    elif c.data in ['buy_premium', 'inline_sub']:
        if cid in premium_users:
            bot.send_message(cid, "✅ У вас уже оформлен безлимитный доступ.")
            return
        # Обновленная стоимость подписки — 25 звёзд
        stars_amount = 25 
        prices = [types.LabeledPrice(label='Премиум подписка (1 месяц)', amount=stars_amount)]
        try:
            bot.send_invoice(
                chat_id=cid, title="⭐ Безлимитный Premium",
                description="Полное снятие ограничений на поиск торрентов и генерацию вердиктов ИИ на 30 дней.",
                invoice_payload="monthly_premium_stars", provider_token="", currency="XTR", prices=prices, start_parameter="premium-stars-sub"
            )
        except Exception as e: bot.send_message(cid, f"❌ Ошибка платежной системы Stars: {e}")
        
    elif c.data == 'inline_ref':
        bot_info = bot.get_me()
        bot.send_message(cid, f"🔗 <b>Ваша реферальная ссылка:</b>\n<code>https://t.me/{bot_info.username}?start=ref{cid}</code>", parse_mode="HTML")

    elif c.data == "test_drop_my_sub":
        if cid in premium_users: premium_users.remove(cid)
        if cid in premium_dates: del premium_dates[cid]
        user_usage[cid] = 0 
        bot.send_message(cid, "🗑 <b>Твоя подписка успешно удалена для тестирования!</b>", parse_mode="HTML")
        show_premium(c.message)

@bot.pre_checkout_query_handler(func=lambda query: True)
def process_stars_pre_checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def stars_payment_success(m):
    global premium_users, premium_dates
    if m.successful_payment.invoice_payload == "monthly_premium_stars":
        premium_users.add(m.chat.id)
        premium_dates[m.chat.id] = datetime.datetime.now()
        bot.send_message(m.chat.id, "🎉 <b>Оплата Звездами успешно проведена!</b>\n\nВаш аккаунт переведен в статус <b>Premium</b> на 30 дней.", reply_markup=get_main_keyboard(), parse_mode="HTML")

if __name__ == '__main__':
    if login():
        print("🚀 Torrent Bot обновлен: парсинг топика исправлен!")
        bot.polling(none_stop=True)
