import os, telebot, requests, io, time, html, re
from bs4 import BeautifulSoup
from telebot import types
from google import genai

TOKEN = os.environ.get("TELEGRAM_TOKEN")
R_LOGIN = os.environ.get("RUTRACKER_LOGIN")
R_PASSWORD = os.environ.get("RUTRACKER_PASSWORD")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

if not all([TOKEN, R_LOGIN, R_PASSWORD]):
    print("❌ ОШИБКА: Не настроены секреты GitHub!"); exit(1)

# Инициализация нового актуального клиента Google GenAI
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

user_data = {}
total_users = set()
total_requests_count = 0
referrals = {}      
user_limits = {}    
user_usage = {}     
premium_users = set() 

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

def parse_rutracker(params, chat_id=None):
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
        return unique
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
        # Использование нового метода генерации контента для google-genai SDK
        response = ai_client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt + "\n\nВот комментарии:\n" + raw_text
        )
        return response.text.strip()
    except: return "Не удалось сгенерировать вердикт ИИ."

def show_chunk(chat_id):
    state = user_data.get(chat_id)
    if not state or not state.get('res'): return
    
    if 'msg_ids' in state:
        for mid in state['msg_ids']:
            try: bot.delete_message(chat_id, mid)
            except: pass
            
    idx = state['idx']
    res_to_show = state['res'][idx:idx+5]
    new_msg_ids = []
    
    for item in res_to_show:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("📄 Открыть карточку релиза", callback_data=f"v{item['tid']}"))
        safe_title = clean_html(item['title'])
        safe_size = clean_html(item['size'])
        text = f"▪️ <b>{safe_title}</b>\n└ 💼 Вес: <code>{safe_size}</code>"
        try:
            m = bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")
            new_msg_ids.append(m.message_id)
            time.sleep(0.1)
        except: pass
        
    nav = types.InlineKeyboardMarkup()
    btns = []
    if idx > 0: btns.append(types.InlineKeyboardButton("⬅️ Назад", callback_data="s_p"))
    btns.append(types.InlineKeyboardButton(f"Стр. {int(idx/5)+1}", callback_data="none"))
    if idx + 5 < len(state['res']): btns.append(types.InlineKeyboardButton("Вперед ➡️", callback_data="s_n"))
    nav.add(*btns)
    
    m_nav = bot.send_message(chat_id, "<b>Навигация по страницам:</b>", reply_markup=nav, parse_mode="HTML")
    new_msg_ids.append(m_nav.message_id)
    user_data[chat_id]['msg_ids'] = new_msg_ids

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
        "🛸 <b>Сетевой Поисковый Бот активен</b>\n\n"
        "Я нахожу, фильтрую и отдаю торрент-файлы любых мировых релизов напрямую в чат.\n\n"
        "⚡️ <i>Используй кнопки нижнего меню для управления.</i>"
    )
    if check_moderator(m.from_user):
        welcome_text += "\n\n👑 <b>Обнаружен статус модератора. Лимиты отключены полностью.</b>"
        
    bot.send_message(m.chat.id, welcome_text, reply_markup=get_main_keyboard(), parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == '🔴 Главное меню')
def menu_redirect(m): start_cmd(m)

@bot.message_handler(func=lambda m: m.text == '🟢 Поиск релизов')
def ask_search(m): bot.send_message(m.chat.id, "✏️ Введи название релиза для поиска:")

@bot.message_handler(func=lambda m: m.text == '🟢 Каталог тем')
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
    bot.send_message(m.chat.id, text, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == '🔵 Безлимитный доступ')
def show_premium(m):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("💳 Оформить подписку за 49₽", callback_data="buy_premium"))
    text = (
        "⭐ <b>Полный Безлимит</b>\n\n"
        "Всего за <b>49 рублей в месяц</b> подписка полностью снимает любые ограничения на поиск релизов.\n"
    )
    bot.send_message(m.chat.id, text, reply_markup=kb, parse_mode="HTML")

@bot.message_handler(commands=['stats'])
def show_stat(m):
    text = (
        "📊 <b>Системная статистика ядра:</b>\n\n"
        f"• Активных сессий: <code>{len(total_users)}</code>\n"
        f"• Премиум-аккаунтов: <code>{len(premium_users)}</code>\n"
        f"• Обработано поисковых индексов: <code>{total_requests_count}</code>\n"
        f"• Базовый шлюз парсинга: <code>{BASE_URL.replace('https://', '')} (Rutracker)</code>"
    )
    bot.send_message(m.chat.id, text, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text not in ['🟢 Поиск релизов', '🟢 Каталог тем', '🔵 Рефералы и Лимиты', '🔵 Безлимитный доступ', '🔴 Главное меню', '/start'])
def handle_text(m):
    global total_requests_count
    if not check_and_increment_limit(m.from_user, m.chat.id):
        bot.send_message(m.chat.id, "⚠️ Суточный лимит исчерпан. Расширь его через друзей или оформи подписку.")
        return

    total_requests_count += 1
    status_msg = bot.send_message(m.chat.id, "🔎 Сверяю индексы базы данных...")
    results = parse_rutracker({'nm': m.text})
    
    try: bot.delete_message(m.chat.id, status_msg.message_id)
    except: pass
    
    if results:
        user_data[m.chat.id] = {'res': results, 'idx': 0, 'msg_ids': []}
        show_chunk(m.chat.id)
    else:
        bot.send_message(m.chat.id, "❌ По данному запросу ничего не найдено.")

@bot.callback_query_handler(func=lambda c: True)
def callbacks(c):
    cid = c.message.chat.id
    bot.answer_callback_query(c.id)
    
    if c.data.startswith('c'):
        if not check_and_increment_limit(c.from_user, cid):
            bot.send_message(cid, "⚠️ Лимит исчерпан.")
            return        
        res = parse_rutracker({'f': c.data[1:]})
        user_data[cid] = {'res': res, 'idx': 0, 'msg_ids': []}
        show_chunk(cid)
    elif c.data == 's_n': 
        user_data[cid]['idx'] += 5; show_chunk(cid)
    elif c.data == 's_p': 
        user_data[cid]['idx'] = max(0, user_data[cid]['idx'] - 5); show_chunk(cid)
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
            types.InlineKeyboardButton("⭐ Подписка", callback_data="inline_sub")
        )
        
        title_text = "Детали релиза"
        if cid in user_data and 'res' in user_data[cid]:
            for item in user_data[cid]['res']:
                if item['tid'] == tid:
                    title_text = item['title']
                    break
                    
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
        except Exception as e:
            bot.send_message(cid, card_text, reply_markup=kb, parse_mode="HTML")
            
    elif c.data == 'buy_premium' or c.data == 'inline_sub':
        premium_users.add(cid)
        bot.send_message(cid, "🎉 Подписка успешно оформлена! Лимиты сняты полностью.")
        
    elif c.data == 'inline_ref':
        bot_info = bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref{cid}"
        bot.send_message(cid, f"🔗 <b>Ваша реферальная ссылка:</b>\n<code>{ref_link}</code>\n\nПоделитесь ей, чтобы увеличить лимиты!", parse_mode="HTML")

if __name__ == '__main__':
    if login():
        print("🚀 БОТ УСПЕШНО ОБНОВЛЕН И ЗАПУЩЕН!")
        bot.polling(none_stop=True)
