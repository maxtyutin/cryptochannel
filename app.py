import time
import datetime
import subprocess
import os
import threading
import json
import requests
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
@app.head("/")
def read_root():
    return {"status": "running", "time": datetime.datetime.utcnow().isoformat() + " UTC"}

@app.get("/ping")
@app.head("/ping")
def ping():
    return "pong"

def load_env_vars():
    """Загружает переменные из .env файла в словарь (в качестве резерва)."""
    env = {}
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    try:
                        key, val = line.strip().split('=', 1)
                        env[key.strip()] = val.strip()
                    except ValueError:
                        pass
    return env

def setup_git_remote(repo_url):
    """Проверяет наличие remote 'origin'. Если есть — обновляет URL, если нет — добавляет."""
    remotes = subprocess.run(["git", "remote"], capture_output=True, text=True)
    if "origin" in remotes.stdout:
        subprocess.run(["git", "remote", "set-url", "origin", repo_url])
    else:
        subprocess.run(["git", "remote", "add", "origin", repo_url])

def push_to_github():
    pat = os.environ.get("GITHUB_PAT")
    if not pat:
        print("[Render] GITHUB_PAT not set, skipping push.")
        return
    repo_url = f"https://maxtyutin:{pat}@github.com/maxtyutin/cryptochannel.git"
    
    # Настраиваем удаленный репозиторий и данные пользователя
    setup_git_remote(repo_url)
    subprocess.run(["git", "config", "user.name", "Render Bot"])
    subprocess.run(["git", "config", "user.email", "render-bot@example.com"])
    
    # Переключаемся на ветку main (на случай если мы в detached HEAD)
    subprocess.run(["git", "checkout", "main"])
    
    # Проверяем, есть ли изменения
    status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    if not status.stdout.strip():
        print("[Render] No changes to push.")
        return
        
    subprocess.run(["git", "add", "processed_news.txt", "published_topics.txt", "articles.json"])
    subprocess.run(["git", "add", "images/"])
    
    commit = subprocess.run(["git", "commit", "-m", "Auto-update database from Render [skip ci]"], capture_output=True, text=True)
    print(f"[Render] Git Commit output:\nSTDOUT:\n{commit.stdout}\nSTDERR:\n{commit.stderr}")
    
    if commit.returncode == 0:
        # Пушим текущую ветку HEAD напрямую в main на GitHub
        push = subprocess.run(["git", "push", "origin", "HEAD:main"], capture_output=True, text=True)
        print(f"[Render] Git Push output:\nSTDOUT:\n{push.stdout}\nSTDERR:\n{push.stderr}")
        if push.returncode == 0:
            print("[Render] Successfully pushed updates to GitHub.")
        else:
            print("[Render] Git push failed.")
    else:
        print("[Render] Git commit failed or nothing to commit.")

def send_pending_tg_post():
    """Читает pending_tg_post.json, ждет обновления сайта на GitHub Pages и отправляет пост."""
    pending_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pending_tg_post.json")
    if not os.path.exists(pending_file):
        return
        
    print("[Render] Found pending Telegram post. Preparing for posting...")
    try:
        with open(pending_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"[Render] Error reading pending post: {e}")
        return
        
    env = load_env_vars()
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or env.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("[Render] Telegram bot credentials missing. Deleting pending file.")
        try:
            os.remove(pending_file)
        except Exception:
            pass
        return
        
    # Задержка 90 секунд перед отправкой в Telegram, чтобы дать GitHub Pages обновить сайт
    print("[Render] Delaying Telegram post by 90 seconds for GitHub Pages deployment...")
    time.sleep(90)
    
    caption = data.get("telegram_caption", "")
    local_img = data.get("local_img_path")
    original_img = data.get("image_url")
    
    print("[Render] Sending post to Telegram...")
    success = False
    
    # 1. Пробуем отправить локальное изображение
    if local_img and os.path.exists(local_img):
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
            with open(local_img, 'rb') as photo:
                files = {'photo': photo}
                payload = {'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML'}
                res = requests.post(url, data=payload, files=files)
                if res.status_code == 200:
                    print("[Render] Telegram post sent successfully (local image).")
                    success = True
                else:
                    print(f"[Render] Telegram local photo send failed: {res.text}")
        except Exception as e:
            print(f"[Render] Error sending local photo to TG: {e}")
            
    # 2. Если не удалось, пробуем внешнюю ссылку на изображение
    if not success and original_img and original_img.startswith('http'):
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
            payload = {'chat_id': chat_id, 'photo': original_img, 'caption': caption, 'parse_mode': 'HTML'}
            res = requests.post(url, data=payload)
            if res.status_code == 200:
                print("[Render] Telegram post sent successfully (external image).")
                success = True
            else:
                print(f"[Render] Telegram external photo send failed: {res.text}")
        except Exception as e:
            print(f"[Render] Error sending external photo to TG: {e}")
            
    # 3. Если всё еще не отправлено — отправляем текстом
    if not success:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {'chat_id': chat_id, 'text': caption, 'parse_mode': 'HTML'}
            res = requests.post(url, data=payload)
            if res.status_code == 200:
                print("[Render] Telegram post sent successfully (text only).")
                success = True
            else:
                print(f"[Render] Telegram text send failed: {res.text}")
        except Exception as e:
            print(f"[Render] Error sending text to TG: {e}")
            
    # Удаляем файл отложенного поста
    try:
        os.remove(pending_file)
        print("[Render] Cleaned up pending post file.")
    except Exception as e:
        print(f"[Render] Error deleting pending file: {e}")

def background_worker():
    print("[Render] Background worker thread started.")
    last_digest_hour = -1
    last_poll_hour = -1
    
    # Ждем 30 секунд при первом запуске, чтобы дать контейнеру полностью инициализироваться
    time.sleep(30)
    
    while True:
        try:
            print("[Render] Starting cycle...")
            pat = os.environ.get("GITHUB_PAT")
            if pat:
                repo_url = f"https://maxtyutin:{pat}@github.com/maxtyutin/cryptochannel.git"
                setup_git_remote(repo_url)
            
            # Принудительно переключаемся на main и сбрасываем локальное состояние к origin/main
            subprocess.run(["git", "checkout", "main"])
            subprocess.run(["git", "reset", "--hard", "origin/main"])
            subprocess.run(["git", "pull", "--rebase", "origin", "main"])
            
            # Определяем текущее время UTC
            now_utc = datetime.datetime.utcnow()
            hour_utc = now_utc.hour
            
            # Запускаем нужный режим
            if hour_utc in [6, 18] and hour_utc != last_digest_hour:
                print(f"[Render] Time is {now_utc.isoformat()} UTC. Triggering digest...")
                subprocess.run(["python3", "news_engine.py", "--digest"])
                last_digest_hour = hour_utc
            elif hour_utc == 11 and hour_utc != last_poll_hour:
                print(f"[Render] Time is {now_utc.isoformat()} UTC. Triggering poll...")
                subprocess.run(["python3", "news_engine.py", "--poll"])
                last_poll_hour = hour_utc
            else:
                print(f"[Render] Time is {now_utc.isoformat()} UTC. Triggering regular news search...")
                # Запускаем в режиме --no-tg (отложенная отправка в телеграм)
                subprocess.run(["python3", "news_engine.py", "--no-tg"])
                
            # Отправляем результаты на GitHub Pages
            push_to_github()
            
            # Если есть отложенный пост, отправляем его в Telegram после паузы
            send_pending_tg_post()
            
        except Exception as e:
            print(f"[Render] Error in background worker: {e}")
            
        print("[Render] Sleeping for 15 minutes...")
        time.sleep(900)

@app.on_event("startup")
def startup_event():
    thread = threading.Thread(target=background_worker, daemon=True)
    thread.start()
