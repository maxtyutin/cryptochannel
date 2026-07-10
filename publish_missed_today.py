import json
import os
import sys
import time
import datetime
import urllib.request
import re

# Add current folder to sys.path
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(PROJECT_DIR)

import news_engine

env = news_engine.load_env()
gemini_key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
bot_token = env.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
chat_id = env.get("TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")

if not gemini_key or not bot_token or not chat_id:
    print("[Missed Today] Error: Missing credentials!")
    sys.exit(1)

JSON_PATH = os.path.join(PROJECT_DIR, "articles.json")

def generate_tg_caption(title, post_text):
    prompt = f"""Ты — профессиональный крипто-журналист и редактор Crypto Analytics.
На основе названия статьи и её полного текста на русском языке, напиши краткий Telegram-пост для нашего канала.

ЗАГОЛОВОК СТАТЬИ: {title}
ТЕКСТ СТАТЬИ: {post_text}

ПРАВИЛО ДЛИНЫ TG-ПОСТА: Длина поста КАТЕГОРИЧЕСКИ не должна превышать 800 символов (включая пробелы).
ПРАВИЛА ОФОРМЛЕНИЯ:
- Должен содержать привлекательный заголовок КАПСОМ с эмодзи в начале.
- Лаконичный разбор новости (2-3 абзаца).
- Вывод 'Что это значит для рынка? 🤔'.
- Хэштеги КАТЕГОРИЧЕСКИ запрещены.
- Разрешены только HTML-теги: <b>, <a>, и <blockquote> (для цитат). Не используй другие теги.

Верни результат в формате JSON с одним ключом:
{{
  "telegram_caption": "текст поста для Телеграма"
}}
"""
    try:
        response_json = news_engine.call_gemini_api(prompt, gemini_key, is_json=True)
        if response_json:
            parsed = json.loads(response_json)
            return parsed.get("telegram_caption", "").strip()
    except Exception as e:
        print(f"[Missed Today] Error generating caption: {e}")
    return None

def download_image_from_live_site(image_url):
    """Пытается скачать картинку с GitHub Pages, если её нет локально"""
    if not image_url or image_url.startswith("http"):
        return None
        
    filename = image_url.replace("./", "")
    local_path = os.path.join(PROJECT_DIR, filename)
    
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return local_path
        
    # Ссылка на лайв сайт
    live_url = f"https://maxtyutin.github.io/cryptochannel/{filename}"
    print(f"[Missed Today] Попытка скачать изображение с GitHub Pages: {live_url}...")
    try:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
        req = urllib.request.Request(live_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            with open(local_path, 'wb') as f:
                f.write(response.read())
        print(f"[Missed Today] Изображение успешно скачано с сайта: {local_path}")
        return local_path
    except Exception as e:
        print(f"[Missed Today] Не удалось скачать с сайта: {e}")
    return None

def main():
    if not os.path.exists(JSON_PATH):
        print("[Missed Today] Error: articles.json not found")
        sys.exit(1)

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        articles = json.load(f)

    # Определяем сегодняшнюю дату
    today = datetime.date(2026, 7, 10)
    today_articles = []

    for a in articles:
        ts = a.get("timestamp")
        if ts:
            dt = datetime.datetime.fromtimestamp(int(ts))
            if dt.date() == today:
                today_articles.append(a)

    # Сортируем хронологически
    today_articles.sort(key=lambda x: x.get("timestamp", 0))

    print(f"[Missed Today] Найдено {len(today_articles)} статей за сегодня ({today}).")
    
    # Process each article
    success_count = 0
    generated_images = []
    
    for idx, a in enumerate(today_articles):
        print(f"\n[{idx+1}/{len(today_articles)}] Обработка: {a.get('title')}...")
        
        # 1. Сначала ищем или скачиваем изображение с лайв сайта
        local_img_path = download_image_from_live_site(a.get("image_url", ""))
        
        # 2. Если изображения нет ни на сайте, ни локально, генерируем новое с помощью ИИ
        if not local_img_path:
            print("[Missed Today] Картинка отсутствует на диске и на сайте. Генерируем AI-иллюстрацию...")
            safe_id = re.sub(r'[^\w\-_\.]', '_', a['id'])
            fallback_filename = f"images/fallback_{safe_id}.jpg"
            fallback_abs_path = os.path.join(PROJECT_DIR, fallback_filename)
            
            # Генерируем картинку по промту через Pollinations AI
            if news_engine.generate_title_card(a['title'], fallback_abs_path, gemini_key):
                local_img_path = fallback_abs_path
                a['image_url'] = f"./{fallback_filename}"
                generated_images.append(fallback_abs_path)
                print(f"[Missed Today] AI-иллюстрация успешно сгенерирована: {local_img_path}")
            else:
                print("[Missed Today] ВНИМАНИЕ: Не удалось сгенерировать иллюстрацию!")
        
        # 3. Генерируем Telegram-капшн
        telegram_caption = generate_tg_caption(a['title'], a['post_text'])
        if not telegram_caption:
            print("[Missed Today] Не удалось сгенерировать Telegram-капшн, пропуск.")
            continue
            
        # 4. Добавляем ссылку на сайт
        article_clean_url = f"https://maxtyutin.github.io/cryptochannel/#article-{a['timestamp']}"
        telegram_caption += f"\n\n👉 <a href=\"" + article_clean_url + "\">Читать на Crypto Analytics</a>"

        # 5. Публикуем в Telegram
        success = False
        if local_img_path:
            print(f"[Missed Today] Отправка в Телеграм с изображением: {local_img_path}...")
            success = news_engine.send_photo_to_telegram(telegram_caption, local_img_path, bot_token, chat_id)
        else:
            print("[Missed Today] ВНИМАНИЕ: Отправка текста, так как изображение отсутствует...")
            success = news_engine.send_to_telegram(telegram_caption, bot_token, chat_id)

        if success:
            print("[Missed Today] Успешно опубликовано в Telegram!")
            success_count += 1
        else:
            print("[Missed Today] Не удалось опубликовать пост.")

        print("[Missed Today] Ожидание 15 секунд...")
        time.sleep(15)

    # Если мы сгенерировали новые картинки, сохраняем их в articles.json и пушим в репозиторий
    if generated_images:
        print("[Missed Today] Сохранение обновленного articles.json с новыми AI-картинками...")
        try:
            with open(JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(articles, f, ensure_ascii=False, indent=2)
            
            pat = os.environ.get("GITHUB_PAT") or env.get("GITHUB_PAT")
            if pat:
                print("[Missed Today] Пушим сгенерированные AI-картинки на GitHub...")
                import subprocess
                repo_url = f"https://maxtyutin:{pat}@github.com/maxtyutin/cryptochannel.git"
                subprocess.run(["git", "remote", "set-url", "origin", repo_url], check=False)
                subprocess.run(["git", "config", "user.name", "Render Bot"], check=False)
                subprocess.run(["git", "config", "user.email", "render-bot@example.com"], check=False)
                subprocess.run(["git", "add", "articles.json", "images/"], check=False)
                subprocess.run(["git", "commit", "-m", "Add generated AI cover images [skip ci]"], check=False)
                subprocess.run(["git", "push", "origin", "HEAD:main"], check=False)
                print("[Missed Today] Изменения успешно запушены на GitHub!")
        except Exception as e:
            print(f"[Missed Today] Ошибка сохранения/пуша новых картинок: {e}")

    print(f"\n[Missed Today] Работа завершена. Успешно опубликовано {success_count}/{len(today_articles)} статей.")

if __name__ == '__main__':
    main()
