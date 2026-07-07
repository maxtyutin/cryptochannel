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
    """Получить список уже опубликованных новостей (из файла + из articles.json для надёжности)"""
    ids = set()
    # 1. Читаем файл processed_news.txt
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, 'r') as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    ids.add(stripped)
    # 2. Дополнительно читаем articles.json — защита от потери processed_news.txt при ручной загрузке
    json_path = os.path.join(BASE_DIR, "articles.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                articles = json.load(f)
            for a in articles:
                if a.get('id'):
                    ids.add(a['id'])
        except Exception:
            pass
    return ids

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

def fetch_article_images(article_url, primary_image_url=None):
    """Скачивает страницу источника и извлекает все дополнительные изображения статьи.
    Возвращает список URL картинок (без дублей, без логотипов/иконок).
    """
    if not article_url or not article_url.startswith('http'):
        return []

    SKIP_KEYWORDS = ['logo', 'avatar', 'icon', 'badge', 'sprite', 'banner-ad',
                     'tracking', 'subscribe', 'newsletter', 'author', 'profile', 'gravatar']
    try:
        ua = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        req = urllib.request.Request(article_url, headers={'User-Agent': ua})
        with urllib.request.urlopen(req, timeout=10) as resp:
            page_html = resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Не удалось скачать страницу для поиска доп. изображений: {e}")
        return []

    found_urls = []
    seen = set()
    if primary_image_url:
        seen.add(primary_image_url.split('?')[0])

    def add_url(u):
        u = u.strip().split('?')[0]
        if not u.startswith('http'):
            return
        if u in seen:
            return
        u_lower = u.lower()
        if any(kw in u_lower for kw in SKIP_KEYWORDS):
            return
        has_ext = any(u_lower.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp'])
        has_keyword = any(kw in u_lower for kw in ['image', 'photo', 'img', 'media', 'upload'])
        if not has_ext and not has_keyword:
            return
        seen.add(u)
        found_urls.append(u)

    # 1. og:image meta-тег
    for m in re.finditer(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', page_html, re.IGNORECASE):
        add_url(html.unescape(m.group(1)))
    for m in re.finditer(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', page_html, re.IGNORECASE):
        add_url(html.unescape(m.group(1)))

    # 2. <img> внутри article/main блоков
    blocks = re.findall(r'<(?:article|main)[^>]*>(.*?)</(?:article|main)>', page_html, re.DOTALL | re.IGNORECASE)
    if not blocks:
        blocks = [page_html]
    for block in blocks:
        for m in re.finditer(r'<img[^>]+(?:src|data-src)=["\']([^"\']+)["\']', block, re.IGNORECASE):
            add_url(html.unescape(m.group(1)))
        for m in re.finditer(r'srcset=["\']([^"\']+)', block, re.IGNORECASE):
            first = m.group(1).split(',')[0].strip().split()[0]
            add_url(html.unescape(first))

    return found_urls[:4]

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
ПРАВИЛО ИСТОЧНИКОВ: В качестве авторитетных источников данных, ончейн-метрик или финансирования старайся ссылаться на такие платформы как The Block и Allium (например, 'по данным отчетов Allium...', 'согласно информации The Block...').
ПРАВИЛО ЦИТАТ: Если в новости есть прямой контекст, цитаты политиков, Белого дома или лидеров крипторынка, СТРОГО оформляй их через цитирование с помощью HTML-тегов <blockquote>Текст цитаты</blockquote>.
ПРАВИЛО ДЛИНЫ: Текст telegram_caption должен представлять собой краткий пересказ новости. Длина текста telegram_caption КАТЕГОРИЧЕСКИ не должна превышать 800 символов (включая пробелы). Это необходимо, чтобы весь пост вместе с автоматически добавляемой ссылкой на сайт гарантированно укладывался в лимит 1000 символов.

Верни результат СТРОГО в формате JSON с тремя следующими ключами:
{{
  "russian_title": "Привлекательный заголовок для веб-сайта на русском языке в стиле Crypto Analytics (без кликбейта, отражающий суть)",
  "telegram_caption": "Краткий пересказ новости для Telegram-канала (подпись к фото/видео). Длина должна быть не более 800 символов (включая пробелы). Должна содержать заголовок капсом с эмодзи в начале, лаконичный разбор и вывод 'Что это значит для рынка? 🤔'. Хэштеги КАТЕГОРИЧЕСКИ запрещены. Разрешены только теги <b>, <a>, и <blockquote> (для цитат/важного контекста).",
  "full_article": "Полная, развернутая и максимально детальная статья для веб-сайта без каких-либо сокращений (около 1500-2500 символов). Подробно опиши предысторию события, контекст, технические детали, мнения участников рынка, развернутый вывод и последствия для индустрии. Разрешены HTML-теги <b>, <a>, <i>, <blockquote>."
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

def extract_tweet_details(title, description, gemini_key):
    """Вытаскивает детали твита через Gemini API для последующей отрисовки"""
    prompt = f"""Ниже приведена новость о публикации (твите) в соцсети X (Twitter).
Новость:
Заголовок: {title}
Описание: {description}

Выдели из этой новости данные для отрисовки оригинального твита.
Верни результат СТРОГО в формате JSON с четырьмя ключами:
{{
  "author_name": "Имя автора (например: Vitalik Buterin, Elon Musk, CZ)",
  "author_handle": "Юзернейм автора (например: @VitalikButerin, @elonmusk, @cz_binance)",
  "tweet_text": "Текст твита на английском (или русском, если в новости цитируется русскоязычный твит), максимально близкий к оригиналу",
  "is_verified": true или false (правда ли, что автор верифицирован/является крупной фигурой)
}}
"""
    response_json = call_gemini_api(prompt, gemini_key, is_json=True)
    if not response_json:
        return None
    try:
        return json.loads(response_json)
    except Exception as e:
        print(f"Ошибка парсинга JSON деталей твита: {e}")
        return None

def draw_tweet_card(details, output_path):
    """Рисует премиальную карточку твита в стиле X Dark Mode с помощью Pillow"""
    # Импортируем Pillow динамически
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        import subprocess
        import sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
        from PIL import Image, ImageDraw, ImageFont
        
    try:
        # Размеры карточки
        width, height = 800, 420
        # X Dim Blue Theme: #15202b
        bg_color = (21, 32, 43)
        text_color = (255, 255, 255)
        gray_color = (136, 153, 166)
        accent_color = (29, 155, 240) # Twitter Blue
        
        img = Image.new("RGB", (width, height), bg_color)
        draw = ImageDraw.Draw(img)
        
        # Пытаемся загрузить стандартные шрифты
        font_bold = None
        font_reg = None
        for font_name in ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "Arial-Bold.ttf"]:
            try:
                font_bold = ImageFont.truetype(font_name, 22)
                break
            except Exception:
                continue
        for font_name in ["DejaVuSans.ttf", "LiberationSans.ttf", "Arial.ttf"]:
            try:
                font_reg = ImageFont.truetype(font_name, 18)
                break
            except Exception:
                continue
                
        if not font_bold:
            font_bold = ImageFont.load_default()
        if not font_reg:
            font_reg = ImageFont.load_default()
            
        # 1. Рисуем аватарку (круг с первой буквой имени)
        avatar_color = (99, 102, 241)
        draw.ellipse([30, 30, 90, 90], fill=avatar_color)
        first_letter = details.get("author_name", "X")[0].upper()
        draw.text((50, 42), first_letter, fill=(255, 255, 255), font=font_bold)
        
        # 2. Имя автора
        author_name = details.get("author_name", "Crypto Player")
        draw.text((110, 35), author_name, fill=text_color, font=font_bold)
        
        # Рассчитаем ширину имени для рисования галочки
        name_width = len(author_name) * 12
        if hasattr(draw, 'textlength'):
            try:
                name_width = draw.textlength(author_name, font=font_bold)
            except Exception:
                pass
        
        # Рисуем галочку верификации
        if details.get("is_verified", True):
            badge_x = int(110 + name_width + 8)
            draw.ellipse([badge_x, 38, badge_x + 18, 56], fill=accent_color)
            draw.line([badge_x + 5, 47, badge_x + 8, 51], fill=(255, 255, 255), width=2)
            draw.line([badge_x + 8, 51, badge_x + 13, 44], fill=(255, 255, 255), width=2)
            
        # 3. Юзернейм
        author_handle = details.get("author_handle", "@cryptoplayer")
        draw.text((110, 65), author_handle, fill=gray_color, font=font_reg)
        
        # 4. Текст твита (с переносом строк)
        tweet_text = details.get("tweet_text", "")
        
        # Перенос слов
        words = tweet_text.split()
        lines = []
        current_line = []
        for word in words:
            current_line.append(word)
            test_line = " ".join(current_line)
            test_width = len(test_line) * 10
            if hasattr(draw, 'textlength'):
                try:
                    test_width = draw.textlength(test_line, font=font_reg)
                except Exception:
                    pass
            if test_width > 700:
                current_line.pop()
                lines.append(" ".join(current_line))
                current_line = [word]
        if current_line:
            lines.append(" ".join(current_line))
            
        # Ограничиваем количество строк
        lines = lines[:8]
        
        y_offset = 120
        for line in lines:
            draw.text((30, y_offset), line, fill=text_color, font=font_reg)
            y_offset += 28
            
        # 5. Рисуем футер (разделитель и иконки активности)
        draw.line([30, 360, 770, 360], fill=(56, 68, 77), width=1)
        
        # Иконки активности
        footer_text = "💬 1.2K     🔁 4.5K     ❤️ 18K     📊 120K"
        draw.text((30, 375), footer_text, fill=gray_color, font=font_reg)
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        img.save(output_path, "JPEG")
        print(f"Карточка твита успешно отрисована в {output_path}")
        return True
    except Exception as e:
        print(f"Ошибка при генерации карточки твита: {e}")
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
    import re
    safe_id = re.sub(r'[^\w\-_\.]', '_', article_id)
    local_filename = f"article_{safe_id}.jpg"
    temp_path = os.path.join(BASE_DIR, "images", f"temp_{local_filename}")
    final_path = os.path.join(BASE_DIR, "images", local_filename)
    relative_path = f"./images/{local_filename}"
    
    # 1. Скачиваем оригинальную картинку во временный файл
    try:
        import subprocess
        ua = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        cmd = ['curl', '-s', '-L', '-A', ua, '-o', temp_path, image_url]
        res = subprocess.run(cmd, timeout=15)
        if res.returncode != 0 or not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            raise Exception("curl returned error or empty file")
    except Exception as e:
        print(f"Не удалось скачать изображение по ссылке {image_url}: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
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

def save_article_to_json(news_item, post_text, russian_title=None, category="news"):
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
        "extra_images": news_item.get('extra_images', []),
        "post_text": post_text,
        "category": category,
        "date": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
        # Используем предзаданный _timestamp (если был установлен для синхронизации с TG-ссылкой)
        "timestamp": news_item.get('_timestamp', int(time.time()))
    }
    
    # Избегаем дублирования по ID
    if any(a['id'] == news_item['id'] for a in articles):
        return
        
    articles.insert(0, article_data)
    articles = articles[:100]  # Храним последние 100 новостей
    
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        print(f"Статья категории '{category}' сохранена в articles.json для сайта!")
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

def fetch_reddit_memes():
    """Получает свежие мемы с сабреддита /r/cryptocurrencymemes через RSS"""
    url = "https://www.reddit.com/r/cryptocurrencymemes/.rss"
    headers = {'User-Agent': 'CryptoAnalyticsFeedBot/1.0 (contact: support@cryptoanalytics.com)'}
    req = urllib.request.Request(url, headers=headers)
    processed_ids = get_processed_ids()
    memes = []
    try:
        # Разрешаем обход ssl-сертификатов на случай локальных проблем
        import ssl
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=10, context=context) as response:
            xml_data = response.read().decode('utf-8', errors='ignore')
        
        # Поиск записей entry
        entries = re.findall(r'<entry>(.*?)</entry>', xml_data, re.DOTALL)
        for entry in entries[:10]:
            title_match = re.search(r'<title>(.*?)</title>', entry, re.DOTALL)
            link_match = re.search(r'<link href="(.*?)"', entry)
            
            title = title_match.group(1).strip() if title_match else ""
            link = link_match.group(1).strip() if link_match else ""
            
            # Поиск любых прямых ссылок на изображения в записи
            imgs = re.findall(r'(https://[^\s"<>]+?\.(?:jpg|jpeg|png|webp|gif))', entry)
            imgs = [img for img in imgs if 'redditstatic.com' not in img]
            
            img_url = imgs[0] if imgs else None
            if img_url:
                img_url = img_url.replace("preview.redd.it", "i.redd.it")
            else:
                continue
                
            # Парсим ID поста
            meme_id = f"meme_{link.split('/')[-2]}" if '/' in link else f"meme_{hash(title)}"
            if meme_id not in processed_ids:
                memes.append({
                    "id": meme_id,
                    "source": "Reddit",
                    "title": title,
                    "description": "Свежий крипто-мем",
                    "link": link,
                    "image_url": img_url
                })
        return memes
    except Exception as e:
        print(f"Ошибка получения мемов с Reddit: {e}")
        return []

def generate_meme_post(meme_item, gemini_key):
    """Переводит заголовок мема и генерирует забавный текст подписи с помощью Gemini"""
    prompt = f"""Ты — редактор юмористического раздела в Crypto Analytics.
Ниже приведен популярный мем с Reddit (заголовок на английском).
Заголовок: {meme_item['title']}

Твоя задача:
1. Переведи заголовок на русский язык, сохранив оригинальный юмор и крипто-сленг.
2. Придумай краткое забавное описание для поста в Telegram-канале (до 300 символов), которое поясняет шутку или добавляет иронии о текущей ситуации на рынке.
3. Категорически запрещено использовать слово ForkLog. Пиши только от лица Crypto Analytics.
4. Разрешены только HTML-теги <b>, <a>, <i>. Хэштеги КАТЕГОРИЧЕСКИ запрещены.

Верни ответ СТРОГО в формате JSON с тремя следующими ключами:
{{
  "russian_title": "Переведенный заголовок мема на русский язык",
  "telegram_caption": "Смешная подпись к картинке в Telegram (до 300 символов) с эмодзи. Должно содержать заголовок капсом с эмодзи в начале.",
  "full_article": "Краткое описание мема и юмористический комментарий для сайта (около 400-800 символов)."
}}
"""
    response_json = call_gemini_api(prompt, gemini_key, is_json=True)
    if not response_json:
        return None
    try:
        parsed = json.loads(response_json)
        return {
            "russian_title": parsed.get("russian_title", "").strip() or meme_item['title'],
            "telegram_caption": parsed.get("telegram_caption", "").strip(),
            "full_article": parsed.get("full_article", "").strip()
        }
    except Exception as e:
        print(f"Ошибка парсинга мема через Gemini: {e}")
        return None

def generate_guide_post(gemini_key, env):
    """Генерирует полезный криптогайд с реферальными ссылками на биржи"""
    bybit_link = env.get("BYBIT_REF_LINK", "https://partner.bybit.com/b/crypto_analytics")
    binance_link = env.get("BINANCE_REF_LINK", "https://accounts.binance.com/register?ref=crypto_analytics")
    okx_link = env.get("OKX_REF_LINK", "https://www.okx.com/join/crypto_analytics")
    
    themes = [
        "Как начать торговать на Bybit новичку с нуля",
        "Безопасность криптовалюты: правила хранения активов на кошельке",
        "Что такое стейкинг и как зарабатывать пассивный доход",
        "Гид по P2P-торговле: как покупать крипту без рисков блокировки карт",
        "Разница между горячими и холодными кошельками: что выбрать"
    ]
    import random
    selected_theme = random.choice(themes)
    
    prompt = f"""Ты — ведущий финансовый аналитик и автор обучающих программ Crypto Analytics.
Напиши понятный и полезный криптогайд для новичков на тему: "{selected_theme}".

ПРАВИЛА ОФОРМЛЕНИЯ ССЫЛОК:
Интегрируй в текст следующие партнерские реферальные ссылки для регистрации на биржах (используй HTML-теги <a href="...">Имя биржи</a>):
- Регистрация на Bybit: {bybit_link}
- Регистрация на OKX: {okx_link}
- Регистрация на Binance: {binance_link}

ПРАВИЛО ДЛИНЫ: telegram_caption (краткая версия для Telegram) должна быть не более 800 символов (включая пробелы) и содержать ключевые шаги/лайфхаки и призыв к действию с реферальной ссылкой.
full_article (полная версия для сайта) должна быть детальной (1500-2500 символов) с пошаговыми инструкциями, примерами и реферальными ссылками.

Категорически запрещено упоминать ForkLog.

Верни результат строго в формате JSON:
{{
  "russian_title": "Заголовок гайда (например: ГИД: Как безопасно покупать криптовалюту)",
  "telegram_caption": "Краткая версия гайда с шагами и реферальными ссылками бирж (до 800 символов). Должна содержать заголовок капсом с эмодзи в начале.",
  "full_article": "Полный текст гайда с HTML-разметкой <b>, <a>, <i>, <blockquote> для веб-сайта."
}}
"""
    response_json = call_gemini_api(prompt, gemini_key, is_json=True)
    if not response_json:
        return None
    try:
        parsed = json.loads(response_json)
        guide_id = f"guide_{int(time.time())}"
        return {
            "id": guide_id,
            "title": parsed.get("russian_title", "").strip() or selected_theme,
            "telegram_caption": parsed.get("telegram_caption", "").strip(),
            "full_article": parsed.get("full_article", "").strip(),
            "source": "Crypto Analytics",
            "link": "https://maxtyutin.github.io/cryptochannel/",
            "image_url": "https://images.unsplash.com/photo-1639762681485-074b7f938ba0?q=80&w=1200&auto=format&fit=crop"
        }
    except Exception as e:
        print(f"Ошибка генерации гайда: {e}")
        return None

def check_price_signals(bot_token, chat_id, gemini_key):
    """Проверяет резкие скачки цен BTC/ETH и публикует срочные сигналы в ТГ и на сайт"""
    prices_path = os.path.join(BASE_DIR, "last_prices.json")
    current_prices = {}
    
    # 1. Получаем текущие цены
    url = 'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            current_prices = {
                "btc": data['bitcoin']['usd'],
                "eth": data['ethereum']['usd'],
                "timestamp": int(time.time())
            }
    except Exception as e:
        print(f"Ошибка получения цен для сигналов: {e}")
        return
        
    # 2. Если файла нет, просто создаем его и выходим
    if not os.path.exists(prices_path):
        try:
            with open(prices_path, 'w') as f:
                json.dump(current_prices, f)
        except Exception:
            pass
        return
        
    # 3. Загружаем предыдущие цены
    try:
        with open(prices_path, 'r') as f:
            last_data = json.load(f)
    except Exception:
        return
        
    last_btc = last_data.get("btc")
    last_eth = last_data.get("eth")
    last_signal_time = last_data.get("last_signal_time", 0)
    
    if not last_btc or not last_eth:
        return
        
    # Проверяем лимит 4 часа между сигналами, чтобы не спамить
    if time.time() - last_signal_time < 14400:
        return
        
    # Вычисляем изменения в %
    btc_change = ((current_prices['btc'] - last_btc) / last_btc) * 100
    eth_change = ((current_prices['eth'] - last_eth) / last_eth) * 100
    
    alert_coin = None
    alert_change = 0.0
    alert_price = 0.0
    
    if abs(btc_change) >= 2.5:
        alert_coin = "Bitcoin (BTC)"
        alert_change = btc_change
        alert_price = current_prices['btc']
    elif abs(eth_change) >= 2.5:
        alert_coin = "Ethereum (ETH)"
        alert_change = eth_change
        alert_price = current_prices['eth']
        
    if alert_coin:
        print(f"🚨 Фиксация резкого изменения: {alert_coin} на {alert_change:.2f}%")
        direction = "вырос" if alert_change > 0 else "упал"
        emoji = "🟢" if alert_change > 0 else "🔴"
        sign = "+" if alert_change > 0 else ""
        
        prompt = f"""Ты — ведущий трейдер и технический аналитик Crypto Analytics.
Срочное оповещение: курс {alert_coin} резко {direction} на {sign}{alert_change:.2f}% и сейчас составляет ${alert_price:,.2f}.
Напиши краткое срочное предупреждение для инвесторов (до 400 символов).
Объясни возможные технические причины (ликвидация шортов/лонгов, пробой уровня поддержки/сопротивления, новости) и напиши краткий вывод 'Что делать? 🎯'.

ПРАВИЛА:
- Язык: русский.
- Ограничение: до 400 символов.
- Используй HTML-теги <b> для акцентов.
- В конце добавь хэштеги: #сигналы #рынок #{alert_coin.split()[0].lower()} #срочно.
- Никаких упоминаний ForkLog.
"""
        signal_text = call_gemini_api(prompt, gemini_key, is_json=False)
        if signal_text:
            full_signal_text = f"🚨 <b>СРОЧНЫЙ СИГНАЛ CRYPTO ANALYTICS</b>\n\n{signal_text.strip()}"
            
            # Отправляем в Telegram
            if bot_token and chat_id:
                send_to_telegram(full_signal_text, bot_token, chat_id)
                
            # Сохраняем на сайт
            signal_item = {
                "id": f"signal_{int(time.time())}",
                "title": f"Срочный сигнал: Резкое движение {alert_coin}!",
                "source": "Crypto Analytics",
                "link": "https://maxtyutin.github.io/cryptochannel/",
                "image_url": "https://images.unsplash.com/photo-1618042164219-62c820f10723?q=80&w=1200&auto=format&fit=crop"
            }
            save_article_to_json(signal_item, full_signal_text, signal_item['title'], category="signals")
            
            current_prices["last_signal_time"] = int(time.time())
            
    if "last_signal_time" not in current_prices:
        current_prices["last_signal_time"] = last_signal_time
        
    try:
        with open(prices_path, 'w') as f:
            json.dump(current_prices, f)
    except Exception:
        pass

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
        
        lines = ["📊 <b>КРИПТОВАЛЮТЫ: ДАЙДЖЕСТ CRYPTO ANALYTICS</b>\n", "Курсы основных криптоактивов и их изменение за 24 часа:\n"]
        
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

def get_stock_price(ticker):
    """Получение цен акций и изменения за 24ч с Yahoo Finance"""
    import urllib.request
    import json
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            meta = data['chart']['result'][0]['meta']
            price = meta['regularMarketPrice']
            prev_close = meta['chartPreviousClose']
            change = ((price - prev_close) / prev_close) * 100
            return price, change
    except Exception as e:
        print(f"Ошибка получения акций {ticker}: {e}")
        return None, None

def generate_stock_digest():
    """Генерация дайджеста цен акций ведущих криптокомпаний"""
    tickers = {
        'MSTR': 'MicroStrategy',
        'COIN': 'Coinbase',
        'MARA': 'MARA Holdings',
        'RIOT': 'Riot Platforms'
    }
    lines = ["📈 <b>АКЦИИ КРИПТОКОМПАНИЙ: ДАЙДЖЕСТ CRYPTO ANALYTICS</b>\n", "Стоимость акций ведущих компаний индустрии и их изменение за 24 часа:\n"]
    
    success_count = 0
    for ticker, name in tickers.items():
        price, change = get_stock_price(ticker)
        if price is not None:
            success_count += 1
            emoji = "🟢" if change >= 0 else "🔴"
            sign = "+" if change >= 0 else ""
            lines.append(f"🔸 {name} ({ticker}): <b>${price:.2f}</b> ({emoji} {sign}{change:.2f}%)")
            
    if success_count == 0:
        return None
        
    lines.append("\n#акции #фондовыйрынок #mstr #coin #mara #riot #рынок")
    return "\n".join(lines)

def generate_market_review(gemini_key, crypto_digest, stock_digest):
    """Генерация краткого аналитического обзора рынка через Gemini API"""
    prompt = f"""Ты — профессиональный финансовый аналитик и редактор Crypto Analytics.
На основе следующих данных о котировках за 24 часа составь краткий аналитический обзор состояния крипторынка (не более 600 символов).
Опиши текущий тренд, взаимосвязь криптовалют и фондового рынка, и настроения инвесторов.

Курсы криптовалют:
{crypto_digest}

Акции криптокомпаний:
{stock_digest}

ПРАВИЛА:
- Пиши только на русском языке.
- Ограничение по длине: строго не более 600 символов.
- Используй HTML-теги <b> для выделения ключевых выводов или цифр.
- Никаких хэштегов внутри текста. В конце добавь хэштеги: #обзор #аналитика #рынок.
- Никаких упоминаний ForkLog.
"""
    review = call_gemini_api(prompt, gemini_key, is_json=False)
    return review.strip() if review else None

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
        target_marker = job.split(' /usr/bin/python3 ')[1].split(' >> ')[0]
        if not any(target_marker in line for line in cron_lines):
            arg_marker = "--digest" if "--digest" in job else ("--poll" if "--poll" in job else "")
            if arg_marker:
                if not any(target_marker in line and arg_marker in line for line in cron_lines):
                    cron_lines.append(job)
                    updated = True
            else:
                if not any(target_marker in line and ("--digest" in line or "--poll" in line) for line in cron_lines):
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
        
    setup_cron()
    args = sys.argv[1:]
    
    if "--digest" in args:
        print("Запуск генерации дайджеста цен и акций...")
        crypto_text = generate_price_digest()
        stock_text = generate_stock_digest()
        
        if crypto_text:
            print("\n=== СГЕНЕРИРОВАННЫЙ ДАЙДЖЕСТ КРИПТЫ ===")
            print(crypto_text)
            if bot_token and chat_id:
                if send_to_telegram(crypto_text, bot_token, chat_id):
                    print("Дайджест цен криптовалют успешно опубликован в Telegram!")
                else:
                    print("Не удалось отправить дайджест криптовалют в Telegram.")
                    
        if stock_text:
            print("\n=== СГЕНЕРИРОВАННЫЙ ДАЙДЖЕСТ АКЦИЙ ===")
            print(stock_text)
            if bot_token and chat_id:
                if send_to_telegram(stock_text, bot_token, chat_id):
                    print("Дайджест акций криптокомпаний успешно опубликован в Telegram!")
                else:
                    print("Не удалось отправить дайджест акций в Telegram.")
                    
        if crypto_text and stock_text:
            print("\n=== СГЕНЕРИРОВАННЫЙ ОБЗОР РЫНКА ===")
            review_text = generate_market_review(gemini_key, crypto_text, stock_text)
            if review_text:
                print(review_text)
                if bot_token and chat_id:
                    if send_to_telegram(review_text, bot_token, chat_id):
                        print("Аналитический обзор рынка успешно опубликован в Telegram!")
                    else:
                        print("Не удалось отправить обзор рынка в Telegram.")
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
        
    # Только новости
    category = "news"
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
            save_processed_id(item['id'])
            continue
        selected_item = item
        break
        
    if not selected_item:
        print("Все новые новости оказались семантическими дубликатами.")
        return
        
    print(f"Выбрана новость: {selected_item['title']}. Ищем дополнительные изображения из источника...")
    extra_images = fetch_article_images(selected_item.get('link', ''), selected_item.get('image_url'))
    if extra_images:
        print(f"Найдено доп. изображений: {len(extra_images)}")
        selected_item['extra_images'] = extra_images
    else:
        selected_item['extra_images'] = []

    print(f"Генерация поста...")
    post_data = generate_forklog_post(selected_item, gemini_key)

    if post_data and selected_item:
        telegram_caption = post_data["telegram_caption"]
        full_article = post_data["full_article"]
        russian_title = post_data["russian_title"]
        
        article_url = f"https://maxtyutin.github.io/cryptochannel/#article-{selected_item['id']}"
        # Генерируем timestamp заранее, чтобы использовать его и в URL и в save_article_to_json
        article_timestamp = int(time.time())
        selected_item['_timestamp'] = article_timestamp
        article_clean_url = f"https://maxtyutin.github.io/cryptochannel/#article-{article_timestamp}"
        telegram_caption += f"\n\n👉 <a href=\"{article_clean_url}\">Читать на Crypto Analytics</a>"
        
        print("\n=== СГЕНЕРИРОВАННЫЙ ПОСТ (TG) ===")
        print(telegram_caption)
        print("\n=== СГЕНЕРИРОВАННАЯ СТАТЬЯ (САЙТ) ===")
        print(full_article)
        print("============================\n")
        
        with open(OUTPUT_FILE, 'w') as f:
            f.write(f"# Свежая новость от ИИ-редактора\n\n## ДЛЯ TELEGRAM:\n{telegram_caption}\n\n## ДЛЯ САЙТА:\n{full_article}\n\n*Оригинальный источник: {selected_item.get('link', 'Crypto Analytics')}*\n*Картинка: {selected_item.get('image_url', 'нет')}*")
            
        local_img_path = None
        if selected_item.get('image_url'):
            if selected_item['image_url'].startswith('http'):
                is_tweet = False
                title_lower = selected_item['title'].lower()
                desc_lower = selected_item.get('description', '').lower()
                if 'tweet' in title_lower or 'on x' in title_lower or 'on twitter' in title_lower or 'tweet' in desc_lower or 'on x' in desc_lower:
                    is_tweet = True
                    
                if is_tweet:
                    print("Обнаружена новость о твите. Попытка генерации скриншота поста из X...")
                    tweet_details = extract_tweet_details(selected_item['title'], selected_item.get('description', ''), gemini_key)
                    if tweet_details:
                        safe_id = re.sub(r'[^\w\-_\.]', '_', selected_item['id'])
                        tweet_filename = f"images/tweet_{safe_id}.jpg"
                        tweet_abs_path = os.path.join(BASE_DIR, tweet_filename)
                        if draw_tweet_card(tweet_details, tweet_abs_path):
                            local_img_path = tweet_abs_path
                            selected_item['image_url'] = f"./{tweet_filename}"
                            print(f"Скриншот твита успешно сгенерирован: {selected_item['image_url']}")
                            
                if not local_img_path:
                    print(f"Скачивание и обработка изображения: {selected_item['image_url']}...")
                    img_result = download_and_standardize_image(selected_item['image_url'], selected_item['id'])
                    if img_result:
                        local_img_path = img_result["local_path"]
                        selected_item['image_url'] = img_result["relative_url"]
            else:
                local_img_path = os.path.join(BASE_DIR, selected_item['image_url'].replace('./', ''))
                
        if bot_token and chat_id:
            print("Отправка поста в Telegram-канал...")
            success = False
            
            if local_img_path:
                print(f"Отправка локально обработанного изображения: {local_img_path}...")
                success = send_photo_to_telegram(telegram_caption, local_img_path, bot_token, chat_id)
                if success:
                    print("Успешно опубликовано со стандартизированным изображением!")
                    
            if not success and selected_item.get('image_url') and selected_item['image_url'].startswith('http'):
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
                save_article_to_json(selected_item, full_article, russian_title, category=category)
        else:
            print("Параметры Telegram не настроены в .env. Пост не отправлен.")
            save_processed_id(selected_item['id'])
            save_article_to_json(selected_item, full_article, russian_title, category=category)

if __name__ == "__main__":
    main()
