import time
import datetime
import subprocess
import os
import threading
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

def push_to_github():
    pat = os.environ.get("GITHUB_PAT")
    if not pat:
        print("[Render] GITHUB_PAT not set, skipping push.")
        return
    repo_url = f"https://maxtyutin:{pat}@github.com/maxtyutin/cryptochannel.git"
    
    # Конфигурируем репозиторий для отправки изменений
    subprocess.run(["git", "remote", "set-url", "origin", repo_url])
    subprocess.run(["git", "config", "user.name", "Render Bot"])
    subprocess.run(["git", "config", "user.email", "render-bot@example.com"])
    
    # Проверяем, есть ли изменения
    status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    if not status.stdout.strip():
        print("[Render] No changes to push.")
        return
        
    subprocess.run(["git", "add", "processed_news.txt", "published_topics.txt", "articles.json"])
    subprocess.run(["git", "add", "images/"])
    commit = subprocess.run(["git", "commit", "-m", "Auto-update database from Render [skip ci]"])
    if commit.returncode == 0:
        push = subprocess.run(["git", "push", "origin", "main"])
        if push.returncode == 0:
            print("[Render] Successfully pushed updates to GitHub.")
        else:
            print("[Render] Git push failed.")

def background_worker():
    print("[Render] Background worker thread started.")
    last_digest_hour = -1
    last_poll_hour = -1
    
    while True:
        try:
            print("[Render] Starting cycle...")
            # 1. Сначала делаем pull, чтобы подтянуть возможные изменения
            pat = os.environ.get("GITHUB_PAT")
            if pat:
                repo_url = f"https://maxtyutin:{pat}@github.com/maxtyutin/cryptochannel.git"
                subprocess.run(["git", "remote", "set-url", "origin", repo_url])
            subprocess.run(["git", "pull", "--rebase", "origin", "main"])
            
            # 2. Определяем текущее время UTC
            now_utc = datetime.datetime.utcnow()
            hour_utc = now_utc.hour
            
            # 3. Запускаем нужный режим
            # Дайджест цен: в 06:00 и 18:00 UTC
            if hour_utc in [6, 18] and hour_utc != last_digest_hour:
                print(f"[Render] Time is {now_utc.isoformat()} UTC. Triggering digest...")
                subprocess.run(["python3", "news_engine.py", "--digest"])
                last_digest_hour = hour_utc
            # Опрос: в 11:00 UTC
            elif hour_utc == 11 and hour_utc != last_poll_hour:
                print(f"[Render] Time is {now_utc.isoformat()} UTC. Triggering poll...")
                subprocess.run(["python3", "news_engine.py", "--poll"])
                last_poll_hour = hour_utc
            # Обычные новости: каждые 15 минут
            else:
                print(f"[Render] Time is {now_utc.isoformat()} UTC. Triggering regular news search...")
                subprocess.run(["python3", "news_engine.py"])
                
            # 4. Отправляем результаты на GitHub Pages
            push_to_github()
            
        except Exception as e:
            print(f"[Render] Error in background worker: {e}")
            
        print("[Render] Sleeping for 15 minutes...")
        time.sleep(900)

@app.on_event("startup")
def startup_event():
    thread = threading.Thread(target=background_worker, daemon=True)
    thread.start()
