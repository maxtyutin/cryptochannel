import os
import json
import urllib.request
import xml.etree.ElementTree as ET
import datetime
import time

# Загрузка env
BASE_DIR = "/Users/maxtyutin/antigravity/TG каналы"
ENV_PATH = os.path.join(BASE_DIR, ".env")

def load_env():
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    k, v = line.strip().split('=', 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env

FEEDS = {
    'CoinDesk': 'https://www.coindesk.com/arc/outboundfeeds/rss',
    'Cointelegraph': 'https://cointelegraph.com/rss',
    'Decrypt': 'https://decrypt.co/feed',
    'Blockworks': 'https://blockworks.com/feed',
    'CryptoSlate': 'https://cryptoslate.com/feed',
    'Bitcoin Magazine': 'https://bitcoinmagazine.com/.rss/full',
    'Bitcoin News': 'https://news.bitcoin.com/feed/',
    'Crypto Briefing': 'https://cryptobriefing.com/feed',
    'BeInCrypto': 'https://beincrypto.com/feed',
    'NewsBTC': 'https://www.newsbtc.com/feed',
    'Glassnode': 'https://insights.glassnode.com/rss',
    'CryptoPanic': 'https://cryptopanic.com/news/rss/'
}

def fetch_all_feed_items():
    items = {}
    for source, url in FEEDS.items():
        print(f"Считывание {source}...")
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as r:
                xml_data = r.read()
            root = ET.fromstring(xml_data)
            
            for item in root.findall('.//item'):
                link = item.find('link').text.strip() if item.find('link') is not None else ""
                title = item.find('title').text.strip() if item.find('title') is not None else ""
                description = ""
                if item.find('description') is not None:
                    description = item.find('description').text or ""
                    
                # Ищем картинку
                image_url = ""
                media_content = item.find('{http://search.yahoo.com/mrss/}content')
                if media_content is not None:
                    image_url = media_content.attrib.get('url', '')
                if not image_url:
                    enclosure = item.find('enclosure')
                    if enclosure is not None:
                        image_url = enclosure.attrib.get('url', '')
                
                if link:
                    items[link] = {
                        "id": link,
                        "title": title,
                        "description": description,
                        "image_url": image_url,
                        "source": source
                    }
        except Exception as e:
            print(f"Ошибка загрузки {source}: {e}")
    return items

GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-pro"
]

def generate_full_article(news_item, gemini_key):
    prompt = f"""Ты — профессиональный крипто-журналист и редактор Crypto Analytics. 
На основе следующей новости напиши полную, детальную, развернутую и информативную статью на русском языке для веб-сайта (объемом около 1500-2500 символов):
Источник: {news_item['source']}
Заголовок: {news_item['title']}
Описание: {news_item['description']}

ПРАВИЛО: КАТЕГОРИЧЕСКИ запрещено упоминать название ForkLog. Пиши только от лица Crypto Analytics.

Напиши в авторитетном, объективном стиле, раскрой предысторию, технические подробности и глубокий рыночный вывод. Разрешены теги <b>, <a>, <i>.
Верни ТОЛЬКО готовый текст статьи без кавычек и вводных фраз.
"""
    data = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }]
    }
    
    last_err = None
    # Пробуем каждую модель по очереди, если лимиты основной исчерпаны
    for model in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
        print(f"Попытка генерации через модель {model}...")
        try:
            req = urllib.request.Request(
                url, 
                data=json.dumps(data).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                print(f"Успешный ответ получен от модели {model}!")
                return result['candidates'][0]['content']['parts'][0]['text'].strip()
        except Exception as e:
            print(f"Модель {model} выдала ошибку: {e}. Переключаемся на резерв...")
            last_err = e
            time.sleep(2)
            
    print(f"Все доступные ИИ-модели выдали ошибки. Последняя: {last_err}")
    return None

def main():
    env = load_env()
    gemini_key = env.get("GEMINI_API_KEY")
    if not gemini_key:
        print("Ошибка: Нет GEMINI_API_KEY")
        return
        
    processed_news_path = os.path.join(BASE_DIR, "processed_news.txt")
    if not os.path.exists(processed_news_path):
        print("Нет опубликованных ссылок.")
        return
        
    with open(processed_news_path, 'r', encoding='utf-8') as f:
        links = [line.strip() for line in f if line.strip()]
        
    if not links:
        print("Список опубликованных новостей пуст.")
        return
        
    print(f"Загружено {len(links)} опубликованных ссылок из processed_news.txt.")
    
    # Считываем все новости из фидов
    feed_items = fetch_all_feed_items()
    
    # Считываем существующие статьи на сайте
    articles_json_path = os.path.join(BASE_DIR, "articles.json")
    existing_articles = []
    if os.path.exists(articles_json_path):
        try:
            with open(articles_json_path, 'r', encoding='utf-8') as f:
                existing_articles = json.load(f)
        except Exception:
            existing_articles = []
            
    existing_ids = {a['id'] for a in existing_articles}
    
    added_count = 0
    # Проходим по ссылкам
    for link in links:
        if link in existing_ids:
            print(f"Статья уже есть на сайте: {link}")
            continue
            
        item = feed_items.get(link)
        if not item:
            # Если статья старая и выпала из RSS, делаем базовый объект из ссылки
            print(f"Статьи нет в текущем RSS (устарела). Создаем базовую информацию...")
            title_part = link.split('/')[-1].replace('-', ' ').title()
            item = {
                "id": link,
                "title": title_part,
                "description": title_part,
                "image_url": "",
                "source": "Архив"
            }
            
        print(f"Генерация статьи для: {item['title']}...")
        full_text = generate_full_article(item, gemini_key)
        
        if full_text:
            article_data = {
                "id": item['id'],
                "title": item['title'],
                "source": item['source'],
                "link": item['id'],
                "image_url": item['image_url'],
                "post_text": full_text,
                "date": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
                "timestamp": int(time.time()) - (added_count * 60) # Смещаем таймштамп назад для сортировки
            }
            existing_articles.append(article_data)
            existing_ids.add(item['id'])
            added_count += 1
            print(f"Статья добавлена в очередь: {item['title']}")
        
        # Пауза между запросами для соблюдения лимитов API (15 секунд для сброса лимита)
        time.sleep(15)
            
    if added_count > 0:
        # Сортируем: новые сверху
        existing_articles.sort(key=lambda x: x['timestamp'], reverse=True)
        with open(articles_json_path, 'w', encoding='utf-8') as f:
            json.dump(existing_articles, f, ensure_ascii=False, indent=2)
        print(f"Успешно добавлено {added_count} архивных статей в articles.json!")
    else:
        print("Нет новых архивных статей для добавления.")

if __name__ == "__main__":
    main()
