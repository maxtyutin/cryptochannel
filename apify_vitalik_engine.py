import os
import sys
import json
import time
import urllib.request
import re
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
from news_engine import load_env, call_gemini_api, send_photo_to_telegram, send_to_telegram, save_processed_id, is_russian_title_duplicate

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
    if not text:
        return ""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    clean_lines = []
    for l in lines:
        if re.match(r'^\d+(\.\d+)?[KMkmM]?$', l):
            continue
        if any(x in l for x in ['Replies', 'Retweets', 'Likes', 'Views', 'Bookmarks', 'x.com/i/broadcasts/']):
            continue
        clean_lines.append(l)
    res = "\n".join(clean_lines)
    res = re.sub(r'https?://t\.co/\S+', '', res)
    return res.strip()

def fetch_untruncated_tweet_text(pg, username, tweet_id, fallback_text):
    if not tweet_id or tweet_id.startswith("pw_"):
        return fallback_text
    try:
        url = f"https://x.com/{username}/status/{tweet_id}"
        pg.goto(url, wait_until="domcontentloaded", timeout=15000)
        pg.wait_for_selector('article', timeout=10000)
        time.sleep(1)

        art = pg.locator('article').first
        try:
            sm = art.locator('[data-testid="tweet-text-show-more-link"]')
            if sm.count() > 0:
                sm.first.click(timeout=1000)
                time.sleep(0.3)
        except Exception:
            pass

        full_txt = art.locator('[data-testid="tweetText"]').first.inner_text(timeout=3000)
        full_txt = clean_tweet_text(full_txt)
        if full_txt and len(full_txt) >= len(fallback_text):
            print(f"[playwright] @{username}: Получен 100% полный текст твита ({len(full_txt)} символов)")
            return full_txt
    except Exception as e:
        print(f"[playwright] Не удалось загрузить прямую страницу твита {tweet_id}: {e}")
    return fallback_text

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
    Собирает по 1 свежему твиту от каждого инфлюенсера через ОДИН Playwright браузер.
    Один браузер на всех = в 3-4 раза быстрее.
    """
    print(f"[influencers_engine] Playwright-скрейпинг {len(INFLUENCERS)} инфлюенсеров (единый браузер)...")
    tweets = []

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(
            viewport={"width": 1280, "height": 900},
            device_scale_factor=2,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        # Устанавливаем куки авторизации один раз для всего контекста
        if twitter_auth_token and twitter_ct0:
            ctx.add_cookies([
                {"name": "auth_token", "value": twitter_auth_token, "domain": ".x.com", "path": "/"},
                {"name": "ct0", "value": twitter_ct0, "domain": ".x.com", "path": "/"},
            ])
            print(f"[influencers_engine] Куки авторизации установлены глобально")

        pg = ctx.new_page()

        for inf in INFLUENCERS:
            username = inf["username"]
            print(f"[influencers_engine] Получаем @{username}...")
            try:
                pg.goto(f"https://x.com/{username}", wait_until="domcontentloaded", timeout=20000)
                pg.wait_for_selector('article', timeout=15000)
                time.sleep(2)

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
                                print(f"[playwright] @{username}: пропускаем Pinned #{i}")
                                continue
                    except Exception:
                        pass

                    # Раскрываем "Show more"
                    try:
                        show_more = art.locator('[data-testid="tweet-text-show-more-link"]')
                        if show_more.count() > 0:
                            show_more.first.click(timeout=2000)
                            time.sleep(0.5)
                    except Exception:
                        pass

                    # Текст твита
                    raw_text = ""
                    try:
                        raw_text = art.locator('[data-testid="tweetText"]').first.inner_text(timeout=5000)
                    except Exception:
                        pass
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

                    # ID твита (фильтруем ретвиты других пользователей)
                    tweet_id = None
                    try:
                        link_el = art.locator(f'a[href*="/{username}/status/"]').first
                        if link_el.count() > 0:
                            href = link_el.get_attribute('href', timeout=2000) or ""
                            if "/status/" in href:
                                tweet_id = href.split("/status/")[-1].split("?")[0]
                    except Exception:
                        pass

                    if not tweet_id:
                        print(f"[playwright] @{username}: пропускаем чужой ретвит #{i}")
                        continue

                    # Счётчики активности
                    replies_cnt = "0"
                    retweets_cnt = "0"
                    likes_cnt = "0"
                    try:
                        rep_el = art.locator('[data-testid="reply"]').first
                        if rep_el.count() > 0: replies_cnt = rep_el.inner_text(timeout=1000) or "0"
                    except Exception: pass
                    try:
                        ret_el = art.locator('[data-testid="retweet"]').first
                        if ret_el.count() > 0: retweets_cnt = ret_el.inner_text(timeout=1000) or "0"
                    except Exception: pass
                    try:
                        lik_el = art.locator('[data-testid="like"]').first
                        if lik_el.count() > 0: likes_cnt = lik_el.inner_text(timeout=1000) or "0"
                    except Exception: pass

                    # Получаем 100% полный текст без обрезки через прямую страницу статуса твита
                    if tweet_id and not tweet_id.startswith("pw_"):
                        raw_text = fetch_untruncated_tweet_text(pg, username, tweet_id, raw_text)

                    result = {
                        "id": tweet_id,
                        "text": raw_text,
                        "media_url": media_url,
                        "username": username,
                        "inf_name": inf["name"],
                        "inf_role": inf["role"],
                        "likes": likes_cnt,
                        "retweets": retweets_cnt,
                        "replies": replies_cnt
                    }
                    print(f"[playwright] @{username}: твит найден #{i}, ID={tweet_id} | ❤️ {likes_cnt} | 🔁 {retweets_cnt} | 💬 {replies_cnt}")
                    break

                if result:
                    tweets.append(result)
                    print(f"[influencers_engine] ✓ @{username}: {result['text'][:60]}...")
                else:
                    print(f"[influencers_engine] ✗ @{username}: твит не найден")

            except Exception as e:
                print(f"[influencers_engine] Ошибка @{username}: {e}")

        b.close()

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

        replies_cnt = tweet.get("replies", "0")
        retweets_cnt = tweet.get("retweets", "0")
        likes_cnt = tweet.get("likes", "0")

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

        # 2. Рендеринг карточки-мокапа твита в стиле Twitter с реальным аватаром и счётчиками
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
            views_str="",
            comments_cnt=replies_cnt,
            retweets_cnt=retweets_cnt,
            likes_cnt=likes_cnt,
            bookmarks_cnt="",
            output_html_path=html_path
        )

        card_png_path = os.path.join(BASE_DIR, f"images/influencer_tweet_{tweet_id}.png")
        os.makedirs(os.path.dirname(card_png_path), exist_ok=True)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(device_scale_factor=2)
            page = context.new_page()
            page.goto(f"file://{html_path}", wait_until="networkidle", timeout=10000)
            page.wait_for_timeout(1000)
            card_el = page.locator('.tweet-card')
            if card_el.count() > 0:
                card_el.screenshot(path=card_png_path)
            else:
                page.screenshot(path=card_png_path, full_page=True)
            browser.close()

        # 3. Публикация карточки-мокапа с аналитическим текстом в Telegram
        final_caption = f"<b>{russian_title}</b>\n\n{telegram_caption}"
        if bot_token and chat_id and os.path.exists(card_png_path) and os.path.getsize(card_png_path) > 1000:
            sent = send_photo_to_telegram(final_caption, card_png_path, bot_token, chat_id)
            if sent:
                print(f"[influencers_engine] УСПЕХ: Мокап твита {author_name} (аватар + лайки/ретвиты/комменты) опубликован в Telegram!")
                save_processed_id(tweet_id)
                save_processed_id_to_supabase(tweet_id, author_name)
                published_count += 1
                cleanup_local_temp_images()

if __name__ == "__main__":
    process_influencers_feed()
