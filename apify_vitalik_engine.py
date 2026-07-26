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
twitter_auth_token = os.environ.get("TWITTER_AUTH_TOKEN") or env.get("TWITTER_AUTH_TOKEN", "")
twitter_ct0 = os.environ.get("TWITTER_CT0") or env.get("TWITTER_CT0", "")

from supabase_engine_integration import cleanup_local_temp_images, get_processed_ids_from_supabase, save_processed_id_to_supabase

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

def scrape_latest_tweet_playwright(username):
    """
    Использует Playwright для получения последнего (не закреплённого) твита
    с профиля @username на x.com.
    """
    url = f"https://x.com/{username}"
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            ctx = b.new_context(
                viewport={"width": 1280, "height": 900},
                device_scale_factor=2,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            # Внедряем куки авторизации Twitter
            if twitter_auth_token and twitter_ct0:
                ctx.add_cookies([
                    {"name": "auth_token", "value": twitter_auth_token, "domain": ".x.com", "path": "/"},
                    {"name": "ct0", "value": twitter_ct0, "domain": ".x.com", "path": "/"},
                ])
                print(f"[playwright] @{username}: куки авторизации установлены")
            pg = ctx.new_page()
            pg.goto(url, wait_until="domcontentloaded", timeout=20000)
            # Ждём появления хотя бы одной статьи
            pg.wait_for_selector('article', timeout=15000)
            time.sleep(3)  # Дополнительное ожидание рендера контента

            result = None
            articles = pg.locator('article')
            count = articles.count()
            print(f"[playwright] @{username}: найдено {count} article-элементов")

            for i in range(min(count, 5)):
                art = articles.nth(i)

                # Пропускаем Pinned tweet
                try:
                    pinned = art.locator('[data-testid="socialContext"]')
                    if pinned.count() > 0:
                        ctx_text = pinned.first.inner_text(timeout=1000)
                        if "Pinned" in ctx_text or "Закрепл" in ctx_text:
                            print(f"[playwright] @{username}: пропускаем Pinned твит #{i}")
                            continue
                except Exception:
                    pass

                # Раскрываем "Show more" если есть
                try:
                    show_more = art.locator('[data-testid="tweet-text-show-more-link"]')
                    if show_more.count() > 0:
                        show_more.first.click(timeout=2000)
                        time.sleep(0.5)
                except Exception:
                    pass

                # Пробуем получить текст твита
                raw_text = ""
                try:
                    txt_el = art.locator('[data-testid="tweetText"]').first
                    raw_text = txt_el.inner_text(timeout=5000)
                except Exception:
                    pass

                # Фаллбэк: берём весь inner_text статьи и очищаем
                if not raw_text or len(raw_text.strip()) < 5:
                    try:
                        raw_text = art.inner_text(timeout=3000)
                    except Exception:
                        continue

                raw_text = clean_tweet_text(raw_text)
                if len(raw_text.strip()) < 10:
                    continue

                # Медиа
                media_url = None
                try:
                    img_el = art.locator('img[src*="pbs.twimg.com/media"], img[src*="pbs.twimg.com/card_img"]').first
                    if img_el.count() > 0:
                        media_url = img_el.get_attribute('src', timeout=2000)
                except Exception:
                    pass

                # ID твита из ссылки
                tweet_id = f"pw_{username}_{int(time.time())}"
                try:
                    link_el = art.locator('a[href*="/status/"]').first
                    if link_el.count() > 0:
                        href = link_el.get_attribute('href', timeout=2000) or ""
                        if "/status/" in href:
                            tweet_id = href.split("/status/")[-1].split("?")[0]
                except Exception:
                    pass

                result = {
                    "id": tweet_id,
                    "text": raw_text,
                    "media_url": media_url,
                    "username": username
                }
                print(f"[playwright] @{username}: твит найден в article #{i}, ID={tweet_id}")
                break

            b.close()
            return result
    except Exception as e:
        print(f"[playwright] Ошибка для @{username}: {e}")
        return None


def fetch_all_influencer_tweets():
    """
    Собирает по 1 свежему твиту от каждого инфлюенсера через Playwright.
    """
    print(f"[influencers_engine] Playwright-скрейпинг {len(INFLUENCERS)} инфлюенсеров...")
    tweets = []
    for inf in INFLUENCERS:
        username = inf["username"]
        print(f"[influencers_engine] Получаем @{username}...")
        tweet = scrape_latest_tweet_playwright(username)
        if tweet:
            tweet["inf_name"] = inf["name"]
            tweet["inf_role"] = inf["role"]
            tweets.append(tweet)
            print(f"[influencers_engine] ✓ @{username}: {tweet['text'][:60]}...")
        else:
            print(f"[influencers_engine] ✗ @{username}: твит не найден")
        time.sleep(1)
    print(f"[influencers_engine] Итого собрано: {len(tweets)} твитов.")
    return tweets


def process_influencers_feed():
    cleanup_local_temp_images()
    tweets = fetch_all_influencer_tweets()
    if not tweets:
        return False

    processed_ids = get_processed_ids_from_supabase()

    published_count = 0
    for tweet in tweets:
        tweet_id = str(tweet.get("id"))
        if tweet_id in processed_ids:
            print(f"[influencers_engine] Пропуск уже опубликованного ID {tweet_id}")
            continue

        full_text = tweet.get("text", "")
        if not full_text or len(full_text) < 10:
            continue

        username = tweet.get("username", "")
        author_name = tweet.get("inf_name", username)
        author_role = tweet.get("inf_role", "Крипто-эксперт")
        author_handle = f"@{username}"
        attached_media_url = tweet.get("media_url")

        print(f"\n[influencers_engine] Обработка твита {author_name} ({author_handle}): {full_text[:70]}...")

        # Playwright не возвращает счётчики — используем пустые заглушки
        replies_cnt = ""
        retweets_cnt = ""
        likes_cnt = ""
        views_cnt = ""
        bookmarks_cnt = ""
            
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

        # Пробуем парсить JSON
        parsed = None
        try:
            parsed = json.loads(clean_json)
        except json.JSONDecodeError:
            # Фаллбэк: извлекаем значения регулярками
            try:
                title_m = re.search(r'"russian_title"\s*:\s*"(.*?)"(?=\s*,|\s*})', clean_json, re.DOTALL)
                cap_m = re.search(r'"telegram_caption"\s*:\s*"(.*?)"(?=\s*})', clean_json, re.DOTALL)
                if title_m and cap_m:
                    parsed = {
                        "russian_title": title_m.group(1).replace('\\"', '"'),
                        "telegram_caption": cap_m.group(1).replace('\\"', '"')
                    }
                    print(f"[influencers_engine] JSON парсинг через regex-фаллбэк")
            except Exception:
                pass

        if not parsed:
            print(f"[influencers_engine] Не удалось распарсить JSON для {author_name}, пропускаем")
            continue

        russian_title = parsed["russian_title"]
        telegram_caption = parsed["telegram_caption"]

        if is_russian_title_duplicate(russian_title):
            print(f"[influencers_engine] Пропуск дубликата: {russian_title}")
            save_processed_id(tweet_id)
            continue

        # 2. Рендеринг карточки твита
        html_path = os.path.join(BASE_DIR, f"scratch_tweet_{tweet_id}.html")
        from datetime import datetime
        date_str = datetime.utcnow().strftime("%d %b. %Y г.")
        generate_tweet_card_html(
            author_name=author_name,
            author_handle=author_handle,
            avatar_url=None,
            date_str=date_str,
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
                save_processed_id_to_supabase(tweet_id, author_name)
                published_count += 1
                cleanup_local_temp_images()

if __name__ == "__main__":
    process_influencers_feed()
