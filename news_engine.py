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
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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
                     'tracking', 'subscribe', 'newsletter', 'author', 'profile', 'gravatar',
                     'recommend', 'sidebar', 'widget', 'advertis', 'promo', 'social', 'telegram',
                     'twitter', 'facebook', 'instagram', 'youtube', 'linkedin', 'ad-', 'ads-',
                     'footer', 'header', 'nav-', 'button', 'pixel']
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

    # Сначала пытаемся вырезать блок основного контента статьи (без сайдбаров и подвалов)
    content_block = None
    content_patterns = [
        r'<div[^>]+class=["\'][^"\']*(?:post-content|post-body|entry-content|article-body|article__body|post-content-wrap)[^"\']*["\'][^>]*>(.*?)</div>',
        r'<article[^>]*>(.*?)</article>',
        r'<main[^>]*>(.*?)</main>'
    ]
    
    for pat in content_patterns:
        match = re.search(pat, page_html, re.DOTALL | re.IGNORECASE)
        if match:
            if len(match.group(1).strip()) > 300:
                content_block = match.group(1)
                break
                
    if not content_block:
        content_block = page_html

    # Очищаем контент от блоков рекомендаций, "Читайте также", промо-ссылок и врезок, встроенных в текст
    content_block = re.sub(r'<div[^>]+class=["\'][^"\']*(?:related|read-more|read-also|promo|recommend|widget)[^"\']*["\'][^>]*>.*?</div>', '', content_block, flags=re.DOTALL | re.IGNORECASE)
    content_block = re.sub(r'<aside[^>]*>.*?</aside>', '', content_block, flags=re.DOTALL | re.IGNORECASE)

    # Ищем теги <img> только внутри выделенного контента статьи
    for m in re.finditer(r'<img[^>]+(?:src|data-src)=["\']([^"\']+)["\']', content_block, re.IGNORECASE):
        add_url(html.unescape(m.group(1)))
    for m in re.finditer(r'srcset=["\']([^"\']+)', content_block, re.IGNORECASE):
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

def fetch_og_image(article_url):
    """Скачивает страницу статьи и находит в ней мета-тег og:image для обложки."""
    if not article_url or not article_url.startswith('http'):
        return None
    try:
        ua = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        req = urllib.request.Request(article_url, headers={'User-Agent': ua})
        with urllib.request.urlopen(req, timeout=8) as resp:
            page_html = resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"[news_engine] Не удалось скачать страницу для поиска og:image: {e}")
        return None
        
    # Ищем og:image meta-тег
    for m in re.finditer(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', page_html, re.IGNORECASE):
        url = html.unescape(m.group(1)).strip()
        if url.startswith('http'):
            return url
    for m in re.finditer(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', page_html, re.IGNORECASE):
        url = html.unescape(m.group(1)).strip()
        if url.startswith('http'):
            return url
    return None

def fetch_article_text(article_url):
    """Скачивает страницу источника и извлекает чистый текст статьи из основного блока контента."""
    if not article_url or not article_url.startswith('http'):
        return ""
    try:
        ua = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        req = urllib.request.Request(article_url, headers={'User-Agent': ua})
        with urllib.request.urlopen(req, timeout=10) as resp:
            page_html = resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"[news_engine] Не удалось скачать страницу для извлечения текста: {e}")
        return ""
        
    # Ищем блок основного контента статьи
    content_block = None
    content_patterns = [
        r'<div[^>]+class=["\'][^"\']*(?:post-content|post-body|entry-content|article-body|article__body|post-content-wrap)[^"\']*["\'][^>]*>(.*?)</div>',
        r'<article[^>]*>(.*?)</article>',
        r'<main[^>]*>(.*?)</main>'
    ]
    
    for pat in content_patterns:
        match = re.search(pat, page_html, re.DOTALL | re.IGNORECASE)
        if match:
            if len(match.group(1).strip()) > 300:
                content_block = match.group(1)
                break
                
    if not content_block:
        content_block = page_html
        
    # Очищаем HTML-теги, скрипты, стили
    text = re.sub(r'<script[^>]*>.*?</script>', '', content_block, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text) # Удаляем теги
    text = html.unescape(text) # Декодируем HTML-сущности
    text = re.sub(r'\s+', ' ', text).strip() # Схлопываем пробелы
    
    return text[:6000] # Ограничиваем длину текста для Gemini

def generate_forklog_post(news_item, gemini_key):
    """Генерация Telegram-поста и полной статьи для сайта с помощью Gemini API"""
    
    # Пытаемся получить полный текст статьи с оригинального сайта
    source_text = fetch_article_text(news_item.get('link', ''))
    if not source_text:
        # Если не удалось скачать, используем описание из RSS как резерв
        source_text = news_item.get('description', '')
        print("[news_engine] Используется описание из RSS в качестве источника текста.")
    else:
        print(f"[news_engine] Успешно скачан оригинальный текст статьи ({len(source_text)} символов).")

    prompt = f"""Ты — профессиональный крипто-журналист и редактор Crypto Analytics. 
На основе оригинального текста статьи напиши качественный перевод-адаптацию на русский язык и краткий Telegram-пост.

ИНФОРМАЦИЯ О СТАТЬЕ:
Источник: {news_item['source']}
Оригинальный заголовок: {news_item['title']}
Оригинальный текст статьи: {source_text}

ПРАВИЛО ПЕРЕВОДА: Твоя статья для сайта должна строго опираться на факты из оригинального текста. Не выдумывай вымышленных цитат, новых участников или не описанных в оригинале технических деталей. Сделай качественный, структурированный, читаемый перевод-адаптацию.
ПРАВИЛО: КАТЕГОРИЧЕСКИ запрещено использовать или упоминать название ForkLog. Пиши только от лица Crypto Analytics.
ПРАВИЛО ИСТОЧНИКОВ: В качестве авторитетных источников данных, ончейн-метрик или финансирования старайся ссылаться на такие платформы как The Block и Allium (например, 'по данным отчетов Allium...', 'согласно информации The Block...').
ПРАВИЛО ЦИТАТ: Если в оригинальном тексте есть прямой контекст или цитаты участников рынка, СТРОГО оформляй их через цитирование с помощью HTML-тегов <blockquote>Текст цитаты</blockquote>.
ПРАВИЛО ДЛИНЫ TG-ПОСТА: Текст telegram_caption должен представлять собой краткий пересказ новости. Длина текста telegram_caption КАТЕГОРИЧЕСКИ не должна превышать 800 символов (включая пробелы). Это необходимо, чтобы весь пост вместе с автоматически добавляемой ссылкой на сайт гарантированно укладывался в лимит 1000 символов.
ПРАВИЛО ЗАГОЛОВКА: Заголовок russian_title должен быть написан капсом с подходящим эмодзи в начале, например: '🚀 СТЕЙБЛКОИНЫ ИНТЕГРИРУЮТ В БАНКОВСКУЮ СИСТЕМУ'. Он должен быть абсолютно одинаковым для сайта и Telegram-поста.

Верни результат СТРОГО в формате JSON с тремя следующими ключами:
{{
  "russian_title": "Привлекательный заголовок капсом с эмодзи в начале (например: '🚀 HYUNDAI ВНЕДРЯЕТ СТЕЙБЛКОИНЫ ДЛЯ МЕЖДУНАРОДНЫХ ПЕРЕВОДОВ')",
  "telegram_caption": "Краткий пересказ новости для Telegram-канала (БЕЗ повторения заголовка в тексте!). Длина должна быть не более 800 символов (включая пробелы). Должна содержать лаконичный разбор и вывод 'Что это значит для рынка? 🤔'. Хэштеги КАТЕГОРИЧЕСКИ запрещены. Разрешены только теги <b>, <a>, и <blockquote> (для цитат/важного контекста).",
  "full_article": "Полная статья-перевод для веб-сайта на русском языке (около 1500-2500 символов). Подробно изложи факты, технические детали и цитаты из оригинального текста. Раздели текст на логические абзацы. Разрешены HTML-теги <b>, <a>, <i>, <blockquote>."
}}
"""
    for attempt in range(3):
        response_json = call_gemini_api(prompt, gemini_key, is_json=True)
        if not response_json:
            print(f"Попытка {attempt+1}: ИИ вернул пустой ответ.")
            continue
            
        try:
            # Очищаем возможные markdown-обертки
            clean_json = response_json.strip()
            if clean_json.startswith("```"):
                start = clean_json.find("{")
                end = clean_json.rfind("}")
                if start != -1 and end != -1:
                    clean_json = clean_json[start:end+1]
            
            parsed = json.loads(clean_json)
            russian_title = parsed.get("russian_title", "").strip() or news_item['title']
            
            # Гарантируем, что заголовок в верхнем регистре (сохраняя эмодзи)
            match = re.match(r'^([^\w]*)(.*)$', russian_title)
            if match:
                prefix, text = match.groups()
                russian_title = prefix + text.upper()
                
            caption_body = parsed.get("telegram_caption", "").strip()
            # Собираем Telegram пост: заголовок в начале
            telegram_caption = f"<b>{russian_title}</b>\n\n{caption_body}"
            
            return {
                "russian_title": russian_title,
                "telegram_caption": telegram_caption,
                "full_article": parsed.get("full_article", "").strip()
            }
        except Exception as e:
            print(f"Попытка {attempt+1} - Ошибка парсинга сгенерированного JSON: {e}")
            if attempt < 2:
                time.sleep(2)
                
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

def generate_title_card(title, output_path, gemini_key=None):
    """Генерирует обложку для статьи с помощью Imagen (Gemini API) с автоматическими фолбеками (Pollinations AI, Unsplash Scraper, Curated Pool) для обхода блокировок РКН"""
    if not gemini_key:
        env = load_env()
        gemini_key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")

    if not gemini_key:
        print("[news_engine] GEMINI_API_KEY отсутствует. Невозможно сгенерировать промт для картинки.")
        return False

    prompt = f"""Write a detailed, high-quality prompt in English for an AI image generator (like Stable Diffusion) based on the following article title.
Also, provide 2-3 simple English keywords that represent the core topic of the article for a photo search engine.

ARTICLE TITLE: {title}

Return the result strictly in JSON format with two keys:
{{
  "image_prompt": "English prompt for AI image generator (1-2 sentences, technological, abstract, no text)",
  "search_keywords": "2-3 search keywords in English (e.g., 'bitcoin security', 'artificial intelligence', 'ethereum')"
}}"""

    print(f"[news_engine] Запрос к Gemini для составления промта и ключевых слов...")
    image_prompt = "futuristic cryptocurrency blockchain tech background, highly detailed, 3d render"
    search_keywords = "cryptocurrency blockchain"
    
    try:
        response_json = call_gemini_api(prompt, gemini_key, is_json=True)
        if response_json:
            parsed = json.loads(response_json)
            image_prompt = parsed.get("image_prompt", image_prompt).strip().replace('"', '').replace("'", "")
            search_keywords = parsed.get("search_keywords", search_keywords).strip()
    except Exception as e:
        print(f"[news_engine] Ошибка получения промта от Gemini: {e}")

    print(f"[news_engine] Итоговый промт: {image_prompt}")
    print(f"[news_engine] Ключевые слова для поиска: {search_keywords}")

    # --- Вариант 1: Официальный Google Gemini API (Imagen 4.0 / 3.0) ---
    import base64
    for model in ["imagen-4.0-generate-001", "imagen-3.0-generate-002"]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predict?key={gemini_key}"
        payload = {
            "instances": [{"prompt": image_prompt}],
            "parameters": {
                "sampleCount": 1,
                "aspectRatio": "16:9",
                "outputMimeType": "image/jpeg"
            }
        }
        
        print(f"[news_engine] Вариант 1: Попытка генерации через Gemini Imagen ({model})...")
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=20) as response:
                result = json.loads(response.read().decode('utf-8'))
                if 'predictions' in result and len(result['predictions']) > 0:
                    b64_data = result['predictions'][0]['bytesBase64Encoded']
                    image_bytes = base64.b64decode(b64_data)
                    os.makedirs(os.path.dirname(output_path), exist_ok=True)
                    with open(output_path, 'wb') as f:
                        f.write(image_bytes)
                    print(f"[news_engine] Успешно сгенерировано изображение через Gemini Imagen ({model})!")
                    return True
        except Exception as e:
            print(f"[news_engine] Ошибка Imagen {model}: {e}")

    # --- Вариант 2: Бесплатный Pollinations AI с зеркалами для обхода блокировок РКН ---
    import urllib.parse
    encoded_prompt = urllib.parse.quote(image_prompt)
    
    # Список зеркал Pollinations AI (основной домен и резервные адреса)
    pollinations_mirrors = [
        f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1200&height=675&nologo=true&private=true",
        f"https://pollinations.ai/p/{encoded_prompt}?width=1200&height=675&nologo=true",
        f"https://www.pollinations.ai/p/{encoded_prompt}?width=1200&height=675&nologo=true"
    ]
    
    for i, p_url in enumerate(pollinations_mirrors):
        print(f"[news_engine] Вариант 2 (Зеркало {i+1}): Попытка генерации через Pollinations AI...")
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            headers = {'User-Agent': 'Mozilla/5.0'}
            req = urllib.request.Request(p_url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as response:
                with open(output_path, 'wb') as f:
                    f.write(response.read())
            print(f"[news_engine] Успешно сгенерировано изображение через Pollinations AI (Зеркало {i+1})!")
            return True
        except Exception as e:
            print(f"[news_engine] Ошибка зеркала Pollinations {i+1}: {e}")

    # --- Вариант 3: Динамический парсинг Unsplash без ключей по ключевым словам (РКН не блокирует) ---
    print(f"[news_engine] Вариант 3: Поиск релевантного фото на Unsplash по запросу '{search_keywords}'...")
    try:
        encoded_keywords = urllib.parse.quote(search_keywords)
        unsplash_search_url = f"https://unsplash.com/s/photos/{encoded_keywords}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        req = urllib.request.Request(unsplash_search_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            html_content = response.read().decode('utf-8', errors='ignore')
            # Регулярным выражением вытаскиваем ссылки на фотографии Unsplash
            matches = re.findall(r'https://images\.unsplash\.com/photo-[a-zA-Z0-9\-_]+', html_content)
            if matches:
                unique_urls = list(dict.fromkeys(matches))
                for img_url in unique_urls:
                    if "profile" not in img_url and "avatar" not in img_url:
                        target_img_url = f"{img_url}?q=80&w=1200&auto=format&fit=crop&h=675"
                        print(f"[news_engine] Найдено релевантное фото на Unsplash: {target_img_url}")
                        req_img = urllib.request.Request(target_img_url, headers=headers)
                        with urllib.request.urlopen(req_img, timeout=15) as img_resp:
                            with open(output_path, 'wb') as f:
                                f.write(img_resp.read())
                        print("[news_engine] Успешно загружено динамическое фото с Unsplash!")
                        return True
    except Exception as e:
        print(f"[news_engine] Ошибка поиска фото на Unsplash: {e}")

    # --- Вариант 4: Премиальный отобранный список Unsplash-обложек (Резервный пул) ---
    print("[news_engine] Вариант 4: Использование обложки из резервного пула...")
    curated_urls = [
        "https://images.unsplash.com/photo-1639762681485-074b7f938ba0?q=80&w=1200&auto=format&fit=crop&h=675",
        "https://images.unsplash.com/photo-1618042164219-62c820f10723?q=80&w=1200&auto=format&fit=crop&h=675",
        "https://images.unsplash.com/photo-1621761191319-c6fb62004040?q=80&w=1200&auto=format&fit=crop&h=675",
        "https://images.unsplash.com/photo-1518546305927-5a555bb7020d?q=80&w=1200&auto=format&fit=crop&h=675",
        "https://images.unsplash.com/photo-1642104704074-907c0698cbd9?q=80&w=1200&auto=format&fit=crop&h=675",
        "https://images.unsplash.com/photo-1622630998477-20aa696ecb05?q=80&w=1200&auto=format&fit=crop&h=675",
        "https://images.unsplash.com/photo-1639762681057-408e52192e55?q=80&w=1200&auto=format&fit=crop&h=675",
        "https://images.unsplash.com/photo-1644024312658-3951417522dd?q=80&w=1200&auto=format&fit=crop&h=675",
        "https://images.unsplash.com/photo-1621416894569-0f39ed31d247?q=80&w=1200&auto=format&fit=crop&h=675",
        "https://images.unsplash.com/photo-1634973357973-f2ed255753e1?q=80&w=1200&auto=format&fit=crop&h=675"
    ]
    import random
    selected_curated_url = random.choice(curated_urls)
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request(selected_curated_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            with open(output_path, 'wb') as f:
                f.write(response.read())
        print(f"[news_engine] Успешно загружена резервная обложка из пула: {selected_curated_url}")
        return True
    except Exception as e:
        print(f"[news_engine] Ошибка загрузки резервной обложки: {e}")
        
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
            # Если у изображения есть альфа-канал (прозрачность), накладываем его на белый фон,
            # иначе при конвертации в RGB прозрачные области станут черными.
            if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1])
                img = background
            elif img.mode != 'RGB':
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
        "date": (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))).strftime("%d.%m.%Y %H:%M"),
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

def wait_for_pages_build(pat, push_time_utc, timeout_seconds=180):
    """
    Опрашивает GitHub API, ожидая успешного завершения сборки GitHub Pages,
    которая началась после push_time_utc.
    """
    import urllib.request
    import json
    import datetime
    
    url = "https://api.github.com/repos/maxtyutin/cryptochannel/pages/builds/latest"
    headers = {
        "Authorization": f"token {pat}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "Render-Bot-Pages-Sync",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    start_time = time.time()
    print(f"[news_engine] Ожидание завершения сборки GitHub Pages (с {push_time_utc.isoformat()} UTC)...")
    
    while time.time() - start_time < timeout_seconds:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                build_data = json.loads(response.read().decode('utf-8'))
                
            status = build_data.get("status")
            updated_at_str = build_data.get("updated_at")
            
            if updated_at_str:
                # Парсим время обновления (например, "2026-07-13T19:51:24Z")
                updated_at = datetime.datetime.strptime(updated_at_str, "%Y-%m-%dT%H:%M:%SZ")
                
                # Если сборка завершена и время обновления позже, чем наш пуш (с запасом 15 секунд)
                if status == "built" and updated_at >= (push_time_utc - datetime.timedelta(seconds=15)):
                    duration = int(time.time() - start_time)
                    print(f"[news_engine] GitHub Pages успешно собран и опубликован за {duration} сек! (Обновлен в {updated_at_str})")
                    return True
                else:
                    print(f"[news_engine] Статус сборки: {status}. Последнее обновление: {updated_at_str}. Ожидаем...")
            else:
                print(f"[news_engine] Не удалось получить время обновления сборки. Статус: {status}. Ожидаем...")
                
        except Exception as e:
            print(f"[news_engine] Ошибка при проверке статуса Pages: {e}. Продолжаем ожидание...")
            
        time.sleep(8)
        
    print("[news_engine] Превышено время ожидания сборки GitHub Pages. Переходим к публикации в Telegram.")
    return False

def main():
    env = load_env()
    gemini_key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    bot_token = env.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")
    
    if not gemini_key:
        print("Ошибка: GEMINI_API_KEY не задан ни в .env, ни в переменных окружения. Пожалуйста, укажите его.")
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
    
    # Пытаемся обработать новости по одной. Если одна вызывает ошибку, помечаем её и идем к следующей.
    published_any = False
    for item in news_list:
        print(f"Проверка кандидата: {item['title']}...")
        if check_semantic_duplicate(item['title'], item['description'], gemini_key):
            print("Новость определена как семантический дубликат. Пропускаем.")
            save_processed_id(item['id'])
            continue
            
        print(f"Кандидат одобрен: {item['title']}. Начинаем обработку и публикацию...")
        
        # Скачиваем и обрабатываем изображения
        extra_images = fetch_article_images(item.get('link', ''), item.get('image_url'))
        item['extra_images'] = extra_images if extra_images else []
        
        print("Генерация перевода и поста...")
        post_data = generate_forklog_post(item, gemini_key)
        
        if not post_data:
            print(f"Ошибка: Не удалось сгенерировать пост для статьи '{item['title']}'. Пропускаем её во избежание зависания.")
            save_processed_id(item['id'])
            continue
            
        telegram_caption = post_data["telegram_caption"]
        full_article = post_data["full_article"]
        russian_title = post_data["russian_title"]
        
        # Защита от пустого/короткого текста поста
        MIN_CAPTION_LEN = 80
        if len(telegram_caption) < MIN_CAPTION_LEN:
            print(f"ПРЕДУПРЕЖДЕНИЕ: telegram_caption слишком короткий ({len(telegram_caption)} симв.). Повторная попытка...")
            retry_data = generate_forklog_post(item, gemini_key)
            if retry_data and len(retry_data.get("telegram_caption", "")) >= MIN_CAPTION_LEN:
                telegram_caption = retry_data["telegram_caption"]
                full_article = retry_data.get("full_article", full_article)
                russian_title = retry_data.get("russian_title", russian_title)
                print("Повторная генерация успешна.")
            else:
                fallback_title = russian_title or item['title']
                fallback_desc = item.get('description', '')[:600]
                telegram_caption = f"<b>{fallback_title.upper()}</b>\n\n{fallback_desc}"
                print(f"Использован fallback-текст ({len(telegram_caption)} симв.).")
                
        if len(telegram_caption.strip()) < 10:
            print("Ошибка: Текст поста пуст. Пропускаем статью.")
            save_processed_id(item['id'])
            continue

        article_timestamp = int(time.time())
        item['_timestamp'] = article_timestamp
        article_clean_url = f"https://maxtyutin.github.io/cryptochannel/#article-{article_timestamp}"
        telegram_caption += f"\n\n👉 <a href=\"{article_clean_url}\">Читать на Crypto Analytics</a>"
        
        print("\n=== СГЕНЕРИРОВАННЫЙ ПОСТ (TG) ===")
        print(telegram_caption)
        print("\n=== СГЕНЕРИРОВАННАЯ СТАТЬЯ (САЙТ) ===")
        print(full_article[:300] + "...")
        print("============================\n")
        
        with open(OUTPUT_FILE, 'w') as f:
            f.write(f"# Свежая новость от ИИ-редактора\n\n## ДЛЯ TELEGRAM:\n{telegram_caption}\n\n## ДЛЯ САЙТА:\n{full_article}\n\n*Оригинальный источник: {item.get('link', 'Crypto Analytics')}*\n*Картинка: {item.get('image_url', 'нет')}*")
            
        # Поиск картинки
        img_url = item.get('image_url')
        is_bad_img = not img_url or any(x in img_url.lower() for x in ['pixel', 'tracker', 'ad-button', 'placeholder', 'spacer'])
        if is_bad_img:
            print("[news_engine] Картинка в RSS отсутствует/некорректна. Ищем og:image...")
            og_image = fetch_og_image(item.get('link', ''))
            if og_image:
                item['image_url'] = og_image
                print(f"[news_engine] Найдена обложка через og:image: {og_image}")
                
        local_img_path = None
        if item.get('image_url'):
            if item['image_url'].startswith('http'):
                is_tweet = False
                title_lower = item['title'].lower()
                desc_lower = item.get('description', '').lower()
                if 'tweet' in title_lower or 'on x' in title_lower or 'on twitter' in title_lower or 'tweet' in desc_lower or 'on x' in desc_lower:
                    is_tweet = True
                    
                if is_tweet:
                    print("Обнаружена новость о твите. Генерация скриншота...")
                    tweet_details = extract_tweet_details(item['title'], item.get('description', ''), gemini_key)
                    if tweet_details:
                        safe_id = re.sub(r'[^\w\-_\.]', '_', item['id'])
                        tweet_filename = f"images/tweet_{safe_id}.jpg"
                        tweet_abs_path = os.path.join(BASE_DIR, tweet_filename)
                        if draw_tweet_card(tweet_details, tweet_abs_path):
                            local_img_path = tweet_abs_path
                            item['image_url'] = f"./{tweet_filename}"
                            print(f"Скриншот твита сгенерирован: {item['image_url']}")
                            
                if not local_img_path:
                    print(f"Скачивание и обработка изображения: {item['image_url']}...")
                    img_result = download_and_standardize_image(item['image_url'], item['id'])
                    if img_result:
                        local_img_path = img_result["local_path"]
                        item['image_url'] = img_result["relative_url"]
            else:
                local_img_path = os.path.join(BASE_DIR, item['image_url'].replace('./', ''))
                
        # Если изображения нет, генерируем фирменную обложку
        if not local_img_path:
            print("[news_engine] Изображение отсутствует. Генерируем фирменную обложку...")
            safe_id = re.sub(r'[^\w\-_\.]', '_', item['id'])
            fallback_filename = f"images/fallback_{safe_id}.jpg"
            fallback_abs_path = os.path.join(BASE_DIR, fallback_filename)
            if generate_title_card(item['title'], fallback_abs_path):
                local_img_path = fallback_abs_path
                item['image_url'] = f"./{fallback_filename}"
                
        # 1. Сохраняем статью в базу данных и отмечаем как обработанную
        save_processed_id(item['id'])
        save_recent_topic(item['title'])
        save_article_to_json(item, full_article, russian_title, category=category)
        print("[news_engine] Статья успешно сохранена в базу данных (articles.json).")
        
        # 2. Выполняем авто-пуш на GitHub, чтобы запустить сборку сайта
        pat = os.environ.get("GITHUB_PAT") or env.get("GITHUB_PAT")
        if pat:
            import datetime
            push_time_utc = datetime.datetime.utcnow().replace(microsecond=0)
            print("[news_engine] Обнаружен GITHUB_PAT, отправляем изменения на GitHub...")
            repo_url = f"https://maxtyutin:{pat}@github.com/maxtyutin/cryptochannel.git"
            try:
                subprocess.run(["git", "remote", "set-url", "origin", repo_url], check=False)
                subprocess.run(["git", "config", "user.name", "Render Bot"], check=False)
                subprocess.run(["git", "config", "user.email", "render-bot@example.com"], check=False)
                subprocess.run(["git", "add", "processed_news.txt", "published_topics.txt", "articles.json", "images/"], check=False)
                subprocess.run(["git", "commit", "-m", "Auto-update database from Render [skip ci]"], check=False)
                subprocess.run(["git", "push", "origin", "HEAD:main"], check=False)
                
                print("[news_engine] Изменения успешно отправлены на GitHub! Запуск отслеживания сборки сайта...")
                wait_for_pages_build(pat, push_time_utc)
            except Exception as e:
                print(f"[news_engine] Ошибка при отправке на GitHub или отслеживании сборки: {e}")
        else:
            print("[news_engine] GITHUB_PAT не задан, пропуск отправки на GitHub.")
            
        # 3. Отправляем пост в Telegram
        if bot_token and chat_id:
            print("Отправка поста в Telegram-канал...")
            success = False
            
            if local_img_path:
                print(f"Отправка локально обработанного изображения: {local_img_path}...")
                success = send_photo_to_telegram(telegram_caption, local_img_path, bot_token, chat_id)
                if success:
                    print("Успешно опубликовано со стандартизированным изображением!")
                    
            if not success and item.get('image_url') and item['image_url'].startswith('http'):
                print(f"Попытка отправить пост с оригинальным URL: {item['image_url']}...")
                success = send_photo_to_telegram(telegram_caption, item['image_url'], bot_token, chat_id)
                if success:
                    print("Успешно опубликовано с изображением по внешней ссылке!")
                    
            if not success:
                print("Не удалось отправить изображение. Отправка текстом...")
                success = send_to_telegram(telegram_caption, bot_token, chat_id)
                if success:
                    print("Пост успешно опубликован в Telegram (текстом)!")
                else:
                    print("Критическая ошибка: не удалось отправить пост в Telegram.")
        else:
            print("TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не установлены. Пропуск публикации в Telegram.")
            
        published_any = True
        break
        
    if not published_any:
        print("Все новые новости оказались семантическими дубликатами или завершились ошибкой при генерации.")

if __name__ == "__main__":
    main()
