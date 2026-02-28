import os
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "attendance_db")

JWT_SECRET = os.getenv("JWT_SECRET", "CHANGE_ME")
APP_ORIGIN = os.getenv("APP_ORIGIN", "http://127.0.0.1:8000")

# Timezone used for "today" and daily attendance calculations.
# Default matches your environment (Jordan).
TIMEZONE_NAME = os.getenv("TIMEZONE_NAME", "Asia/Amman")
