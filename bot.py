import os
import time
import threading
import logging
from flask import Flask

# Import Bot Configuration
from config import bot

# Import Modules (Ye zaroori hai taaki commands register hon)
import gaming   # Economy & Games Commands
import chat_ai  # Unlimited Chat Logic

# =========================================================
# ⚙️ LOGGING SETUP
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("MAIN_BOT")

# =========================================================
# 🌐 FAKE WEB SERVER (REQUIRED FOR RENDER)
# =========================================================
# Render requires a web service to bind to a port within 60 seconds.
# This Flask app does exactly that to keep the bot alive.

app = Flask(__name__)

@app.route('/')
def home():
    return "<h1>Miku Bot is Online! 🤖</h1>", 200

@app.route('/health')
def health():
    return "OK", 200

def run_web_server():
    """Runs the Flask app to satisfy Render's port requirement."""
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"🚀 Starting Web Server on Port {port}...")
    try:
        # use_reloader=False is important for threading
        app.run(host="0.0.0.0", port=port, use_reloader=False)
    except Exception as e:
        logger.error(f"Web Server Error: {e}")

# =========================================================
# 🚀 MAIN BOT START
# =========================================================
if __name__ == "__main__":
    logger.info("✅ System Loaded: Gaming & Unlimited Chat Modules Active.")

    # 1. Start Web Server (Background Thread)
    # Ye thread Render ko khush rakhega taaki wo bot ko kill na kare
    web_thread = threading.Thread(target=run_web_server)
    web_thread.daemon = True
    web_thread.start()

    # 2. Clean Start (Remove Webhook)
    # Ye sabse zaroori step hai polling ke liye
    try:
        logger.info("🧹 Removing old webhooks...")
        bot.remove_webhook()
        time.sleep(1) # Safety pause
    except Exception as e:
        logger.warning(f"Webhook Removal Warning: {e}")

    # 3. Start Polling Loop (Infinite)
    logger.info("🤖 Miku Bot is Polling...")
    
    while True:
        try:
            # infinity_polling automatically handles many errors
            bot.infinity_polling(timeout=10, long_polling_timeout=5, skip_pending=False)
        except Exception as e:
            logger.error(f"❌ Bot Crash detected: {e}")
            time.sleep(5) # 5 second wait karke restart karega
            logger.info("🔄 Restarting Bot Polling...")
