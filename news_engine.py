import urllib.request
import json
import xml.etree.ElementTree as ET
import os
import re
import html
import sys
import subprocess
import datetime
import time

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

GEMINI_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.0-flash",
    "gemini-3-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite"
]

def call_gemini_api(prompt, gemini_key, is_json=False):
    """Выполняет запрос к Gemini API с автоматическим переключением моделей при ошибках лимитов (429, 503)"""
    last_err = None
    for model in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
        
        data = {
            "contents": [{
                "parts": [{
                    "text": prompt
                }]
            }]
        }
        if is_json:
            data["generationConfig"] = {
                "responseMimeType": "application/json"
            }
            
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        
        print(f"Запрос к ИИ: Попытка через модель {model}...")
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                text_out = result['candidates'][0]['content']['parts'][0]['text'].strip()
                print(f"Успешный ответ получен от модели: {model}")
                return text_out
        except Exception as e:
            print(f"Модель {model} выдала ошибку: {e}. Переключаемся на резервную модель...")
            last_err = e
            time.sleep(2)
            
    print(f"Все доступные ИИ-модели вернули ошибку. Последняя ошибка: {last_err}")
    return None

def generate_forklog_post(news_item, gemini_key):
    """Генерация Telegram-поста и полной статьи для сайта с помощью Gemini API"""
    prompt = f"""Ты — профессиональный крипто-журналист и редактор Crypto Analytics. 
На основе следующей новости напиши заголовок и две версии статьи на русском языке:
Источник: {news_item['source']}
Заголовок: {news_item['title']}
Описание: {news_item['description']}

ПРАВИЛО: КАТЕГОРИЧЕСКИ запрещено использовать или упоминать название ForkLog. Пиши только от лица Crypto Analytics.
ПРАВИЛО ДЛИНЫ: Текст telegram_caption должен представлять собой краткий пересказ новости. Длина текста telegram_caption КАТЕГОРИЧЕСКИ не должна превышать 800 символов (включая пробелы). Это необходимо, чтобы весь пост вместе с автоматически добавляемой ссылкой на сайт гарантированно укладывался в лимит 1000 символов.

Верни результат СТРОГО в формате JSON с тремя следующими ключами:
{{
  "russian_title": "Привлекательный заголовок для веб-сайта на русском языке в стиле Crypto Analytics (без кликбейта, отражающий суть)",
  "telegram_caption": "Краткий пересказ новости для Telegram-канала (подпись к фото). Длина должна быть не более 800 символов (включая пробелы). Должна содержать заголовок капсом с эмодзи в начале, лаконичный разбор и вывод 'Что это значит для рынка? 🤔'. Хэштеги КАТЕГОРИЧЕСКИ запрещены. Разрешены только теги <b> и <a>.",
  "full_article": "Полная, развернутая и максимально детальная статья для веб-сайта без каких-либо сокращений (около 1500-2500 символов). Подробно опиши предысторию события, контекст, технические детали, мнения участников рынка, развернутый вывод и последствия для индустрии. Разрешены HTML-теги <b>, <a>, <i>."
}}
"""
    response_json = call_gemini_api(prompt, gemini_key, is_json=True)
    if not response_json:
        return None
        
    try:
        parsed = json.loads(response_json)
        return {
            "russian_title": parsed.get("russian_title", "").strip() or news_item['title'],
            "telegram_caption": parsed.get("telegram_caption", "").strip(),
            "full_article": parsed.get("full_article", "").strip()
        }
    except Exception as e:
        print(f"Ошибка парсинга сгенерированного JSON: {e}")
        return None

def send_to_telegram(post_text, bot_token, chat_id):
    """Отправка сгенерированного текстового поста в Telegram-канал"""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": post_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "link_preview_options": {"is_disabled": True}
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

def download_and_standardize_image(image_url, article_id):
    """Скачивает изображение, приводит его к стандарту 16:9 (1200x675) и сохраняет локально"""
    import urllib.request
    
    # Импортируем Pillow динамически
    try:
        from PIL import Image
    except ImportError:
        import subprocess
        import sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
        from PIL import Image
    
    os.makedirs(os.path.join(BASE_DIR, "images"), exist_ok=True)
    local_filename = f"article_{article_id}.jpg"
    temp_path = os.path.join(BASE_DIR, "images", f"temp_{local_filename}")
    final_path = os.path.join(BASE_DIR, "images", local_filename)
    relative_path = f"./images/{local_filename}"
    
    # 1. Скачиваем оригинальную картинку во временный файл
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        req = urllib.request.Request(image_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            with open(temp_path, 'wb') as out_file:
                out_file.write(response.read())
    except Exception as e:
        print(f"Не удалось скачать изображение по ссылке {image_url}: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return None
        
    # 2. Обрабатываем изображение с помощью Pillow
    try:
        target_width = 1200
        target_height = 675  # соотношение 16:9
        
        with Image.open(temp_path) as img:
            if img.mode != 'RGB':
                img = img.convert('RGB')
                
            img_width, img_height = img.size
            
            # Рассчитываем масштаб (ratio), чтобы полностью покрыть 1200x675
            ratio_w = target_width / img_width
            ratio_h = target_height / img_height
            ratio = max(ratio_w, ratio_h) # Берем максимум, чтобы заполнить холст
            
            new_width = int(img_width * ratio)
            new_height = int(img_height * ratio)
            
            try:
                resample_filter = Image.Resampling.LANCZOS
            except AttributeError:
                resample_filter = Image.ANTIALIAS
                
            # Изменяем размер
            resized_img = img.resize((new_width, new_height), resample_filter)
            
            # Обрезаем излишки по центру
            left = (new_width - target_width) / 2
            top = (new_height - target_height) / 2
            right = left + target_width
            bottom = top + target_height
            
            cropped_img = resized_img.crop((left, top, right, bottom))
            cropped_img.save(final_path, "JPEG", quality=90)
            
        print(f"Изображение успешно стандартизировано и сохранено в {final_path}")
        return {
            "local_path": final_path,
            "relative_url": relative_path
        }
    except Exception as e:
        print(f"Ошибка при обработке изображения PIL: {e}")
        return None
    finally:
        # Удаляем временный файл
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

def send_photo_to_telegram(post_text, image_path_or_url, bot_token, chat_id):
    """Отправка поста с изображением в Telegram-канал (поддерживает локальные файлы и URL)"""
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    
    # Импортируем requests динамически
    try:
        import requests
    except ImportError:
        import subprocess
        import sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
        import requests
        
    link_pattern = r'(\n\n👉 <a href="https://maxtyutin\.github\.io/cryptochannel/#article-[^"]+">Читать на Crypto Analytics</a>)$'
    match = re.search(link_pattern, post_text)
    
    caption = post_text
    if len(caption) > 1024:
        if match:
            link_part = match.group(1)
            text_part = post_text[:match.start()]
            max_text_len = 1024 - len(link_part)
            truncated_text = text_part[:max_text_len]
            sentence_end_match = list(re.finditer(r'[.!?]\s', truncated_text))
            if sentence_end_match:
                last_end_idx = sentence_end_match[-1].end() - 1
                caption = truncated_text[:last_end_idx].strip() + link_part
            else:
                space_match = list(re.finditer(r'\s', truncated_text))
                if space_match:
                    caption = truncated_text[:space_match[-1].start()].strip() + link_part
                else:
                    caption = truncated_text.strip() + link_part
        else:
            caption = caption[:1024]
            
    # Отправка
    try:
        if os.path.exists(image_path_or_url):
            # Если это локальный файл, загружаем как multipart/form-data
            with open(image_path_or_url, 'rb') as f:
                files = {'photo': f}
                data = {
                    "chat_id": chat_id,
                    "caption": caption,
                    "parse_mode": "HTML"
                }
                r = requests.post(url, data=data, files=files, timeout=30)
        else:
            # Если это внешняя ссылка URL
            data = {
                "chat_id": chat_id,
                "photo": image_path_or_url,
                "caption": caption,
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True}
            }
            r = requests.post(url, json=data, timeout=30)
            
        if r.status_code == 200:
            return True
        else:
            print(f"Ошибка Telegram API ({r.status_code}): {r.text}")
            return False
    except Exception as e:
        print(f"Ошибка при отправке изображения в Telegram: {e}")
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

def save_article_to_json(news_item, post_text, russian_title=None):
    """Сохраняет опубликованную новость в файл articles.json для веб-сайта"""
    json_path = os.path.join(BASE_DIR, "articles.json")
    articles = []
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                articles = json.load(f)
        except Exception:
            articles = []
            
    # Формируем структуру новости для сайта
    article_data = {
        "id": news_item['id'],
        "title": russian_title if russian_title else news_item['title'],
        "source": news_item['source'],
        "link": news_item['link'],
        "image_url": news_item.get('image_url', ''),
        "post_text": post_text,
        "date": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
        "timestamp": int(time.time())
    }
    
    # Избегаем дублирования по ID
    if any(a['id'] == news_item['id'] for a in articles):
        return
        
    articles.insert(0, article_data)
    articles = articles[:100]  # Храним последние 100 новостей
    
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        print("Статья сохранена в articles.json для сайта!")
    except Exception as e:
        print(f"Ошибка сохранения статьи в JSON: {e}")

def check_semantic_duplicate(news_title, news_desc, gemini_key):
    """Семантическая проверка на дубликаты через Gemini API"""
    recent_topics = get_recent_topics()
    if not recent_topics:
        return False
        
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
    answer = call_gemini_api(prompt, gemini_key)
    if not answer:
        return False
        
    return "YES" in answer.upper()

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
        
        lines = ["📊 <b>РЫНОЧНЫЙ ДАЙДЖЕСТ CRYPTO ANALYTICS</b>\n", "Курсы основных криптоактивов и их изменение за 24 часа:\n"]
        
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
    
    prompt = f"""Ты — редактор Crypto Analytics. На основе последних новостей крипторынка придумай интересный опрос для Telegram-канала.
Новости:
{titles}

ПРАВИЛО: КАТЕГОРИЧЕСКИ запрещено использовать или упоминать название ForkLog. Пиши только от лица Crypto Analytics.

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
    try:
        json_text = call_gemini_api(prompt, gemini_key, is_json=True)
        if not json_text:
            return False
            
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
    post_data = generate_forklog_post(selected_item, gemini_key)
    
    if post_data:
        telegram_caption = post_data["telegram_caption"]
        full_article = post_data["full_article"]
        russian_title = post_data["russian_title"]
        
        # Добавляем ссылку на полный обзор статьи на сайте
        article_url = f"https://maxtyutin.github.io/cryptochannel/#article-{selected_item['id']}"
        telegram_caption += f"\n\n👉 <a href=\"{article_url}\">Читать на Crypto Analytics</a>"
        
        print("\n=== СГЕНЕРИРОВАННЫЙ ПОСТ (TG) ===")
        print(telegram_caption)
        print("\n=== СГЕНЕРИРОВАННАЯ СТАТЬЯ (САЙТ) ===")
        print(full_article)
        print("============================\n")
        
        with open(OUTPUT_FILE, 'w') as f:
            f.write(f"# Свежая новость от ИИ-редактора\n\n## ДЛЯ TELEGRAM:\n{telegram_caption}\n\n## ДЛЯ САЙТА:\n{full_article}\n\n*Оригинальный источник: {selected_item['link']}*\n*Картинка: {selected_item.get('image_url', 'нет')}*")
        print(f"Пост сохранен в файл: {OUTPUT_FILE}")
        
        # Скачиваем и стандартизируем изображение, если оно есть
        local_img_path = None
        if selected_item.get('image_url'):
            print(f"Скачивание и обработка изображения: {selected_item['image_url']}...")
            img_result = download_and_standardize_image(selected_item['image_url'], selected_item['id'])
            if img_result:
                local_img_path = img_result["local_path"]
                # Обновляем ссылку в объекте новости для сайта, чтобы вела на локальную версию
                selected_item['image_url'] = img_result["relative_url"]
                print(f"Ссылка на картинку обновлена на локальную: {selected_item['image_url']}")

        if bot_token and chat_id:
            print("Отправка поста в Telegram-канал...")
            success = False
            
            # Отправка полноценного фото-поста в Telegram (фото сверху, текст в подписи)
            if local_img_path:
                print(f"Отправка локально обработанного изображения: {local_img_path}...")
                success = send_photo_to_telegram(telegram_caption, local_img_path, bot_token, chat_id)
                if success:
                    print("Успешно опубликовано со стандартизированным изображением!")
                else:
                    print("Не удалось отправить фото-пост с обработанной картинкой. Пробуем исходную...")
            
            if not success and selected_item.get('image_url') and not selected_item['image_url'].startswith('./'):
                print(f"Попытка отправить пост с оригинальным URL: {selected_item['image_url']}...")
                success = send_photo_to_telegram(telegram_caption, selected_item['image_url'], bot_token, chat_id)
                if success:
                    print("Успешно опубликовано с изображением по внешней ссылке!")
            
            if not success:
                if send_to_telegram(telegram_caption, bot_token, chat_id):
                    print("Успешно опубликовано (только текст)!")
                    success = True
                else:
                    print("Не удалось отправить текстовый пост в Telegram. Проверьте токен и права бота.")
            
            if success:
                save_processed_id(selected_item['id'])
                save_recent_topic(selected_item['title'])
                save_article_to_json(selected_item, full_article, russian_title)
        else:
            print("Параметры Telegram не настроены в .env. Пост не отправлен.")
            save_processed_id(selected_item['id'])
            save_article_to_json(selected_item, full_article, russian_title)

if __name__ == "__main__":
    main()
