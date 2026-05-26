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
    print("❌ ОШИБКА: Не настроены обязательные секреты (Токен или логин/пароль к трекеру)!"); exit(1)

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
    """Регистрирует отправленное ботом сообщение для последующего автоматического удаления"""
    if chat_id not in user_messages_to_delete:
        user_messages_to_delete[chat_id] = []
    user_messages_to_delete[chat_id].append(message_id)

def clear_previous_interface_messages(chat_id):
    """Удаляет абсолютно все ранее зарегистрированные сообщения результатов поиска для чистоты чата"""
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
                BASE_URL = domain
                return True
        except: 
            pass
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
        else:
            return []

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
    except: 
        return []

def parse_topic_details(tid):
    """Обновленный и устойчивый к разметке парсер описания, картинок и отзывов"""
    try:
        url = f"{BASE_URL}/forum/viewtopic.php?t={tid}"
        resp = r_session.get(url, timeout=20)
        
        if resp.status_code != 200:
            return None, "Не удалось загрузить страницу топика (Ошибка соединения).", []
            
        resp.encoding = 'windows-1251'
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 1. Поиск постера/картинки (через var class="postImg")
        img_url = None
        img_tag = soup.find('var', class_='postImg')
        if img_tag and img_tag.get('title'):
            img_url = img_tag['title']

        # 2. Извлечение описания раздачи
        description = "Описание релиза недоступно."
        main_post = soup.find('span', class_='postbody')
        
        if main_post:
            post_copy = BeautifulSoup(str(main_post), 'html.parser')
            # Вырезаем технические таблицы, спойлеры и скриншоты, чтобы не засорять описание
            for r_tag in post_copy.find_all(['div', 'table'], class_=['sp-wrap', 'sp-body', 'sp-head', 'forumline']):
                r_tag.decompose()
                
            lines = [line.strip() for line in post_copy.get_text().split('\n') if line.strip()]
            valid_desc_lines = [l for l in lines if len(l) > 20 and not l.startswith('[')]
            
            if valid_desc_lines:
                description = "\n".join(valid_desc_lines[:4])[:400] + "..."
            else:
                clean_lines = [l for l in lines if not l.startswith('[')]
                if clean_lines:
                    description = "\n".join(clean_lines[:3])[:350] + "..."

        # 3. Извлечение комментариев пользователей (ячейки td с классом message)
        comments = []
        posts = soup.find_all('td', class_='message')
        
        if len(posts) > 1:
            for post in posts[1:]:  # Пропускаем нулевой пост (шапку темы)
                # Точечно вырезаем цитаты, чтобы ИИ не читал повторы
                for quote in post.find_all('table', class_='forumline'):
                    quote.decompose()
                for spoiler in post.find_all('div', class_='sp-wrap'):
                    spoiler.decompose()
                    
                text = post.get_text(strip=True)
                if text and len(text) > 15:
                    clean_comment = " ".join(text.split())
                    comments.append(clean_comment[:300])
                    
                if len(comments) >= 12: 
                    break

        return img_url, description, comments
        
    except Exception as e:
        print(f"❌ Ошибка парсинга топика {tid}: {e}")
        return None, "Произошла внутренняя ошибка при разборе страницы топика.", []

def get_ai_summary(comments):
    if not ai_client or not comments:
        return "Отзывы к релизу отсутствуют или в ветке пока нет обсуждений."
    
    raw_text = "\n".join([f"- {c}" for c in comments])
    prompt = (
        "Ты — полезный ИИ-ассистент в торрент-боте. Твоя задача — прочитать отзывы пользователей "
        "о релизе ниже и составить ультра-краткое резюме (максимум 2 предложения).\n"
        "Напиши четко: рабочая ли раздача, какое качество (звук/видео), нет ли вирусов или вылетов на Windows 11.\n"
        "Пиши сразу суть, без вводных фраз вроде 'На основе комментариев...'.\n\n"
        f"Вот комментарии пользователей:\n{raw_text}"
    )
    try:
        response = ai_client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt
        )
        result = response.text.strip()
        return result if result else "Не удалось сформировать однозначный вердикт по отзывам."
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
    if check_moderator(user_obj) or chat_id in premium_users: 
        return True
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
            if referrer_id == m.chat.id:
                bot.send_message(m.chat.id, "⚠️ Вы не можете активировать собственную реферальную ссылку.")
            else:
                if referrer_id not in referrals: referrals[referrer_id] = []
                if m.chat.id not in referrals[referrer_id]:
                    referrals[referrer_id].append(m.chat.id)
                    user_limits[referrer_id] = user_limits.get(referrer_id, 3) + 2
                    try: bot.send_message(referrer_id, f"🎉 Новый реферал! Ваш суточный лимит увеличен на +2 запроса.")
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
    
    if check_moderator(m.from_user) or m.chat.id in premium_users:
        status_text = "<b>∞ Безлимит (Модератор/Премиум)</b>"
    else:
        status_text = f"<b>{user_usage.get(m.chat.id, 0)} из {user_limits.get(m.chat.id, 3)} запросов сегодня</b>"

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
        if check_moderator(m.from_user):
            sub_info = "👑 <b>Статус: Вечный безлимит (Разработчик)</b>\n"
            days_left_text = "Дней до конца: <b>∞</b>"
        else:
            start_date = premium_dates.get(cid, datetime.datetime.now())
            end_date = start_date + datetime.timedelta(days=30)
            days_left = (end_date - datetime.datetime.now()).days
            days_left = max(0, days_left)
            
            sub_info = f"⭐ <b>Статус: Подписка Активна</b>\n" \
                       f"📅 Дата оформления: <code>{start_date.strftime('%d.%m.%Y %H:%M')}</code>\n"
            days_left_text = f"⏳ Дней до конца подписки: <b>{days_left} дней</b>"

        # Кнопка тестового сброса активной подписки для отладки
        kb.add(types.InlineKeyboardButton("🛠 Сбросить мою подписку (Тест)", callback_data="test_drop_my_sub"))

        text = (
            f"{sub_info}"
            f"📊 Потрачено лимитов (всего поисков): <b>{total_searches} запросов</b>\n"
            f"{days_left_text}\n\n"
            f"🚀 Любые суточные ограничения для тебя полностью сняты!"
        )
        bot.send_message(cid, text, reply_markup=kb, parse_mode="HTML")
    else:
        kb.add(types.InlineKeyboardButton("⭐️ Оформить Premium за 2 Звезды", callback_data="buy_premium"))
        text = (
            "⭐ <b>Полный Безлимит за Telegram Stars</b>\n\n"
            "Подписка полностью отключает суточные лимиты, открывает бесконечный поиск релизов и моментальный ИИ-анализ комментариев.\n\n"
            f"📈 Твоя текущая статистика поисков: <b>{total_searches} запросов</b> за все время.\n"
        )
        bot.send_message(cid, text, reply_markup=kb, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text not in ['🔍 Поиск релизов', '📂 Каталог тем', '👥 Рефералы и Лимиты', '⭐ Безлимитный доступ', '🏠 Главное меню', '/start', 'Поиск', 'Каталог', 'Menu', 'Меню'])
def handle_text(m):
    global total_requests_count, user_total_searches
    if not check_and_increment_limit(m.from_user, m.chat.id):
        bot.send_message(m.chat.id, "⚠️ Суточный лимит исчерпан. Расширь его через друзей или оформи подписку.")
        return

    # Чистим прошлые результаты из чата перед выводом новых
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
        if not check_and_increment_limit(c.from_user, cid):
            bot.send_message(cid, "⚠️ Лимит исчерпан.")
            return        
        
        clear_previous_interface_messages(cid)
        results = parse_rutracker(query_text=None, category_id=c.data[1:])
        if results:
            user_total_searches[cid] = user_total_searches.get(cid, 0) + 1
            for item in results:
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton("📄 Открыть карточку релиза", callback_data=f"v{item['tid']}"))
                safe_title = clean_html(item['title'])
                safe_size = clean_html(item['size'])
                text = f"▪️ <b>{safe_title}</b>\n└ 💼 Вес: <code>{safe_size}</code>"
                try: 
                    msg = bot.send_message(cid, text, reply_markup=kb, parse_mode="HTML")
                    register_msg_for_deletion(cid, msg.message_id)
                except: pass
        else:
            bot.send_message(cid, "❌ В этой категории ничего не найдено.")

    elif c.data.startswith('d'):
        tid = c.data[1:]
        try:
            r = r_session.get(f"{BASE_URL}/forum/dl.php?t={tid}", headers={'Referer': f"{BASE_URL}/forum/viewtopic.php?t={tid}"}, timeout=20)
            f = io.BytesIO(r.content); f.name = f"{tid}.torrent"
            bot.send_document(cid, f, caption="✅ Файл готов.")
            clear_previous_interface_messages(cid)
        except: 
            bot.send_message(cid, "❌ Ошибка загрузки торрента.")
    
    elif c.data.startswith('v'):
        if not check_and_increment_limit(c.from_user, cid):
            bot.send_message(cid, "⚠️ Лимит исчерпан для просмотра карточек.")
            return

        tid = c.data[1:]
        # Удаляем всю пачку сообщений поиска из чата
        clear_previous_interface_messages(cid)

        wait_msg = bot.send_message(cid, "⏳ <i>Загружаю карточку релиза и генерирую отзыв ИИ...</i>", parse_mode="HTML")
        
        img_url, description, comments = parse_topic_details(tid)
        summary = get_ai_summary(comments)
        
        try: bot.delete_message(cid, wait_msg.message_id)
        except: pass
        
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("📥 Скачать .torrent", callback_data=f"d{tid}"))
        kb.add(
            types.InlineKeyboardButton("👥 Рефка", callback_data="inline_ref"),
            types.InlineKeyboardButton("⭐️ Подписка", callback_data="inline_sub")
        )
        
        title_text = "Детали релиза"
        try:
            lines = c.message.text.split('\n')
            if lines: title_text = lines[0].replace('▪️ ', '')
        except: pass
                    
        safe_title = clean_html(title_text)
        safe_desc = clean_html(description)
        safe_summary = clean_html(summary)
        
        card_text = (
            f"📦 <b>{safe_title}</b>\n\n"
            f"📋 <b>Описание:</b>\n<i>{safe_desc}</i>\n\n"
            f"🤖 <b>Вердикт ИИ по комментариям:</b>\n"
            f"<blockquote>{safe_summary}</blockquote>"
        )
        
        try:
            if img_url and (img_url.startswith('http://') or img_url.startswith('https://')):
                msg = bot.send_photo(cid, img_url, caption=card_text[:1024], reply_markup=kb, parse_mode="HTML")
            else:
                msg = bot.send_message(cid, card_text, reply_markup=kb, parse_mode="HTML")
        except:
            msg = bot.send_message(cid, card_text, reply_markup=kb, parse_mode="HTML")
            
        if msg:
            register_msg_for_deletion(cid, msg.message_id)
            
    elif c.data in ['buy_premium', 'inline_sub']:
        if cid in premium_users:
            bot.send_message(cid, "✅ У вас уже оформлен безлимитный доступ.")
            return
            
        stars_amount = 2 
        prices = [types.LabeledPrice(label='Премиум подписка (1 месяц)', amount=stars_amount)]
        
        try:
            bot.send_invoice(
                chat_id=cid,
                title="⭐ Безлимитный Premium",
                description="Полное снятие ограничений на поиск торрентов и генерацию вердиктов ИИ на 30 дней.",
                invoice_payload="monthly_premium_stars",
                provider_token="XTR_TEST", 
                currency="XTR",    
                prices=prices,
                start_parameter="premium-stars-sub"
            )
        except Exception as e:
            bot.send_message(cid, f"❌ Ошибка платежной системы Stars: {e}")
        
    elif c.data == 'inline_ref':
        bot_info = bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref{cid}"
        bot.send_message(cid, f"🔗 <b>Ваша реферальная ссылка:</b>\n<code>{ref_link}</code>\n\nПоделитесь ей, чтобы увеличить лимиты!", parse_mode="HTML")

    elif c.data == "test_drop_my_sub":
        # Логика удаления подписки для тестов
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
    payload = m.successful_payment.invoice_payload
    if payload == "monthly_premium_stars":
        premium_users.add(m.chat.id)
        premium_dates[m.chat.id] = datetime.datetime.now()
        
        text = (
            "🎉 <b>Тестовая оплата Звездами успешно проведена!</b>\n\n"
            "Ваш аккаунт переведен в статус <b>Premium</b> в системе Torrent Archive на 30 дней. "
            "Лимиты полностью отключены. Проверить статус можно в меню «Безлимитный доступ»."
        )
        bot.send_message(m.chat.id, text, reply_markup=get_main_keyboard(), parse_mode="HTML")

if __name__ == '__main__':
    if login():
        print("🚀 Torrent Bot запущен. Сессия Rutracker активна!")
        bot.polling(none_stop=True)
