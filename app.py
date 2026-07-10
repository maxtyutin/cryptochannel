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
        push = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
        print(f"[Render] Git Push output:\nSTDOUT:\n{push.stdout}\nSTDERR:\n{push.stderr}")
        if push.returncode == 0:
            print("[Render] Successfully pushed updates to GitHub.")
        else:
            print("[Render] Git push failed.")
    else:
        print("[Render] Git commit failed or nothing to commit.")

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
            
            # Сбрасываем локальное состояние к origin/main, чтобы избежать конфликтов слияния
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
                subprocess.run(["python3", "news_engine.py"])
                
            # Отправляем результаты на GitHub Pages
            push_to_github()
            
        except Exception as e:
            print(f"[Render] Error in background worker: {e}")
            
        print("[Render] Sleeping for 15 minutes...")
        time.sleep(900)

@app.on_event("startup")
def startup_event():
    thread = threading.Thread(target=background_worker, daemon=True)
    thread.start()
