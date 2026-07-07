import time
import datetime
import subprocess
import sys
import os

BASE_DIR = "/Users/maxtyutin/antigravity/TG каналы"
LOG_FILE = os.path.join(BASE_DIR, "news_daemon.log")

def log_message(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"
    print(formatted_msg)
    with open(LOG_FILE, "a") as f:
        f.write(formatted_msg + "\n")

def run_script(args=[]):
    script_path = os.path.join(BASE_DIR, "news_engine.py")
    cmd = [sys.executable, script_path] + args
    log_message(f"Запуск скрипта с аргументами: {args}")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        log_message("Успешное выполнение. Вывод:")
        if res.stdout.strip():
            log_message(res.stdout)
    except subprocess.CalledProcessError as e:
        log_message(f"ОШИБКА ВЫПОЛНЕНИЯ (код {e.returncode}):")
        log_message(e.stdout)
        log_message(e.stderr)
    except Exception as e:
        log_message(f"Системная ошибка при запуске: {e}")

def main():
    log_message("==================================================")
    log_message("ИИ-Редактор ForkLog: ФОНОВЫЙ ДЕМОН УСПЕШНО ЗАПУЩЕН")
    log_message("Расписание:")
    log_message("- Публикация новостей: каждые 10 минут")
    log_message("- Рыночный дайджест цен: ежедневно в 09:15 и 21:15")
    log_message("- Интерактивный опрос: ежедневно в 14:00")
    log_message("==================================================")

    last_news_minute = -1
    last_digest_key = ""
    last_poll_date = ""

    # При старте делаем одну первичную проверку новостей
    log_message("Первичная проверка новостей при старте демона...")
    run_script()
    last_news_minute = datetime.datetime.now().minute

    while True:
        try:
            now = datetime.datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            
            # 1. Новости каждые 10 минут
            if now.minute % 10 == 0 and now.minute != last_news_minute:
                log_message(f"Триггер: Наступила минута {now.minute}. Запуск публикации новостей.")
                run_script()
                last_news_minute = now.minute
                
            # 2. Дайджест цен в 09:15 и 21:15
            if (now.hour == 9 or now.hour == 21) and now.minute == 15:
                digest_key = f"{today_str}_{now.hour}"
                if last_digest_key != digest_key:
                    log_message(f"Триггер: Время {now.hour}:15. Запуск дайджеста цен.")
                    run_script(["--digest"])
                    last_digest_key = digest_key
                    
            # 3. Опрос в 14:00
            if now.hour == 14 and now.minute == 0:
                if last_poll_date != today_str:
                    log_message("Триггер: Время 14:00. Запуск интерактивного опроса.")
                    run_script(["--poll"])
                    last_poll_date = today_str
                    
        except Exception as e:
            log_message(f"Критическая ошибка в главном цикле демона: {e}")
            
        # Пауза 30 секунд перед следующей проверкой
        time.sleep(30)

if __name__ == "__main__":
    main()
