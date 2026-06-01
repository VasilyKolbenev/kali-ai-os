import sys
import argparse
import json
import os

# Простой скрипт для регистрации задач.
# В реальном ядре KALI он должен делать API-вызов в kernel/scheduler.py
# Здесь мы эмулируем создание файла задачи в data/scheduler/

def main():
    parser = argparse.ArgumentParser(description="Automation Scheduler Agent Tool")
    parser.add_argument("--cron", type=str, required=True, help="Cron expression e.g. '0 8 * * *'")
    parser.add_argument("--action", type=str, required=True, help="Action to execute e.g. 'telegram_message'")
    parser.add_argument("--payload", type=str, required=True, help="Payload data for the action")
    
    args = parser.parse_args()
    
    task_data = {
        "cron": args.cron,
        "action": args.action,
        "payload": args.payload,
        "status": "active"
    }
    
    # Save to KALI scheduler dir
    scheduler_dir = os.path.join(os.getcwd(), "data", "scheduler")
    os.makedirs(scheduler_dir, exist_ok=True)
    
    # Unique filename based on hash
    task_id = str(hash(f"{args.cron}{args.action}{args.payload}"))[-8:]
    task_file = os.path.join(scheduler_dir, f"task_{task_id}.json")
    
    with open(task_file, "w", encoding="utf-8") as f:
        json.dump(task_data, f, ensure_ascii=False, indent=2)
        
    result = {
        "success": True,
        "task_id": task_id,
        "message": f"Task registered successfully to run with schedule: {args.cron}"
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
