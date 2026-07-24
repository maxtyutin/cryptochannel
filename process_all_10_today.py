import os
import sys
import json
import time
import urllib.request
import re
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
from news_engine import load_env, call_gemini_api, send_photo_to_telegram, save_processed_id, is_russian_title_duplicate

env = load_env()
gemini_key = env.get("GEMINI_API_KEY")
bot_token = env.get("TELEGRAM_BOT_TOKEN")
chat_id = env.get("TELEGRAM_CHAT_ID")
apify_token = os.environ.get("APIFY_API_TOKEN") or env.get("APIFY_API_TOKEN")

from tweet_template_generator import generate_tweet_card_html, get_base64_avatar_for_user
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
    Строго удаляет весь мусор UI, ссылки вещаний и утекающие счетчики активности типа 4.1K, 31K, 4.7M
    """
    if not text:
        return ""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    clean_lines = []
    for l in lines:
        # Фильтруем чистые числа или числа с K/M (например: 4.1K, 31K, 4.7M, 277K)
        if re.match(r'^\d+(\.\d+)?[KMkmM]?$', l):
            continue
        # Фильтруем служебные строки X UI и трансляций
        if any(x in l for x in ['Replies', 'Retweets', 'Likes', 'Views', 'Bookmarks', 'x.com/i/broadcasts/']):
            continue
        clean_lines.append(l)
    return "\n".join(clean_lines)

def fetch_influencer_tweets_playwright(target):
    username = target["username"]
    name = target["name"]
    url = f"https://x.com/{username}"
    print(f"\n[engine_10] Сканирование постов {name} (@{username})...")
    
    results = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=2)
        pg = ctx.new_page()
        
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=15000)
            pg.wait_for_selector('article', timeout=8000)
            time.sleep(2)
            
            articles = pg.locator('article').all()
            for art in articles[:2]:
                text = art.inner_text()
                
                img_el = art.locator('img[src*="pbs.twimg.com/media"]').first
                attached_img = img_el.get_attribute('src') if img_el.count() > 0 else None
                
                full_text = clean_tweet_text(text)
                if len(full_text) > 15:
                    results.append({
                        "text": full_text,
                        "attached_img": attached_img
                    })
            b.close()
        except Exception as e:
            print(f"[engine_10] Пропуск {name}: {e}")
            b.close()
            
    return results

def process_all_10_today():
    proc_file = os.path.join(BASE_DIR, "processed_news.txt")
    processed_ids = set()
    if os.path.exists(proc_file):
        with open(proc_file, 'r', encoding='utf-8') as f:
            processed_ids = set(line.strip() for line in f if line.strip())

    for target in INFLUENCERS:
        name = target["name"]
        username = target["username"]
        role = target["role"]
        
        tweets = fetch_influencer_tweets_playwright(target)
        if not tweets:
            continue
            
        for idx, tw in enumerate(tweets):
            full_text = clean_tweet_text(tw["text"])
            attached_img = tw["attached_img"]
            
            tweet_hash = f"{username}_{hash(full_text[:40])}"
            if tweet_hash in processed_ids:
                print(f"[engine_10] Уже опубликован твит от {name}")
                continue

            print(f"\n[engine_10] Публикация чистого твита от {name} (@{username})...")

            prompt = f"""Ниже сегодняшняя публикация от {name} ({role}) из X.com:
"{full_text}"

Твоя задача:
1. Создать броский заголовок 'russian_title' с эмодзи в начале, подчеркивающий автора (например: '⚡️ ИЛОН МАСК О БУДУЩЕМ ИИ').
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
                print(f"[engine_10] Пропуск дубликата: {russian_title}")
                save_processed_id(tweet_hash)
                continue

            html_path = os.path.join(BASE_DIR, f"scratch_tweet_{username}_{idx}.html")
            generate_tweet_card_html(
                author_name=name,
                author_handle=f"@{username}",
                avatar_url=None,
                date_str="24 июл. 2026 г.",
                tweet_text_en=full_text,
                attached_img_url=attached_img,
                views_str="190 тыс.",
                comments_cnt="240",
                retweets_cnt="180",
                likes_cnt="2,5 тыс.",
                bookmarks_cnt="210",
                output_html_path=html_path
            )

            card_png_path = os.path.join(BASE_DIR, f"images/clean_card_{username}_{idx}.png")
            os.makedirs(os.path.dirname(card_png_path), exist_ok=True)

            with sync_playwright() as p:
                b = p.chromium.launch(headless=True)
                ctx = b.new_context(device_scale_factor=2)
                pg = ctx.new_page()
                pg.goto(f"file://{html_path}", wait_until="load")
                card_el = pg.locator('.tweet-card')
                card_el.screenshot(path=card_png_path)
                b.close()

            final_caption = f"<b>{russian_title}</b>\n\n{telegram_caption}"
            if bot_token and chat_id and os.path.exists(card_png_path):
                sent = send_photo_to_telegram(final_caption, card_png_path, bot_token, chat_id)
                if sent:
                    print(f"[SUCCESS] Чистый твит от {name} БЕЗ МУСОРНЫХ ЦИФР опубликован!")
                    save_processed_id(tweet_hash)
                    time.sleep(2)
                    break

if __name__ == "__main__":
    process_all_10_today()
