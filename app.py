import time
import datetime
import subprocess
import os
import sys
import threading
from fastapi import FastAPI

app = FastAPI()

worker_logs = []

def log(message):
    timestamp = datetime.datetime.utcnow().isoformat() + " UTC"
    full_msg = f"[{timestamp}] {message}"
    print(full_msg)
    worker_logs.append(full_msg)
    if len(worker_logs) > 300:
        worker_logs.pop(0)

@app.get("/")
@app.head("/")
def read_root():
    return {"status": "running", "time": datetime.datetime.utcnow().isoformat() + " UTC"}

@app.get("/ping")
@app.head("/ping")
def ping():
    return "pong"

@app.get("/logs")
def get_logs():
    return {"logs": worker_logs}

def run_command(cmd):
    log(f"Executing: {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.stdout:
        # Ограничим вывод в логи FastAPI, чтобы JSON не раздувался
        stdout_lines = res.stdout.splitlines()[-100:]
        log("STDOUT (last 100 lines):\n" + "\n".join(stdout_lines))
    if res.stderr:
        log(f"STDERR:\n{res.stderr}")
    return res

def background_worker():
    log("Background worker thread started.")
    
    last_digest_hour = -1
    last_poll_hour = -1
    
    # Ждем 30 секунд при первом запуске, чтобы дать контейнеру полностью инициализироваться
    time.sleep(30)
    
    while True:
        try:
            log("Starting new cycle...")
            pat = os.environ.get("GITHUB_PAT")
            if pat:
                repo_url = f"https://maxtyutin:{pat}@github.com/maxtyutin/cryptochannel.git"
                run_command(["git", "remote", "set-url", "origin", repo_url])
            else:
                log("WARNING: GITHUB_PAT not set in environment!")
            
            # Очищаем репозиторий, забираем изменения из origin и жестко сбрасываем main
            run_command(["git", "clean", "-fd", "-e", ".venv", "-e", "venv"])
            run_command(["git", "checkout", "main"])
            run_command(["git", "fetch", "origin"])
            run_command(["git", "reset", "--hard", "origin/main"])
            
            # Определяем текущее время UTC
            now_utc = datetime.datetime.utcnow()
            hour_utc = now_utc.hour
            
            # Запускаем нужный режим. Вся логика отправки в TG, пуша на GitHub и задержки теперь внутри news_engine.py!
            if hour_utc in [6, 18] and hour_utc != last_digest_hour:
                log(f"Triggering digest for hour {hour_utc} UTC...")
                run_command([sys.executable, "news_engine.py", "--digest"])
                last_digest_hour = hour_utc
            elif hour_utc == 11 and hour_utc != last_poll_hour:
                log(f"Triggering poll for hour {hour_utc} UTC...")
                run_command([sys.executable, "news_engine.py", "--poll"])
                last_poll_hour = hour_utc
            else:
                log("Triggering regular news search...")
                run_command([sys.executable, "news_engine.py"])
                
        except Exception as e:
            log(f"Error in background worker: {e}")
            
        log("Cycle finished. Sleeping for 15 minutes...")
        time.sleep(900)

@app.on_event("startup")
def startup_event():
    thread = threading.Thread(target=background_worker, daemon=True)
    thread.start()
