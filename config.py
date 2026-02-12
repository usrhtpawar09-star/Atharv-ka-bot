import telebot
from pymongo import MongoClient
import certifi
import logging

# =========================================================
# 📝 CONFIGURATION & SETTINGS
# =========================================================

# ✅ Bot Token
BOT_TOKEN = "8533598800:AAHHkoJ77C2QO7j8F1IUUX92qKVac3ySZkM"

# ✅ MongoDB Connection
MONGO_URL = "mongodb+srv://usrhtffdbr:miku1234@cluster0.jhvwttf.mongodb.net/?appName=Cluster0"

# ✅ Groq API Configuration (Rotation System)
GROQ_API_KEYS = [
    "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",
    "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",
    "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",
    "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"
]

GROQ_MODEL_NAME = "moonshotai/kimi-k2-instruct-0905"

# ✅ Admin & Owner Configuration
OWNER_ID = 8327837344
ADMIN_IDS = [
    8327837344,  # Owner
    6088855317,  # Admin 1
    7738104912   # Admin 2
]

# ✅ Global Time Constants
DAY_SECONDS = 86400
REVIVE_SECONDS = 21600

# =========================================================
# 🔌 INITIALIZATION
# =========================================================

print("🔄 Initializing Miku Bot Systems...")

# 1️⃣ Initialize Bot
try:
    bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
    print("🤖 Bot Token Accepted.")
except Exception as e:
    print(f"❌ Bot Token Error: {e}")

# 2️⃣ Initialize Database
try:
    client = MongoClient(MONGO_URL, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=5000)
    db = client["miku_database"]
    users_col = db["users"]
    groups_col = db["groups"]
    config_col = db["config"]
    client.admin.command('ping')
    print("✅ MongoDB Connected Successfully!")
except Exception as e:
    print(f"❌ Database Connection Failed: {e}")

print("✅ System Ready!")
