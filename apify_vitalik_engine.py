import os
import sys
import json
import time
import urllib.request
import re
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
from news_engine import load_env, call_gemini_api, send_photo_to_telegram, save_processed_id, is_russian_title_duplicate

env = load_env()
gemini_key = env.get("GEMINI_API_KEY")
bot_token = env.get("TELEGRAM_BOT_TOKEN")
chat_id = env.get("TELEGRAM_CHAT_ID")
apify_token = os.environ.get("APIFY_API_TOKEN") or env.get("APIFY_API_TOKEN")

from tweet_template_generator import generate_tweet_card_html
from playwright.sync_api import sync_playwright

INFLUENCERS = [
    {"username": "VitalikButerin", "name": "vitalik.eth", "role": "Создатель Ethereum"},
    {"username": "saylor", "name": "Michael Saylor", "role": "Глава MicroStrategy"},
    {"username": "cz_binance", "name": "CZ 🔶 Binance", "role": "Основатель Binance"},
    {"username": "brian_armstrong", "name": "Brian Armstrong", "role": "CEO Coinbase"},
    {"username": "elonmusk", "name": "Elon Musk", "role": "Глава X & Tesla"},
    {"username": "aeyakovenko", "name": "Anatoly Yakovenko", "role": "Основатель Solana"},
    {"username": "CryptoHayes", "name": "Arthur Hayes", "role": "Основатель BitMEX"},
    {"username": "paoloardoino", "name": "Paolo Ardoino", "role": "CEO Tether (USDT)"},
    {"username": "justinsuntron", "name": "Justin Sun", "role": "Основатель TRON"},
    {"username": "IOHK_Charles", "name": "Charles Hoskinson", "role": "Создатель Cardano"}
]

def format_count(num):
    if not num:
        return "0"
    num = int(num)
    if num >= 1000000:
        return f"{num/1000000:.1f}M".replace('.0', '')
    elif num >= 1000:
        return f"{num/1000:.1f}K".replace('.0', '').replace('.', ',') + " тыс."
    return str(num)

def clean_tweet_text(text):
    """
    Удаляет весь лишний мусор UI, ссылки вещаний и утекающие счетчики типа 4.1K, 31K, 4.7M
    """
    if not text:
        return ""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    clean_lines = []
    for l in lines:
        # Фильтруем чистые числа или числа с K/M (например: 4.1K, 31K, 4.7M, 277K)
        if re.match(r'^\d+(\.\d+)?[KMkmM]?$', l):
            continue
        # Фильтруем служебные строки X UI
        if any(x in l for x in ['Replies', 'Retweets', 'Likes', 'Views', 'Bookmarks', 'x.com/i/broadcasts/']):
            continue
        clean_lines.append(l)
    return "\n".join(clean_lines)

def fetch_top10_tweets_from_apify():
    dataset_id = "w0g162dfGxl7oovEG"
    url = f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={apify_token}"
    print(f"[influencers_engine] Получение данных твитов через Apify API...")
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            print(f"[influencers_engine] УСПЕХ: Загружено {len(data)} постов.")
            return data
    except Exception as e:
        print(f"[influencers_engine] Ошибка Apify: {e}")
        return []

def process_influencers_feed():
    tweets = fetch_top10_tweets_from_apify()
    if not tweets:
        return False
        
    proc_file = os.path.join(BASE_DIR, "processed_news.txt")
    processed_ids = set()
    if os.path.exists(proc_file):
        with open(proc_file, 'r', encoding='utf-8') as f:
            processed_ids = set(line.strip() for line in f if line.strip())

    published_count = 0
    for tweet in tweets:
        tweet_id = str(tweet.get("id"))
        if tweet_id in processed_ids:
            continue
            
        raw_text = tweet.get("text") or tweet.get("fullText") or ""
        full_text = clean_tweet_text(raw_text)
        if not full_text or len(full_text) < 10:
            continue

        author = tweet.get("author", {})
        author_username = author.get("userName", "")
        author_name = author.get("name", author_username)
        author_handle = f"@{author_username}"
        avatar_url = author.get("profileImageUrl")
        
        matched_inf = next((x for x in INFLUENCERS if x["username"].lower() == author_username.lower()), None)
        author_role = matched_inf["role"] if matched_inf else "Крипто-эксперт"

        print(f"\n[influencers_engine] Обработка твита {author_name} ({author_handle}): {full_text[:70]}...")

        replies_cnt = format_count(tweet.get("replyCount", 0))
        retweets_cnt = format_count(tweet.get("retweetCount", 0))
        likes_cnt = format_count(tweet.get("likeCount", 0))
        views_cnt = format_count(tweet.get("viewCount", 0))
        bookmarks_cnt = format_count(tweet.get("bookmarkCount", 0))
        
        attached_media_url = None
        media_list = tweet.get("media", [])
        if media_list and isinstance(media_list, list):
            attached_media_url = media_list[0].get("media_url_https") or media_list[0].get("url")
            
        # 1. Запрос к ИИ для создания русскоязычного аналитического поста для Telegram
        prompt = f"""Ниже свежий оригинальный твит от {author_name} ({author_role}) из X.com:
"{full_text}"

Твоя задача:
1. Создать заголовок 'russian_title' с эмодзи в начале, подчеркивающий автора (например: '⚡️ ИЛОН МАСК О БУДУЩЕМ ИИ').
2. Написать лаконичный аналитический пост 'telegram_caption' на русском языке (до 550 символов) с разбором смысла и блоком 'Что это значит для рынка? 🤔'.
КАТЕГОРИЧЕСКИ НЕ ДОБАВЛЯЙ никаких ссылок на оригинальный твит или X.com!

Верни JSON с ключами russian_title и telegram_caption.
"""
        res_json = call_gemini_api(prompt, gemini_key, is_json=True)
        clean_json = res_json.strip()
        if clean_json.startswith("```"):
            start = clean_json.find("{")
            end = clean_json.rfind("}")
            if start != -1 and end != -1:
                clean_json = clean_json[start:end+1]
        parsed = json.loads(clean_json)

        russian_title = parsed["russian_title"]
        telegram_caption = parsed["telegram_caption"]

        if is_russian_title_duplicate(russian_title):
            print(f"[influencers_engine] Пропуск дубликата: {russian_title}")
            save_processed_id(tweet_id)
            continue

        # 2. Рендеринг карточки твита
        html_path = os.path.join(BASE_DIR, f"scratch_tweet_{tweet_id}.html")
        generate_tweet_card_html(
            author_name=author_name,
            author_handle=author_handle,
            avatar_url=avatar_url,
            date_str="24 июл. 2026 г.",
            tweet_text_en=full_text,
            attached_img_url=attached_media_url,
            views_str=views_cnt,
            comments_cnt=replies_cnt,
            retweets_cnt=retweets_cnt,
            likes_cnt=likes_cnt,
            bookmarks_cnt=bookmarks_cnt,
            output_html_path=html_path
        )

        card_png_path = os.path.join(BASE_DIR, f"images/influencer_tweet_{tweet_id}.png")
        os.makedirs(os.path.dirname(card_png_path), exist_ok=True)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(device_scale_factor=2)
            page = context.new_page()
            
            page.goto(f"file://{html_path}", wait_until="load")
            card_el = page.locator('.tweet-card')
            card_el.screenshot(path=card_png_path)
            browser.close()

        # 3. Публикация в Telegram
        final_caption = f"<b>{russian_title}</b>\n\n{telegram_caption}"
        if bot_token and chat_id and os.path.exists(card_png_path):
            sent = send_photo_to_telegram(final_caption, card_png_path, bot_token, chat_id)
            if sent:
                print(f"[influencers_engine] УСПЕХ: Чистая карточка твита от {author_name} опубликована в Telegram!")
                save_processed_id(tweet_id)
                published_count += 1

if __name__ == "__main__":
    process_influencers_feed()
