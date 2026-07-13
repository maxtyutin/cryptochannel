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
                subprocess.run(["git", "remote", "set-url", "origin", repo_url], check=False)
            
            # Очищаем репозиторий, забираем изменения из origin и жестко сбрасываем main
            subprocess.run(["git", "clean", "-fd"], check=False)
            subprocess.run(["git", "checkout", "main"], check=False)
            subprocess.run(["git", "fetch", "origin"], check=False)
            subprocess.run(["git", "reset", "--hard", "origin/main"], check=False)
            
            # Определяем текущее время UTC
            now_utc = datetime.datetime.utcnow()
            hour_utc = now_utc.hour
            
            # Запускаем нужный режим. Вся логика отправки в TG, пуша на GitHub и задержки теперь внутри news_engine.py!
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
                
        except Exception as e:
            print(f"[Render] Error in background worker: {e}")
            
        print("[Render] Sleeping for 15 minutes...")
        time.sleep(900)

@app.on_event("startup")
def startup_event():
    thread = threading.Thread(target=background_worker, daemon=True)
    thread.start()
