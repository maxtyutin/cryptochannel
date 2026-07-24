import os
import sys
import json
import time
import urllib.request
import re
from PIL import Image

BASE_DIR = "/Users/maxtyutin/antigravity/Cryptochannel"
sys.path.append(BASE_DIR)
from news_engine import load_env, call_gemini_api, send_photo_to_telegram, save_processed_id, is_russian_title_duplicate

env = load_env()
gemini_key = env.get("GEMINI_API_KEY")
bot_token = env.get("TELEGRAM_BOT_TOKEN")
chat_id = env.get("TELEGRAM_CHAT_ID")
apify_token = os.environ.get("APIFY_API_TOKEN") or env.get("APIFY_API_TOKEN")

from tweet_template_generator import generate_tweet_card_html
from playwright.sync_api import sync_playwright

def format_count(num):
    """Форматирует числа в стиль X (например 302398 -> 302.4K / 302,4 тыс.)"""
    if not num:
        return "0"
    num = int(num)
    if num >= 1000000:
        return f"{num/1000000:.1f}M".replace('.0', '')
    elif num >= 1000:
        return f"{num/1000:.1f}K".replace('.0', '').replace('.', ',') + " тыс."
    return str(num)

def fetch_vitalik_tweets_from_apify():
    """Получает свежие данные твитов Виталика Бутерина из Apify API"""
    dataset_id = "w0g162dfGxl7oovEG"
    url = f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={apify_token}"
    print(f"[apify_engine] Запрос к Apify API датасету: {dataset_id}...")
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            print(f"[apify_engine] УСПЕХ: Получено {len(data)} твитов из Apify.")
            return data
    except Exception as e:
        print(f"[apify_engine] Ошибка получения данных из Apify: {e}")
        return []

def process_apify_vitalik_tweets():
    tweets = fetch_vitalik_tweets_from_apify()
    if not tweets:
        print("[apify_engine] Твитов не найдено.")
        return False
        
    proc_file = os.path.join(BASE_DIR, "processed_news.txt")
    processed_ids = set()
    if os.path.exists(proc_file):
        with open(proc_file, 'r', encoding='utf-8') as f:
            processed_ids = set(line.strip() for line in f if line.strip())

    for tweet in tweets:
        tweet_id = str(tweet.get("id"))
        if tweet_id in processed_ids:
            continue
            
        print(f"\n[apify_engine] Обработка твита ID {tweet_id}...")
        full_text = tweet.get("text") or tweet.get("fullText") or ""
        author = tweet.get("author", {})
        author_name = author.get("name", "vitalik.eth")
        author_handle = f"@{author.get('userName', 'VitalikButerin')}"
        avatar_url = author.get("profileImageUrl")
        
        replies_cnt = format_count(tweet.get("replyCount", 0))
        retweets_cnt = format_count(tweet.get("retweetCount", 0))
        likes_cnt = format_count(tweet.get("likeCount", 0))
        views_cnt = format_count(tweet.get("viewCount", 0))
        bookmarks_cnt = format_count(tweet.get("bookmarkCount", 0))
        
        # Получаем прикрепленное медиа (если есть)
        attached_media_url = None
        media_list = tweet.get("media", [])
        if media_list and isinstance(media_list, list):
            attached_media_url = media_list[0].get("media_url_https") or media_list[0].get("url")
            
        # 1. Запрос к Gemini для аналитической выжимки на русском для Telegram
        prompt = f"""Ниже 100% оригинальный текст твита Виталика Бутерина из X.com:
"{full_text}"

Твоя задача:
1. Создать броский заголовок 'russian_title' с эмодзи в начале (капсом).
2. Написать лаконичный аналитический пост 'telegram_caption' на русском языке (до 550 символов) с разбором сути предложения Виталика и блоком 'Что это значит для рынка? 🤔'.
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
            print(f"[apify_engine] Блокировка дубликата заголовка: {russian_title}")
            save_processed_id(tweet_id)
            continue

        # 2. Генерируем HTML карточку твита с данными Apify
        html_path = os.path.join(BASE_DIR, f"scratch_tweet_{tweet_id}.html")
        generate_tweet_card_html(
            author_name=author_name,
            author_handle=author_handle,
            avatar_url=avatar_url,
            date_str="21 июл. 2026 г.",
            tweet_text_en=full_text,
            attached_img_url=attached_media_url,
            views_str=views_cnt,
            comments_cnt=replies_cnt,
            retweets_cnt=retweets_cnt,
            likes_cnt=likes_cnt,
            bookmarks_cnt=bookmarks_cnt,
            output_html_path=html_path
        )

        # 3. Рендерим HTML в Retina 2K PNG через Playwright
        card_png_path = os.path.join(BASE_DIR, f"images/apify_tweet_{tweet_id}.png")
        os.makedirs(os.path.dirname(card_png_path), exist_ok=True)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(device_scale_factor=2)
            page = context.new_page()
            
            page.goto(f"file://{html_path}", wait_until="load")
            card_el = page.locator('.tweet-card')
            card_el.screenshot(path=card_png_path)
            browser.close()

        print(f"[apify_engine] Идеальная карточка твита создана -> {card_png_path}")

        # 4. Отправляем в Telegram без ссылок
        final_caption = f"<b>{russian_title}</b>\n\n{telegram_caption}"
        if bot_token and chat_id and os.path.exists(card_png_path):
            sent = send_photo_to_telegram(final_caption, card_png_path, bot_token, chat_id)
            if sent:
                print(f"[apify_engine] УСПЕХ: Пост по твиту ID {tweet_id} опубликован в Telegram!")
                save_processed_id(tweet_id)
                return True

if __name__ == "__main__":
    process_apify_vitalik_tweets()
