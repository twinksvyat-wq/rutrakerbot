import os, telebot, requests, io, html, re, datetime
from bs4 import BeautifulSoup
from telebot import types
from google import genai

TOKEN = os.environ.get("TELEGRAM_TOKEN")
R_LOGIN = os.environ.get("RUTRACKER_LOGIN")
R_PASSWORD = os.environ.get("RUTRACKER_PASSWORD")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

if not all([TOKEN, R_LOGIN, R_PASSWORD]):
    print("❌ ОШИБКА: Не настроены секреты GitHub!"); exit(1)

if GEMINI_KEY:
    ai_client = genai.Client(api_key=GEMINI_KEY)
else:
    ai_client = None

bot = telebot.TeleBot(TOKEN)
r_session = requests.Session()
r_session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'})

DOMAINS = ["https://rutracker.net", "https://rutracker.org", "https://rutracker.nl"]
BASE_URL = DOMAINS[0]

CAT_MAP = {"🎬 Кино": "7", "📺 Сериалы": "189", "🎮 Игры": "9", "📚 Книги": "10"}

# Твой ник для вечного безлимита
MODERATORS = ["Ki_l1"]

total_users = set()
total_requests_count = 0
referrals = {}      
user_limits = {}    
user_usage = {}     

# Статистика лимитов и дат для подписок
premium_users = set()       
premium_dates = {}         
user_total_searches = {}   

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

def parse_rutracker(params):
    try:
        resp = r_session.get(f"{BASE_URL}/forum/tracker.php", params=params, timeout=25)
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
            if r['tid'] not in seen: unique.append(r); seen.add(r['tid'])
        return unique[:10]
    except: return []

def parse_topic_details(tid):
    try:
        resp = r_session.get(f"{BASE_URL}/forum/viewtopic.php?t={tid}", timeout=15)
        resp.encoding = 'windows-1251'
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        img_url = None
        main_post = soup.find('span', class_='postbody')
        if main_post:
            img_tag = main_post.find('var', class_='postImg')
            if img_tag and img_tag.get('title'):
                img_url = img_tag['title']
        
        description = "Описание релиза недоступно."
        if main_post:
            lines = [line.strip() for line in main_post.get_text().split('\n') if line.strip()]
            valid_lines = [l for l in lines if not l.startswith('[') and len(l) > 10]
            if valid_lines:
                description = "\n".join(valid_lines[:3])[:350] + "..."

        comments = []
        for post in soup.find_all('span', class_='postbody')[1:]: 
            text = post.get_text(strip=True)
            if text and len(text) > 10: comments.append(text[:200])
            if len(comments) >= 20: break
            
        return img_url, description, comments
    except:
        return None, "Не удалось загрузить данные топика.", []

def get_ai_summary(comments):
    if not ai_client or not comments:
        return "Отзывы к релизу отсутствуют или в ветке пока нет обсуждений."
    raw_text = "\n--- Отзыв ---\n".join(comments)
    prompt = (
        "Ты — технический ассистент торрент-бота. Проанализируй комментарии пользователей к раздаче. "
        "Выдай краткий жесткий вердикт (строго до 2 предложений). Напиши, стабилен ли релиз, "
        "нет ли проблем со звуком, багов или проблем на Windows 11. Пиши без приветствий, сразу суть."
    )
    try:
        response = ai_client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt + "\n\nВот комментарии:\n" + raw_text
        )
        return response.text.strip()
    except: return "Не удалось сгенерировать вердикт ИИ."

def get_main_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row('🟢 Поиск релизов', '🟢 Каталог тем')
    kb.row('🔵 Рефералы и Лимиты', '🔵 Безлимитный доступ')
    kb.row('🔴 Главное меню')
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
                    try: bot.send_message(referrer_id, f"🎉 Новый реферал! Ваш суточный лимит увеличен на +2 запроса.")
                    except: pass
        except: pass

    welcome_text = (
        "🛸 <b>Torrent Archive активен</b>\n\n"
        "Я нахожу, индексирую и отдаю торрент-файлы любых мировых релизов напрямую в чат.\n\n"
        "⚡️ <i>Используй цветное меню ниже для управления.</i>"
    )
    if check_moderator(m.from_user):
        welcome_text += "\n\n👑 <b>Обнаружен статус модератора. Полный безлимит включен.</b>"
        
    bot.send_message(m.chat.id, welcome_text, reply_markup=get_main_keyboard(), parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text in ['🔴 Главное меню', 'Меню', '/menu'])
def menu_redirect(m): start_cmd(m)

@bot.message_handler(func=lambda m: m.text in ['🟢 Поиск релизов', 'Поиск'])
def ask_search(m): bot.send_message(m.chat.id, "✏️ Введи название релиза для поиска в архиве:", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda m: m.text in ['🟢 Каталог тем', 'Каталог'])
def show_cat(m):
    kb = types.InlineKeyboardMarkup(row_width=2)
    for name, fid in CAT_MAP.items(): kb.add(types.InlineKeyboardButton(name, callback_data=f"c{fid}"))
    bot.send_message(m.chat.id, "📂 Выберите категорию:", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == '🔵 Рефералы и Лимиты')
def show_ref(m):
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

@bot.message_handler(func=lambda m: m.text == '🔵 Безлимитный доступ')
def show_premium(m):
    cid = m.chat.id
    total_searches = user_total_searches.get(cid, 0)
    
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

        text = (
            f"{sub_info}"
            f"📊 Потрачено лимитов (всего поисков): <b>{total_searches} запросов</b>\n"
            f"{days_left_text}\n\n"
            f"🚀 Любые суточные ограничения для тебя полностью сняты!"
        )
        bot.send_message(cid, text, reply_markup=get_main_keyboard(), parse_mode="HTML")
    else:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⭐️ Оформить Premium за 2 Звезды", callback_data="buy_premium"))
        text = (
            "⭐ <b>Полный Безлимит за Telegram Stars</b>\n\n"
            "Подписка полностью отключает суточные лимиты, открывает бесконечный поиск релизов и моментальный ИИ-анализ комментариев.\n\n"
            f"📈 Твоя текущая статистика поисков: <b>{total_searches} запросов</b> за все время.\n"
        )
        bot.send_message(cid, text, reply_markup=kb, parse_mode="HTML")

@bot.message_handler(commands=['stats'])
def show_stat(m):
    text = (
        "📊 <b>Системная статистика ядра Torrent Archive:</b>\n\n"
        f"• Активных сессий: <code>{len(total_users)}</code>\n"
        f"• Премиум-аккаунтов: <code>{len(premium_users)}</code>\n"
        f"• Обработано поисковых индексов: <code>{total_requests_count}</code>\n"
        f"• Базовый шлюз парсинга: <code>{BASE_URL.replace('https://', '')} (Rutracker)</code>"
    )
    bot.send_message(m.chat.id, text, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text not in ['🟢 Поиск релизов', '🟢 Каталог тем', '🔵 Рефералы и Лимиты', '🔵 Безлимитный доступ', '🔴 Главное меню', '/start', 'Поиск', 'Каталог', 'Menu', 'Меню'])
def handle_text(m):
    global total_requests_count, user_total_searches
    if not check_and_increment_limit(m.from_user, m.chat.id):
        bot.send_message(m.chat.id, "⚠️ Суточный лимит исчерпан. Расширь его через друзей или оформи подписку.")
        return

    total_requests_count += 1
    user_total_searches[m.chat.id] = user_total_searches.get(m.chat.id, 0) + 1
    
    status_msg = bot.send_message(m.chat.id, "🔎 Сверяю индексы базы данных...")
    results = parse_rutracker({'nm': m.text})
    
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
                bot.send_message(m.chat.id, text, reply_markup=kb, parse_mode="HTML")
            except: pass
    else:
        bot.send_message(m.chat.id, "❌ По данному запросу ничего не найдено.", reply_markup=get_main_keyboard())

@bot.callback_query_handler(func=lambda c: True)
def callbacks(c):
    global user_total_searches
    cid = c.message.chat.id
    bot.answer_callback_query(c.id)
    
    if c.data.startswith('c'):
        if not check_and_increment_limit(c.from_user, cid):
            bot.send_message(cid, "⚠️ Лимит исчерпан.")
            return        
        results = parse_rutracker({'f': c.data[1:]})
        if results:
            user_total_searches[cid] = user_total_searches.get(cid, 0) + 1
            for item in results:
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton("📄 Открыть карточку релиза", callback_data=f"v{item['tid']}"))
                safe_title = clean_html(item['title'])
                safe_size = clean_html(item['size'])
                text = f"▪️ <b>{safe_title}</b>\n└ 💼 Вес: <code>{safe_size}</code>"
                try: bot.send_message(cid, text, reply_markup=kb, parse_mode="HTML")
                except: pass
        else:
            bot.send_message(cid, "❌ В этой категории ничего не найдено.")

    elif c.data.startswith('d'):
        tid = c.data[1:]
        try:
            r = r_session.get(f"{BASE_URL}/forum/dl.php?t={tid}", headers={'Referer': f"{BASE_URL}/forum/viewtopic.php?t={tid}"}, timeout=20)
            f = io.BytesIO(r.content); f.name = f"{tid}.torrent"
            bot.send_document(cid, f, caption="✅ Файл готов.")
        except: bot.send_message(cid, "❌ Ошибка загрузки торрента.")
    
    elif c.data.startswith('v'):
        if not check_and_increment_limit(c.from_user, cid):
            bot.send_message(cid, "⚠️ Лимит исчерпан для просмотра карточек.")
            return

        tid = c.data[1:]
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
                bot.send_photo(cid, img_url, caption=card_text[:1024], reply_markup=kb, parse_mode="HTML")
            else:
                bot.send_message(cid, card_text, reply_markup=kb, parse_mode="HTML")
        except:
            bot.send_message(cid, card_text, reply_markup=kb, parse_mode="HTML")
            
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

# --- СЛУЖЕБНЫЕ ХЭНДЛЕРЫ ОБРАБОТКИ ПЛАТЕЖЕЙ STARS ---

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
        print("🚀 TORRENT ARCHIVE УСПЕШНО ЗАПУЩЕН НА БАЗЕ STARS!")
        bot.polling(none_stop=True)
