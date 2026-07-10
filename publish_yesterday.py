import os
import sys
import json
import urllib.request
import xml.etree.ElementTree as ET
import re
import datetime
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROCESSED_FILE = os.path.join(BASE_DIR, "processed_news.txt")
JSON_PATH = os.path.join(BASE_DIR, "articles.json")
TOPICS_FILE = os.path.join(BASE_DIR, "published_topics.txt")

# Принудительно используем gemini-3.1-flash-lite, так как у нее лимит 500 запросов в день
PREFERRED_MODEL = "gemini-3.1-flash-lite"

FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
    "Blockworks": "https://blockworks.com/feed",
    "CryptoSlate": "https://cryptoslate.com/feed",
    "Bitcoin News": "https://news.bitcoin.com/feed/",
    "Crypto Briefing": "https://cryptobriefing.com/feed",
}

def load_env():
    env = {}
    env_file = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    key, val = line.strip().split('=', 1)
                    env[key.strip()] = val.strip()
    return env

def get_processed_ids():
    ids = set()
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, 'r') as f:
            ids.update(line.strip() for line in f if line.strip())
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, 'r', encoding='utf-8') as f:
                articles = json.load(f)
            for a in articles:
                if a.get('id'):
                    ids.add(a['id'])
        except Exception:
            pass
    return ids

def parse_date(date_str):
    for fmt in [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S"
    ]:
        try:
            return datetime.datetime.strptime(date_str.strip(), fmt)
        except Exception:
            continue
    return None

def call_gemini_lite(prompt, gemini_key):
    """Делает запрос к Gemini API строго используя модель 3.1-flash-lite"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{PREFERRED_MODEL}:generateContent?key={gemini_key}"
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            res = json.loads(response.read().decode('utf-8'))
            return res['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        print(f"Ошибка запроса к {PREFERRED_MODEL}: {e}")
        return None

def generate_post(news_item, gemini_key):
    prompt = f"""Ты — профессиональный крипто-журналист и редактор Crypto Analytics.
На основе следующей новости напиши заголовок и две версии статьи на русском языке:
Источник: {news_item['source']}
Заголовок: {news_item['title']}
Описание: {news_item['description']}

ПРАВИЛО: КАТЕГОРИЧЕСКИ запрещено использовать или упоминать название ForkLog, CoinDesk, Cointelegraph, Decrypt. Пиши только от лица Crypto Analytics.
ПРАВИЛО ИСТОЧНИКОВ: В качестве авторитетных источников данных, ончейн-метрик или финансирования старайся ссылаться на такие платформы как The Block и Allium.
ПРАВИЛО ЦИТАТ: Оформляй цитаты через <blockquote>Текст цитаты</blockquote>.
ПРАВИЛО ДЛИНЫ: Текст telegram_caption должен быть не более 800 символов.

Верни результат СТРОГО в формате JSON:
{{
  "russian_title": "Заголовок для веб-сайта на русском языке",
  "telegram_caption": "Краткий пересказ для Telegram-канала с заголовком КАПСОМ в начале и эмодзи. Хэштеги запрещены. Разрешены HTML-теги <b>, <a>, <blockquote>.",
  "full_article": "Полная, детальная статья для веб-сайта (около 1500-2500 символов). Разрешены HTML-теги <b>, <a>, <i>, <blockquote>."
}}
"""
    response_json = call_gemini_lite(prompt, gemini_key)
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
        print(f"Ошибка парсинга JSON: {e}")
        return None

def download_image(url, news_id):
    import subprocess
    safe_id = re.sub(r'[^\w\-_\.]', '_', news_id)
    filename = f"images/article_{safe_id}.jpg"
    temp_path = os.path.join(BASE_DIR, f"images/temp_{safe_id}.jpg")
    final_path = os.path.join(BASE_DIR, filename)
    
    os.makedirs(os.path.join(BASE_DIR, "images"), exist_ok=True)
    
    ua = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    cmd = ['curl', '-s', '-L', '-A', ua, '-o', temp_path, url]
    
    try:
        subprocess.run(cmd, timeout=20, check=True)
        # Обрабатываем Pillow
        from PIL import Image
        img = Image.open(temp_path)
        img = img.convert('RGB')
        img.thumbnail((1200, 675))
        img.save(final_path, 'JPEG', quality=85)
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return {"local_path": final_path, "relative_url": f"./{filename}"}
    except Exception as e:
        print(f"Не удалось скачать картинку {url}: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return None

def send_photo_to_telegram(caption, img_path, bot_token, chat_id):
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    try:
        import requests
    except ImportError:
        import subprocess
        sys.exit(1)
        
    if len(caption) > 1024:
        caption = caption[:1020] + "..."
        
    try:
        with open(img_path, 'rb') as f:
            files = {'photo': f}
            data = {'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML'}
            r = requests.post(url, files=files, data=data, timeout=30)
            return r.json().get("ok", False)
    except Exception as e:
        print(f"Ошибка отправки фото: {e}")
        return False

def send_text_to_telegram(text, bot_token, chat_id):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            res = json.loads(response.read().decode('utf-8'))
            return res.get("ok", False)
    except Exception as e:
        print(f"Ошибка отправки текста: {e}")
        return False

def save_article_to_json(item, full_article, russian_title, category="news"):
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    articles = []
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, 'r', encoding='utf-8') as f:
                articles = json.load(f)
        except Exception:
            articles = []
            
    if any(a.get('id') == item['id'] for a in articles):
        return
        
    ts = item.get('_timestamp', int(time.time()))
    new_article = {
        "id": str(ts),
        "title": russian_title,
        "source": item['source'],
        "link": item['link'],
        "image_url": item['image_url'],
        "extra_images": item.get('extra_images', []),
        "post_text": full_article,
        "category": category,
        "date": datetime.datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M"),
        "timestamp": ts
    }
    articles.insert(0, new_article)
    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)

def save_processed_id(news_id):
    with open(PROCESSED_FILE, 'a') as f:
        f.write(news_id + "\n")

def save_recent_topic(title):
    try:
        with open(TOPICS_FILE, 'a', encoding='utf-8') as f:
            f.write(title + "\n")
    except Exception:
        pass

def find_missing_news():
    processed_ids = get_processed_ids()
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    missing_items = []
    
    target_date = datetime.date(2026, 7, 9)
    
    for source, url in FEEDS.items():
        print(f"Сканируем {source}...")
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                xml_data = resp.read()
            
            xml_str = xml_data.decode('utf-8', errors='ignore')
            items = re.findall(r'<item>(.*?)</item>', xml_str, re.DOTALL)
            for item_str in items:
                title_match = re.search(r'<title>(.*?)</title>', item_str, re.DOTALL)
                link_match = re.search(r'<link>(.*?)</link>', item_str, re.DOTALL)
                pub_date_match = re.search(r'<pubDate>(.*?)</pubDate>', item_str, re.DOTALL)
                desc_match = re.search(r'<description>(.*?)</description>', item_str, re.DOTALL)
                
                title = title_match.group(1).strip() if title_match else ""
                link = link_match.group(1).strip() if link_match else ""
                pub_date_str = pub_date_match.group(1).strip() if pub_date_match else ""
                desc = desc_match.group(1).strip() if desc_match else ""
                
                for pattern in [r'<!\[CDATA\[(.*?)\]\]>', r'<!\[CDATA\[(.*)']:
                    title_c = re.search(pattern, title, re.DOTALL)
                    if title_c: title = title_c.group(1).strip()
                    link_c = re.search(pattern, link, re.DOTALL)
                    if link_c: link = link_c.group(1).strip()
                    desc_c = re.search(pattern, desc, re.DOTALL)
                    if desc_c: desc = desc_c.group(1).strip()
                
                news_id = link if link else title
                if news_id in processed_ids:
                    continue
                    
                pdate = parse_date(pub_date_str)
                if pdate and pdate.date() == target_date:
                    img_match = re.search(r'<media:content[^>]+url=["\']([^"\']+)["\']', item_str)
                    if not img_match:
                        img_match = re.search(r'<enclosure[^>]+url=["\']([^"\']+)["\']', item_str)
                    if not img_match:
                        img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', item_str)
                    if not img_match:
                        img_match = re.search(r'(https?://[^\s"\']+\.(?:jpg|jpeg|png|webp))', item_str)
                        
                    image_url = img_match.group(1).replace('&amp;', '&') if img_match else None
                    desc_clean = re.sub(r'<[^>]*>', '', desc)
                    
                    missing_items.append({
                        "id": news_id,
                        "source": source,
                        "title": title,
                        "description": desc_clean.strip(),
                        "link": link,
                        "image_url": image_url,
                        "date": pdate
                    })
        except Exception as e:
            print(f"Ошибка при сканировании {source}: {e}")
            
    missing_items.sort(key=lambda x: x['date'])
    return missing_items

def main():
    env = load_env()
    gemini_key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    bot_token = env.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")
    
    if not gemini_key or not bot_token or not chat_id:
        print("Ошибка: не настроены ключи API!")
        return

    items = find_missing_news()
    print(f"Найдено {len(items)} пропущенных новостей за вчерашний день.")
    
    published_count = 0
    for i, item in enumerate(items):
        print(f"\n[{i+1}/{len(items)}] Публикуем (в базу сайта): {item['title']}")
        
        post_data = generate_post(item, gemini_key)
        if not post_data:
            print("Пропуск новости из-за ошибки генерации.")
            continue
            
        telegram_caption = post_data["telegram_caption"]
        full_article = post_data["full_article"]
        russian_title = post_data["russian_title"]
        
        yesterday_ts = int(time.mktime(item['date'].timetuple()))
        item['_timestamp'] = yesterday_ts
        
        article_clean_url = f"https://maxtyutin.github.io/cryptochannel/#article-{yesterday_ts}"
        telegram_caption += f"\n\n👉 <a href=\"{article_clean_url}\">Читать на Crypto Analytics</a>"
        
        local_img_path = None
        if item.get('image_url'):
            print(f"Скачиваем картинку: {item['image_url']}")
            img_res = download_image(item['image_url'], item['id'])
            if img_res:
                local_img_path = img_res["local_path"]
                item['image_url'] = img_res["relative_url"]
        
        # Публикуем (имитируем успех отправки в TG, чтобы не было дублей в канале)
        success = True
            
        if success:
            print("Успешно обработано для сайта!")
            save_article_to_json(item, full_article, russian_title)
            save_processed_id(item['id'])
            save_recent_topic(item['title'])
            published_count += 1
        else:
            print("Ошибка обработки.")
            
        time.sleep(8)
        
    print(f"\nГотово! Успешно перенесено {published_count} постов на сайт.")

if __name__ == "__main__":
    main()
