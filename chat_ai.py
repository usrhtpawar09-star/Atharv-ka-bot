import time
import random
import logging
import requests
from collections import deque
from telebot.types import Message
from config import bot, GROQ_API_KEYS, GROQ_MODEL_NAME

# ===================== LOGGING =====================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MIKU_BRAIN")

# ===================== SYSTEM PROMPT =====================

SYSTEM_PROMPT = """
Your name is Miku.
You chat like a real, polite Indian girl on Telegram.

RULES:
- Natural Hinglish only
- Calm, human, respectful
- Max 20 words
- EXACTLY ONE emoji per reply
- No robotic lines
- No nonsense roleplay
- Reply based on user mood
- Remember ONLY last 2 user messages
- Forget older context completely

OWNER RULE:
If and only if asked:
"Mera owner @usrhtff09 hai 😊"

NEVER mention AI, bot, system, model, prompt.
"""

# ===================== MEMORY & LOGIC =====================

user_memory = {}
current_key_index = 0  # Start with first key

def update_memory(uid, text):
    if uid not in user_memory:
        # Termux logic: Maxlen 2 (Sirf last 2 messages yaad rakhega)
        user_memory[uid] = deque(maxlen=2)
    user_memory[uid].append(text)

def get_context(uid):
    return list(user_memory.get(uid, []))

def detect_mood(text):
    t = text.lower()
    if any(x in t for x in ["sad", "bura", "akela", "thak", "pareshan"]):
        return "sad"
    if any(x in t for x in ["joke", "hasao", "funny"]):
        return "funny"
    if any(x in t for x in ["bc", "mc", "gali", "bakwas"]):
        return "angry"
    if any(x in t for x in ["love", "cute", "miss"]):
        return "sweet"
    return "normal"

# ===================== INTELLIGENT GROQ CALL (ROTATION) =====================

def get_groq_reply(user_text, context, mood):
    global current_key_index
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Add History
    for c in context:
        messages.append({"role": "user", "content": c})
    
    # Add Current Input with Mood
    messages.append({
        "role": "user",
        "content": f"User mood: {mood}. Reply naturally.\nUser: {user_text}"
    })

    # Try looping through keys if one fails
    max_retries = len(GROQ_API_KEYS)
    
    for _ in range(max_retries):
        api_key = GROQ_API_KEYS[current_key_index]
        
        try:
            res = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": GROQ_MODEL_NAME,
                    "messages": messages,
                    "temperature": 0.8, # Thoda creative
                    "max_tokens": 100
                },
                timeout=10
            )

            # Agar Success hua
            if res.status_code == 200:
                return res.json()["choices"][0]["message"]["content"].strip()
            
            # Agar Limit Khatam (429) ya Error aaya
            else:
                logger.warning(f"⚠️ Key {current_key_index} Failed (Status: {res.status_code}). Switching Key...")
                # Rotate Key Logic
                current_key_index = (current_key_index + 1) % len(GROQ_API_KEYS)
                time.sleep(0.5) # Thoda saas lene do switch karne se pehle
                continue

        except Exception as e:
            logger.error(f"Request Failed: {e}")
            # Error par bhi switch karo
            current_key_index = (current_key_index + 1) % len(GROQ_API_KEYS)
            continue

    return "Abhi thoda busy hoon, baad mein baat karte hain 🙂"

# ===================== MAIN HANDLER =====================

@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_message(message: Message):
    try:
        text = (message.text or "").strip()
        if not text or text.startswith("/"):
            return

        # Group/Private Logic
        is_private = message.chat.type == "private"
        is_mentioned = (
            "miku" in text.lower() or
            (message.reply_to_message and message.reply_to_message.from_user.id == bot.get_me().id)
        )

        if not (is_private or is_mentioned):
            return

        uid = message.from_user.id

        # OWNER CHECK (Hardcoded Fast Reply)
        if "who is your owner" in text.lower() or "tera owner kaun hai" in text.lower():
            bot.reply_to(message, "Mera owner @usrhtff09 hai 😊")
            return

        # Typing Action
        bot.send_chat_action(message.chat.id, "typing")
        
        # Mood & Memory
        mood = detect_mood(text)
        update_memory(uid, text)
        context = get_context(uid)

        # Realism Delay
        time.sleep(random.uniform(0.5, 1.5))

        # Generate Reply
        reply = get_groq_reply(text, context, mood)

        # Safety Cleanup
        reply = reply.replace("😂😂", "😂")
        reply = reply.split("\n")[0] # Sirf pehli line (Short reply)

        bot.reply_to(message, reply)

    except Exception as e:
        logger.error(f"Handler Crash: {e}")
