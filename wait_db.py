import socket
import time
import sys

host = "db"
port = 5432

print("Ожидание базы данных...", flush=True)
while True:
    try:
        with socket.create_connection((host, port), timeout=2):
            print("База данных готова!", flush=True)
            sys.exit(0)
    except OSError:
        print("База ещё не готова, повтор...", flush=True)
        time.sleep(1)