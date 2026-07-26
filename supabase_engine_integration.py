import os
import sys
import json
import time
import shutil
import urllib.request
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
from news_engine import load_env, call_gemini_api, send_photo_to_telegram, is_russian_title_duplicate

env = load_env()
gemini_key = env.get("GEMINI_API_KEY")
bot_token = env.get("TELEGRAM_BOT_TOKEN")
chat_id = env.get("TELEGRAM_CHAT_ID")
apify_token = os.environ.get("APIFY_API_TOKEN") or env.get("APIFY_API_TOKEN")

supabase_url = os.environ.get("SUPABASE_URL") or env.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY") or env.get("SUPABASE_KEY")

from tweet_template_generator import generate_tweet_card_html, get_base64_avatar_for_user
from playwright.sync_api import sync_playwright

def cleanup_local_temp_images():
    """
    Полностью очищает локальные временные изображения, чтобы 0 байт памяти забивалось на диске.
    """
    tmp_images_dir = os.path.join(BASE_DIR, "images")
    if os.path.exists(tmp_images_dir):
        try:
            for fname in os.listdir(tmp_images_dir):
                fpath = os.path.join(tmp_images_dir, fname)
                if os.path.isfile(fpath) and not fname.startswith("avatar"):
                    os.remove(fpath)
            print("[cleanup] Локальные временные файлы очищены. Память диска свободна!")
        except Exception as e:
            print(f"[cleanup] Ошибка очистки: {e}")

def get_processed_ids_from_supabase():
    """Считывает обработанные ID твитов из Supabase DB (или локального фаллбэка)"""
    if supabase_url and supabase_key:
        try:
            url = f"{supabase_url}/rest/v1/processed_tweets?select=tweet_id"
            req = urllib.request.Request(url, headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}"
            })
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return set(x["tweet_id"] for x in data)
        except Exception as e:
            print(f"[supabase] Запрос к DB: {e}")
            
    proc_file = os.path.join(BASE_DIR, "processed_news.txt")
    if os.path.exists(proc_file):
        with open(proc_file, 'r', encoding='utf-8') as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_processed_id_to_supabase(tweet_id, author_name=""):
    """Сохраняет обработанный ID твита в Supabase DB"""
    if supabase_url and supabase_key:
        try:
            url = f"{supabase_url}/rest/v1/processed_tweets"
            payload = json.dumps({"tweet_id": str(tweet_id), "author": author_name}).encode('utf-8')
            req = urllib.request.Request(url, data=payload, headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            })
            with urllib.request.urlopen(req, timeout=5) as resp:
                print(f"[supabase] ID {tweet_id} сохранен в облачную БД!")
        except Exception as e:
            print(f"[supabase] Ошибка сохранения ID: {e}")
            
    proc_file = os.path.join(BASE_DIR, "processed_news.txt")
    with open(proc_file, 'a', encoding='utf-8') as f:
        f.write(f"{tweet_id}\n")

if __name__ == "__main__":
    cleanup_local_temp_images()
    processed = get_processed_ids_from_supabase()
    print(f"[supabase_test] Загружено {len(processed)} прошлых ID.")
