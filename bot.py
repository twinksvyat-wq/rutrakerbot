import os, telebot, requests, io, time
from bs4 import BeautifulSoup
from telebot import types

TOKEN = os.environ.get("TELEGRAM_TOKEN")
R_LOGIN = os.environ.get("RUTRACKER_LOGIN")
R_PASSWORD = os.environ.get("RUTRACKER_PASSWORD")

if not all([TOKEN, R_LOGIN, R_PASSWORD]):
    print("❌ ОШИБКА: Не настроены секреты GitHub!"); exit(1)

bot = telebot.TeleBot(TOKEN)
r_session = requests.Session()
r_session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'})

DOMAINS = ["https://rutracker.net", "https://rutracker.org", "https://rutracker.nl"]
BASE_URL = DOMAINS[0]

CAT_MAP = {"🎬 Кино": "7", "📺 Сериалы": "189", "🎮 Игры": "9", "📚 Книги": "10", "🎵 Музыка": "404"}
user_data = {}

# --- СТАТИСТИКА ---
total_users = set()
total_requests_count = 0

MINI_APP_URL = f"https://{os.environ.get('GITHUB_REPOSITORY_OWNER', 'twinksvyat-wq')}.github.io/rutrakerbot/"

def clear_old_messages(chat_id):
    if chat_id in user_data and 'msg_ids' in user_data[chat_id]:
        for mid in user_data[chat_id]['msg_ids']:
            try: bot.delete_message(chat_id, mid)
            except: pass
        user_data[chat_id]['msg_ids'] = []

def login():
    global BASE_URL
    for domain in DOMAINS:
        try:
            data = {'login_username': R_LOGIN, 'login_password': R_PASSWORD, 'login': 'Вход'}
            res = r_session.post(f"{domain}/forum/login.php", data=data, timeout=15)
            if "login_username" not in res.text and res.status_code == 200:
                BASE_URL = domain
                return True
        except: pass
    return False

def parse_rutracker(params, chat_id=None):
    try:
        resp = r_session.get(f"{BASE_URL}/forum/tracker.php", params=params, timeout=25)
        if "ddos" in resp.text.lower() or "cloudflare" in resp.text.lower() or resp.status_code in [403, 503]:
            if chat_id: bot.send_message(chat_id, "⚠️ Рутрекер включил защиту. Попробуйте позже.")
            return []
            
        resp.encoding = 'windows-1251'
        soup = BeautifulSoup(resp.text, 'html.parser')
        results = []
        for row in soup.find_all('tr'):
            links = [l for l in row.find_all('a', href=True) if "viewtopic.php?t=" in l['href']]
            if not links: continue
            title = links[0].get_text(strip=True)[:60]
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
    except:
        return []

def show_chunk(chat_id):
    state = user_data.get(chat_id)
    if not state or not state.get('res'):
        bot.send_message(chat_id, "❌ Ничего не найдено."); return
    clear_old_messages(chat_id)
    idx = state['idx']
    res_to_show = state['res'][idx:idx+5]
    new_msg_ids = []
    
    for item in res_to_show:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("📥 Скачать торрент", callback_data=f"d{item['tid']}"))
        try:
            m = bot.send_message(chat_id, f"📦 **{item['title']}**\n⚖️ Вес: `{item['size']}`", reply_markup=kb, parse_mode="Markdown")
            new_msg_ids.append(m.message_id)
            time.sleep(0.2)
        except: pass
        
    nav = types.InlineKeyboardMarkup()
    btns = []
    if idx > 0: btns.append(types.InlineKeyboardButton("⬅️ Назад", callback_data="s_p"))
    btns.append(types.InlineKeyboardButton(f"{idx+1}-{idx+len(res_to_show)} / {len(state['res'])}", callback_data="none"))
    if idx + 5 < len(state['res']): btns.append(types.InlineKeyboardButton("Вперед ➡️", callback_data="s_n"))
    nav.add(*btns)
    m_nav = bot.send_message(chat_id, "🧭 Навигация по результатам:", reply_markup=nav)
    new_msg_ids.append(m_nav.message_id)
    user_data[chat_id]['msg_ids'] = new_msg_ids

def get_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row('🔍 Поиск', '🏠 Меню', '📂 Каталог')
    kb.row(types.KeyboardButton("📱 Открыть Mini App", web_app=types.WebAppInfo(url=MINI_APP_URL)))
    return kb

@bot.message_handler(commands=['stats'])
def show_stat(m):
    text = (
        "📊 **Системная статистика:**\n\n"
        f"👥 Уникальных юзеров за сессию: `{len(total_users)}`\n"
        f"🔍 Всего запросов поиска: `{total_requests_count}`\n"
        f"🌐 Рабочий домен: `{BASE_URL.replace('https://', '')}`"
    )
    bot.send_message(m.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['start'])
@bot.message_handler(func=lambda m: m.text == '🏠 Меню')
def start_cmd(m):
    clear_old_messages(m.chat.id)
    total_users.add(m.chat.id)
    
    welcome_text = (
        "👋 **Бот Rutracker активен!**\n"
        "Создатель: @neeb_devv\n\n"
        "🛠 **Changelog:**\n"
        "• `v1.3` — Кнопка статистики убрана в скрытую команду `/stats`.\n"
        "• `v1.2` — Обычный поиск переведен на выдачу строго по 5 позиций.\n"
        "• `v1.1` — Проведены тех. работы с сервером (авто-обход блокировок).\n"
        "• `v1.0` — Релиз бота + запуск встроенного Mini App.\n\n"
        "Используй меню ниже для поиска или запуска приложения!"
    )
    bot.send_message(m.chat.id, welcome_text, reply_markup=get_kb(), parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == '🔍 Поиск')
def ask_search(m): 
    bot.send_message(m.chat.id, "Введите текст для поиска:")

@bot.message_handler(func=lambda m: m.text == '📂 Каталог')
def show_cat(m):
    kb = types.InlineKeyboardMarkup(row_width=2)
    for name, fid in CAT_MAP.items(): 
        kb.add(types.InlineKeyboardButton(name, callback_data=f"c{fid}"))
    bot.send_message(m.chat.id, "Выберите категорию для поиска:", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text not in ['🔍 Поиск', '📂 Каталог', '🏠 Меню', '/start'])
def handle_text(m):
    global total_requests_count
    total_requests_count += 1
    total_users.add(m.chat.id)
    
    status_msg = bot.send_message(m.chat.id, f"🔍 Ищу «{m.text}» на Рутрекере...")
    results = parse_rutracker({'nm': m.text}, m.chat.id)
    
    try: bot.delete_message(m.chat.id, status_msg.message_id)
    except: pass
    
    if results:
        if m.chat.id not in user_data: user_data[m.chat.id] = {'msg_ids': []}
        user_data[m.chat.id]['res'] = results
        user_data[m.chat.id]['idx'] = 0
        show_chunk(m.chat.id)
    else: 
        bot.send_message(m.chat.id, "❌ Ничего не найдено.")

@bot.callback_query_handler(func=lambda c: True)
def callbacks(c):
    cid = c.message.chat.id
    bot.answer_callback_query(c.id)
    
    if c.data.startswith('c'):
        res = parse_rutracker({'f': c.data[1:]}, cid)
        if cid not in user_data: user_data[cid] = {'msg_ids': []}
        user_data[cid]['res'] = res
        user_data[cid]['idx'] = 0
        show_chunk(cid)
    elif c.data == 's_n': 
        user_data[cid]['idx'] += 5
        show_chunk(cid)
    elif c.data == 's_p': 
        user_data[cid]['idx'] = max(0, user_data[cid]['idx'] - 5)
        show_chunk(cid)
    elif c.data.startswith('d'):
        tid = c.data[1:]
        try:
            r = r_session.get(f"{BASE_URL}/forum/dl.php?t={tid}", headers={'Referer': f"{BASE_URL}/forum/viewtopic.php?t={tid}"}, timeout=20)
            f = io.BytesIO(r.content); f.name = f"{tid}.torrent"
            bot.send_document(cid, f, caption="Файл готов ✅")
        except: 
            bot.send_message(cid, "❌ Ошибка при загрузке торрента.")

if __name__ == '__main__':
    if login():
        print("🚀 БОТ УСПЕШНО ЗАПУЩЕН!")
        bot.polling(none_stop=True)
