import urllib.request
import json
import xml.etree.ElementTree as ET
import os
import re
import html
import sys
import subprocess
import datetime

# Пути к файлам в рабочем пространстве
BASE_DIR = "/Users/maxtyutin/antigravity/TG каналы"
PROCESSED_FILE = os.path.join(BASE_DIR, "processed_news.txt")
ENV_FILE = os.path.join(BASE_DIR, ".env")
OUTPUT_FILE = os.path.join(BASE_DIR, "Свежие_новости.md")

# RSS-ленты мировых крипто-новостей
FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
    "Blockworks": "https://blockworks.com/feed",
    "CryptoSlate": "https://cryptoslate.com/feed",
    "Bitcoin Magazine": "https://bitcoinmagazine.com/.rss/full",
    "Bitcoin News": "https://news.bitcoin.com/feed/",
    "Crypto Briefing": "https://cryptobriefing.com/feed",
    "BeInCrypto": "https://beincrypto.com/feed",
    "NewsBTC": "https://www.newsbtc.com/feed",
    "Glassnode": "https://insights.glassnode.com/rss",
    "CryptoPanic (X / Socials)": "https://cryptopanic.com/news/rss/"
}

def load_env():
    """Загрузка переменных окружения из файла .env"""
    env = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    key, val = line.strip().split('=', 1)
                    env[key.strip()] = val.strip()
    return env

def get_processed_ids():
    """Получить список уже опубликованных новостей"""
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, 'r') as f:
            return set(line.strip() for line in f)
    return set()

def save_processed_id(news_id):
    """Сохранить ID опубликованной новости"""
    with open(PROCESSED_FILE, 'a') as f:
        f.write(f"{news_id}\n")

def extract_image_url(item, raw_item_xml):
    """Попытка извлечь URL картинки из элементов новости"""
    namespaces = {
        'media': 'http://search.yahoo.com/mrss/',
        'content': 'http://purl.org/rss/1.0/modules/content/'
    }
    
    # 1. Проверяем теги <media:content> или <media:thumbnail>
    for media_tag in ['.//media:content', './/media:thumbnail']:
        try:
            elem = item.find(media_tag, namespaces)
            if elem is not None and elem.get('url'):
                return elem.get('url')
        except Exception:
            pass

    # 2. Проверяем <enclosure>
    try:
        for enc in item.findall('enclosure'):
            enc_type = enc.get('type', '')
            if 'image' in enc_type or enc.get('url', '').split('.')[-1].lower() in ['jpg', 'jpeg', 'png', 'webp']:
                return enc.get('url')
    except Exception:
        pass

    # 3. Ищем img src в описании
    for tag_name in ['description', 'content:encoded']:
        try:
            tag_elem = item.find(tag_name, namespaces) if tag_name != 'description' else item.find('description')
            if tag_elem is not None and tag_elem.text:
                img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', tag_elem.text)
                if img_match:
                    return img_match.group(1)
        except Exception:
            pass

    # 4. Фолбек: регулярное выражение по сырому XML
    urls = re.findall(r'https?://[^\s"\']+\.(?:jpg|jpeg|png|webp)', raw_item_xml)
    if urls:
        for u in urls:
            if 'logo' not in u.lower() and 'avatar' not in u.lower():
                return html.unescape(u)
                
    return None

def fetch_rss_news():
    """Загрузка и парсинг последних новостей из RSS-лент"""
    news_items = []
    processed_ids = get_processed_ids()
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    for source, url in FEEDS.items():
        print(f"Загрузка ленты {source}...")
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()
            
            # Попытка парсинга стандартным XML-парсером
            try:
                root = ET.fromstring(xml_data)
                items = root.findall('.//item')[:5]
                is_xml = True
            except Exception as xml_err:
                print(f"Предупреждение: стандартный XML-парсер не справился с {source} ({xml_err}). Используем regex-фолбек.")
                is_xml = False
            
            if is_xml:
                for item in items:
                    title = item.find('title').text if item.find('title') is not None else ""
                    link = item.find('link').text if item.find('link') is not None else ""
                    desc = item.find('description').text if item.find('description') is not None else ""
                    
                    # Чистим описание от HTML-тегов
                    desc_clean = re.sub(r'<[^>]*>', '', desc)
                    desc_clean = html.unescape(desc_clean).strip()
                    
                    try:
                        raw_xml = ET.tostring(item, encoding='utf-8').decode('utf-8')
                    except Exception:
                        raw_xml = ""
                    image_url = extract_image_url(item, raw_xml)
                    
                    news_id = link if link else title
                    if news_id and news_id not in processed_ids:
                        news_items.append({
                            "id": news_id,
                            "source": source,
                            "title": title,
                            "description": desc_clean,
                            "link": link,
                            "image_url": image_url
                        })
            else:
                # Регулярные выражения для парсинга, если XML поврежден
                xml_str = xml_data.decode('utf-8', errors='ignore')
                raw_items = re.findall(r'<item>(.*?)</item>', xml_str, re.DOTALL)
                for item_str in raw_items[:5]:
                    title_match = re.search(r'<title>(.*?)</title>', item_str, re.DOTALL)
                    link_match = re.search(r'<link>(.*?)</link>', item_str, re.DOTALL)
                    desc_match = re.search(r'<description>(.*?)</description>', item_str, re.DOTALL)
                    
                    title = title_match.group(1).strip() if title_match else ""
                    link = link_match.group(1).strip() if link_match else ""
                    desc = desc_match.group(1).strip() if desc_match else ""
                    
                    # Извлекаем текст из CDATA блоков
                    for pattern in [r'<!\[CDATA\[(.*?)\]\]>', r'<!\[CDATA\[(.*)']:
                        title_c = re.search(pattern, title, re.DOTALL)
                        if title_c: title = title_c.group(1).strip()
                        link_c = re.search(pattern, link, re.DOTALL)
                        if link_c: link = link_c.group(1).strip()
                        desc_c = re.search(pattern, desc, re.DOTALL)
                        if desc_c: desc = desc_c.group(1).strip()
                    
                    desc_clean = re.sub(r'<[^>]*>', '', desc)
                    desc_clean = html.unescape(desc_clean).strip()
                    
                    # Попытка извлечь картинку из регулярного выражения
                    img_match = re.search(r'https?://[^\s"\']+\.(?:jpg|jpeg|png|webp)', item_str)
                    image_url = img_match.group(0) if img_match else None
                    
                    news_id = link if link else title
                    if news_id and news_id not in processed_ids:
                        news_items.append({
                            "id": news_id,
                            "source": source,
                            "title": title,
                            "description": desc_clean,
                            "link": link,
                            "image_url": image_url
                        })
        except Exception as e:
            print(f"Ошибка загрузки ленты {source}: {e}")
            
    return news_items

def generate_forklog_post(news_item, gemini_key):
    """Генерация Telegram-поста в стиле ForkLog с помощью Gemini API"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    
    prompt = f"""Ты — профессиональный крипто-журналист и редактор ForkLog. 
Напиши подробную, развернутую и информативную новостную статью на русском языке для публикации в Telegram-канале на основе следующего текста:
Источник: {news_item['source']}
Заголовок: {news_item['title']}
Описание: {news_item['description']}

Правила оформления поста:
1. Заголовок поста должен быть коротким, капсом (в одну строку), передавать главную суть новости и содержать релевантный эмодзи в начале. Например: "📰 BLACKROCK СКУПАЕТ ETHEREUM" или "⚖️ SEC ОШТРАФОВАЛА BINANCE".
2. Тело поста должно быть детальным и развернутым (около 150-250 слов), полностью раскрывать суть события, описывать предысторию, контекст, важные детали, мнения участников или цитаты (если есть в описании). Пиши в авторитетном, объективном журналистском стиле.
3. В конце добавь раздел "Что это значит для рынка? 🤔" с развернутым выводом в 2-3 предложения (будет ли рост, падение или это локальный шум).
4. КАТЕГОРИЧЕСКИ НЕ ИСПОЛЬЗУЙ хэштеги. В посте не должно быть никаких хэштегов (символов # с текстом).
5. Не используй markdown-разметку, кроме жирного текста (для этого используй теги <b> и </b>) и ссылок (теги <a href="..."> и </a>), так как пост отправляется через HTML-парсинг Telegram API.
6. Выводи ТОЛЬКО готовый текст поста, без каких-либо вводных слов вроде "Вот ваш пост" или кавычек.
"""

    data = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }]
    }
    
    req = urllib.request.Request(
        url, 
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            post_text = result['candidates'][0]['content']['parts'][0]['text']
            return post_text.strip()
    except Exception as e:
        print(f"Ошибка вызова Gemini API: {e}")
        return None

def send_to_telegram(post_text, bot_token, chat_id):
    """Отправка сгенерированного текстового поста в Telegram-канал"""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": post_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode('utf-8'))
            return res.get("ok", False)
    except Exception as e:
        print(f"Ошибка отправки текста в Telegram: {e}")
        return False

def send_photo_to_telegram(post_text, image_url, bot_token, chat_id):
    """Отправка поста с изображением по ссылке в Telegram-канал"""
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    
    # Ограничение Telegram на длину подписи к фото - 1024 символа
    caption = post_text
    if len(caption) > 1020:
        caption = caption[:1017] + "..."
        
    data = {
        "chat_id": chat_id,
        "photo": image_url,
        "caption": caption,
        "parse_mode": "HTML"
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode('utf-8'))
            return res.get("ok", False)
    except Exception as e:
        print(f"Ошибка отправки фото в Telegram: {e}")
        return False

TOPICS_FILE = os.path.join(BASE_DIR, "published_topics.txt")

def get_recent_topics():
    """Получить список последних 20 опубликованных тем"""
    if os.path.exists(TOPICS_FILE):
        try:
            with open(TOPICS_FILE, 'r', encoding='utf-8') as f:
                return [line.strip() for line in f if line.strip()][-20:]
        except Exception:
            return []
    return []

def save_recent_topic(topic):
    """Сохранить тему в список последних публикаций"""
    topics = get_recent_topics()
    topics.append(topic)
    try:
        with open(TOPICS_FILE, 'w', encoding='utf-8') as f:
            for t in topics[-20:]:
                f.write(f"{t}\n")
    except Exception as e:
        print(f"Ошибка сохранения темы: {e}")

def check_semantic_duplicate(news_title, news_desc, gemini_key):
    """Семантическая проверка на дубликаты через Gemini API"""
    recent_topics = get_recent_topics()
    if not recent_topics:
        return False
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    
    topics_list = "\n".join([f"- {t}" for t in recent_topics])
    
    prompt = f"""Ниже приведен список недавно опубликованных в Telegram-канале тем:
{topics_list}

Кандидат на новую публикацию:
Заголовок: {news_title}
Описание: {news_desc}

Определи, сообщает ли кандидат о том же самом событии, которое уже было опубликовано (даже если написано другими словами).
Ответь строго одним словом:
YES — если это дубликат / то же самое событие.
NO — если это новая новость о другом событии.
Выведи ТОЛЬКО это слово (YES или NO), без каких-либо дополнительных объяснений или кавычек.
"""
    data = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }]
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            answer = result['candidates'][0]['content']['parts'][0]['text'].strip().upper()
            return "YES" in answer
    except Exception as e:
        print(f"Ошибка проверки семантического дубликата: {e}")
        return False

def generate_price_digest():
    """Получение курсов с CoinGecko и генерация дайджеста цен"""
    url = 'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,binancecoin,solana,the-open-network&vs_currencies=usd&include_24hr_change=true'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        
        coins = {
            'bitcoin': ('🪙 Bitcoin', 'BTC'),
            'ethereum': ('💎 Ethereum', 'ETH'),
            'binancecoin': ('🔸 BNB', 'BNB'),
            'solana': ('☀️ Solana', 'SOL'),
            'the-open-network': ('💎 TON', 'TON')
        }
        
        lines = ["📊 <b>РЫНОЧНЫЙ ДАЙДЖЕСТ FORKLOG STYLE</b>\n", "Курсы основных криптоактивов и их изменение за 24 часа:\n"]
        
        for coin_id, (name, symbol) in coins.items():
            if coin_id in data:
                price = data[coin_id]['usd']
                change = data[coin_id]['usd_24h_change'] or 0.0
                
                if price >= 1000:
                    price_str = f"${price:,.0f}"
                elif price >= 1:
                    price_str = f"${price:,.2f}"
                else:
                    price_str = f"${price:,.4f}"
                    
                emoji = "🟢" if change >= 0 else "🔴"
                sign = "+" if change >= 0 else ""
                
                lines.append(f"{name} ({symbol}): <b>{price_str}</b> ({emoji} {sign}{change:.2f}%)")
                
        lines.append("\n#дайджест #курсы #аналитика #рынок")
        return "\n".join(lines)
    except Exception as e:
        print(f"Ошибка генерации дайджеста цен: {e}")
        return None

def generate_and_send_poll(gemini_key, bot_token, chat_id):
    """Генерация опроса через Gemini на основе последних новостей и отправка его"""
    news_list = fetch_rss_news()
    if not news_list:
        print("Не удалось получить новости для создания опроса.")
        return False
        
    titles = "\n".join([f"- {n['title']}" for n in news_list[:5]])
    
    prompt = f"""Ты — редактор ForkLog. На основе последних новостей крипторынка придумай интересный опрос для Telegram-канала.
Новости:
{titles}

Опрос должен быть на тему актуального рыночного тренда или горячего спора в крипте.
Верни ответ строго в формате JSON со следующей структурой:
{{
  "question": "Текст вопроса (максимум 255 символов)?",
  "options": [
    "Вариант ответа 1 (максимум 100 символов)",
    "Вариант ответа 2",
    "Вариант ответа 3"
  ]
}}
Выведи ТОЛЬКО готовый JSON без каких-либо кавычек ```json или дополнительного текста.
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    data = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }]
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            json_text = result['candidates'][0]['content']['parts'][0]['text'].strip()
            
            # Очищаем от возможных ```json оберток
            json_text = re.sub(r'^```json\s*', '', json_text)
            json_text = re.sub(r'\s*```$', '', json_text)
            
            poll_data = json.loads(json_text)
            
            # Отправка опроса в Telegram
            poll_url = f"https://api.telegram.org/bot{bot_token}/sendPoll"
            tg_data = {
                "chat_id": chat_id,
                "question": poll_data["question"],
                "options": json.dumps(poll_data["options"]),
                "is_anonymous": False
            }
            
            poll_req = urllib.request.Request(
                poll_url,
                data=json.dumps(tg_data).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(poll_req) as r:
                res = json.loads(r.read().decode('utf-8'))
                return res.get("ok", False)
    except Exception as e:
        print(f"Ошибка генерации или отправки опроса: {e}")
        return False

def setup_cron():
    """Настройка расписания в планировщике macOS (crontab)"""
    try:
        current_cron = subprocess.check_output("crontab -l", shell=True, stderr=subprocess.DEVNULL).decode('utf-8')
    except Exception:
        current_cron = ""
        
    script_path = os.path.abspath(__file__)
    
    # 1. Задача на обычные новости каждые 3 часа
    news_job = f'0 */3 * * * /usr/bin/python3 "{script_path}" >> "{BASE_DIR}/news_engine.log" 2>&1'
    
    # 2. Задача на дайджест цен в 9:15 и 21:15 ежедневно
    digest_job = f'15 9,21 * * * /usr/bin/python3 "{script_path}" --digest >> "{BASE_DIR}/news_engine.log" 2>&1'
    
    # 3. Задача на опрос в 14:00 ежедневно
    poll_job = f'0 14 * * * /usr/bin/python3 "{script_path}" --poll >> "{BASE_DIR}/news_engine.log" 2>&1'
    
    jobs = [news_job, digest_job, poll_job]
    updated = False
    
    cron_lines = [line.strip() for line in current_cron.splitlines() if line.strip()]
    
    for job in jobs:
        # Проверяем, есть ли уже такая задача в crontab
        target_marker = job.split(' /usr/bin/python3 ')[1].split(' >> ')[0]
        if not any(target_marker in line for line in cron_lines):
            # Если передаются аргументы, ищем точное совпадение аргумента
            arg_marker = "--digest" if "--digest" in job else ("--poll" if "--poll" in job else "")
            if arg_marker:
                if not any(target_marker in line and arg_marker in line for line in cron_lines):
                    cron_lines.append(job)
                    updated = True
            else:
                # Для базового вызова проверяем, чтобы в строке не было других аргументов
                if not any(target_marker in line and ("--digest" in line or "--poll" in line) for line in cron_lines):
                    # Но убеждаемся, что самого базового вызова нет
                    if not any(target_marker in line and "--digest" not in line and "--poll" not in line for line in cron_lines):
                        cron_lines.append(job)
                        updated = True
            
    if updated:
        new_cron = "\n".join(cron_lines) + "\n"
        temp_cron_path = os.path.join(BASE_DIR, "temp_cron")
        with open(temp_cron_path, "w") as f:
            f.write(new_cron)
        subprocess.run(f"crontab \"{temp_cron_path}\" && rm \"{temp_cron_path}\"", shell=True)
        print("Расписание crontab успешно обновлено! Добавлены задачи публикации новостей (каждые 3 часа), дайджестов цен и опросов.")
    else:
        print("Задачи планировщика уже были настроены ранее.")

def main():
    env = load_env()
    gemini_key = env.get("GEMINI_API_KEY")
    bot_token = env.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID")
    
    if not gemini_key:
        print("Ошибка: В файле .env не задан GEMINI_API_KEY. Пожалуйста, укажите его.")
        return
        
    # Автоматически настраиваем планировщик crontab при запуске
    setup_cron()
    
    # Разбор аргументов командной строки
    args = sys.argv[1:]
    
    if "--digest" in args:
        print("Запуск генерации дайджеста цен...")
        digest_text = generate_price_digest()
        if digest_text:
            print("\n=== СГЕНЕРИРОВАННЫЙ ДАЙДЖЕСТ ===")
            print(digest_text)
            print("============================\n")
            if bot_token and chat_id:
                if send_to_telegram(digest_text, bot_token, chat_id):
                    print("Дайджест цен успешно опубликован в Telegram!")
                else:
                    print("Не удалось отправить дайджест в Telegram.")
            else:
                print("Параметры Telegram не настроены. Дайджест не отправлен.")
        return
        
    elif "--poll" in args:
        print("Запуск генерации опроса...")
        if bot_token and chat_id:
            if generate_and_send_poll(gemini_key, bot_token, chat_id):
                print("Интерактивный опрос успешно опубликован в Telegram!")
            else:
                print("Не удалось отправить опрос в Telegram.")
        else:
            print("Параметры Telegram не настроены. Опрос не отправлен.")
        return
        
    # Обычный режим работы — публикация новости
    news_list = fetch_rss_news()
    if not news_list:
        print("Новых новостей в лентах не найдено.")
        return
        
    print(f"Найдено новых новостей: {len(news_list)}. Ищем подходящую новость без дубликатов...")
    
    selected_item = None
    for item in news_list:
        print(f"Проверка кандидата: {item['title']}...")
        if check_semantic_duplicate(item['title'], item['description'], gemini_key):
            print("Новость определена как семантический дубликат. Пропускаем.")
            save_processed_id(item['id']) # Помечаем как обработанную, чтобы больше не проверять
            continue
        
        selected_item = item
        break
        
    if not selected_item:
        print("Все новые новости оказались семантическими дубликатами недавних публикаций.")
        return
        
    print(f"Выбрана новость: {selected_item['title']}. Генерация поста...")
    post = generate_forklog_post(selected_item, gemini_key)
    
    if post:
        print("\n=== СГЕНЕРИРОВАННЫЙ ПОСТ ===")
        print(post)
        print("============================\n")
        
        with open(OUTPUT_FILE, 'w') as f:
            f.write(f"# Свежая новость от ИИ-редактора\n\n{post}\n\n*Оригинальный источник: {selected_item['link']}*\n*Картинка: {selected_item.get('image_url', 'нет')}*")
        print(f"Пост сохранен в файл: {OUTPUT_FILE}")
        
        if bot_token and chat_id:
            print("Отправка поста в Telegram-канал...")
            success = False
            
            # Отправка с фото через скрытую HTML-ссылку (поддержка текстов до 4096 символов)
            if selected_item.get('image_url'):
                print(f"Попытка отправить пост с изображением (через превью-ссылку): {selected_item['image_url']}...")
                rich_post = f'<a href="{selected_item["image_url"]}">&#8203;</a>{post}'
                success = send_to_telegram(rich_post, bot_token, chat_id)
                if success:
                    print("Успешно опубликовано с изображением!")
                else:
                    print("Не удалось отправить с изображением через ссылку. Пробуем отправить только текст...")
            
            if not success:
                if send_to_telegram(post, bot_token, chat_id):
                    print("Успешно опубликовано (только текст)!")
                    success = True
                else:
                    print("Не удалось отправить текстовый пост в Telegram. Проверьте токен и права бота.")
            
            if success:
                save_processed_id(selected_item['id'])
                save_recent_topic(selected_item['title'])
        else:
            print("Параметры Telegram не настроены в .env. Пост не отправлен.")
            save_processed_id(selected_item['id'])

if __name__ == "__main__":
    main()
