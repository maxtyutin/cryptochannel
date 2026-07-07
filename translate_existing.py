import json
import os
import re
import urllib.request
import time

BASE_DIR = "/Users/maxtyutin/antigravity/TG каналы"
JSON_PATH = os.path.join(BASE_DIR, "articles.json")
ENV_FILE = os.path.join(BASE_DIR, ".env")

GEMINI_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.0-flash",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite"
]

def load_env():
    env = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    k, v = line.strip().split('=', 1)
                    env[k.strip()] = v.strip()
    return env

def call_gemini_api(prompt, gemini_key, is_json=False):
    for model in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
        data = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        if is_json:
            data["generationConfig"] = {"responseMimeType": "application/json"}
            
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result['candidates'][0]['content']['parts'][0]['text'].strip()
        except Exception as e:
            print(f"Модель {model} не сработала: {e}")
            continue
    return None

def translate_title(title, gemini_key):
    prompt = f"Переведи заголовок крипто-новости на русский язык. Сделай перевод привлекательным, информативным и профессиональным в стиле издания ForkLog. Не используй кликбейт. Верни только переведенную фразу без кавычек и лишнего текста.\n\nЗаголовок: {title}"
    translated = call_gemini_api(prompt, gemini_key)
    if translated:
        # Убираем лишние кавычки по краям
        translated = re.sub(r'^["\'«]|["\'»]$', '', translated).strip()
        return translated
    return title

def main():
    env = load_env()
    key = env.get("GEMINI_API_KEY")
    if not key:
        print("API key not found")
        return
        
    if not os.path.exists(JSON_PATH):
        print("articles.json not found")
        return
        
    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        articles = json.load(f)
        
    print(f"Загружено статей: {len(articles)}")
    updated = False
    
    for a in articles:
        title = a.get("title", "")
        # Если заголовок содержит в основном английский текст, переводим
        if re.search(r'[a-zA-Z]{3,}', title):
            print(f"Переводим: {title}")
            new_title = translate_title(title, key)
            print(f"Результат: {new_title}")
            a["title"] = new_title
            updated = True
            time.sleep(2) # Задержка для соблюдения лимитов
            
    if updated:
        with open(JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        print("База articles.json успешно обновлена русскими заголовками!")
    else:
        print("Все заголовки уже на русском или нет статей для перевода.")

if __name__ == "__main__":
    main()
