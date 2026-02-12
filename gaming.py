import time
import random
import threading
from telebot import apihelper
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import bot, users_col, groups_col, config_col, OWNER_ID, ADMIN_IDS, DAY_SECONDS, REVIVE_SECONDS

# =========================================================
# ⚙️ CONFIGURATION
# =========================================================
AUTO_REVIVE_SECONDS = 6 * 3600  # 6 Hours
BOT_START_TIME = time.time()    # Uptime track karne ke liye
DB_LIMIT_MB = 512               # MongoDB Free Tier Limit

# =========================================================
# 🌐 GLOBAL BROADCAST VARIABLES
# =========================================================
BROADCAST_RUNNING = False
DELETE_RUNNING = False
STOP_BROADCAST = False
STOP_DELETE = False

# Store {chat_id: message_id} of the LAST broadcast for deletion
LAST_BROADCAST_IDS = {} 

# =========================================================
# 🛍️ SHOP ITEMS DATA
# =========================================================
SHOP_ITEMS = {
    "rose": {"name": "Rose", "icon": "🌹", "price": 500},
    "chocolate": {"name": "Chocolate", "icon": "🍫", "price": 800},
    "ring": {"name": "Ring", "icon": "💍", "price": 2000},
    "teddy": {"name": "Teddy Bear", "icon": "🧸", "price": 1500},
    "pizza": {"name": "Pizza", "icon": "🍕", "price": 600},
    "surprise": {"name": "Surprise Box", "icon": "🎁", "price": 2500},
    "puppy": {"name": "Puppy", "icon": "🐶", "price": 3000},
    "cake": {"name": "Cake", "icon": "🎂", "price": 1000},
    "letter": {"name": "Love Letter", "icon": "💌", "price": 400},
    "cat": {"name": "Cat", "icon": "🐱", "price": 2500}
}

# =========================================================
# 🛠️ HELPER FUNCTIONS
# =========================================================

def is_admin(uid):
    return str(uid) == str(OWNER_ID) or uid in ADMIN_IDS

def check_admin(m):
    if is_admin(m.from_user.id): return True
    bot.reply_to(m, "⚠️ <b>Only owner/admin can use this command.</b>", parse_mode="HTML")
    return False

# 🔒 STRICT CHECK FOR BROADCAST COMMANDS
def check_admin_strict(m):
    if is_admin(m.from_user.id): return True
    bot.reply_to(m, "⚠️ Admin/ Owner command only.")
    return False

def eco_locked():
    cfg = config_col.find_one({"_id": "settings"})
    if not cfg: return False
    return cfg.get("locked", False)

def is_group_locked(chat_id):
    grp = groups_col.find_one({"_id": chat_id})
    if not grp: return False
    return grp.get("eco_disabled", False)

def track_chat(m):
    if m.chat.type in ['group', 'supergroup']:
        groups_col.update_one(
            {"_id": m.chat.id}, 
            {"$set": {"name": m.chat.title}}, 
            upsert=True
        )

def get_user(uid, name):
    uid = int(uid)
    user = users_col.find_one({"_id": uid})
    if not user:
        user = {
            "_id": uid,
            "name": name,
            "balance": 1000,
            "kills": 0,
            "status": "alive",
            "death_time": 0,
            "protection": 0,
            "last_daily": 0,
            "last_ubi": 0,
            "inventory": {}
        }
        users_col.insert_one(user)
    else:
        if user.get("name") != name:
            users_col.update_one({"_id": uid}, {"$set": {"name": name}})
    
    if user.get("status") == "dead":
        death_time = user.get("death_time", 0)
        if time.time() > death_time + AUTO_REVIVE_SECONDS:
            users_col.update_one({"_id": uid}, {"$set": {"status": "alive", "death_time": 0}})
            user["status"] = "alive"
            user["death_time"] = 0

    now = time.time()
    last_ubi = user.get("last_ubi", 0)
    if now - last_ubi > DAY_SECONDS:
        users_col.update_one(
            {"_id": uid}, 
            {"$inc": {"balance": 1000}, "$set": {"last_ubi": now}}
        )
        user["balance"] += 1000
    return user

def check_death(uid):
    uid = int(uid)
    user = users_col.find_one({"_id": uid})
    if not user: return False
    if user.get("status") == "dead":
        if time.time() > user.get("death_time", 0) + AUTO_REVIVE_SECONDS:
            users_col.update_one({"_id": uid}, {"$set": {"status": "alive", "death_time": 0}})
            return False
        return True
    return False

def can_play(m):
    track_chat(m)
    if eco_locked(): 
        if is_admin(m.from_user.id): return True
        bot.reply_to(m, "🔒 Global Economy is locked by Owner.", parse_mode="HTML")
        return False
    
    if m.chat.type in ['group', 'supergroup'] and is_group_locked(m.chat.id):
        if m.text and m.text.startswith(("/open", "/close")):
            return True
        bot.reply_to(m, "⛔ Economy is closed. Use /open", parse_mode="HTML")
        return False
        
    return True

# =========================================================
# 🔄 BACKGROUND AUTO-REVIVE SYSTEM
# =========================================================

def background_revive_job():
    while True:
        try:
            cutoff_time = time.time() - AUTO_REVIVE_SECONDS
            users_col.update_many(
                {
                    "status": "dead",
                    "death_time": {"$lt": cutoff_time}
                },
                {
                    "$set": {"status": "alive", "death_time": 0}
                }
            )
        except Exception as e:
            print(f"Auto Revive Error: {e}")
        time.sleep(300)

threading.Thread(target=background_revive_job, daemon=True).start()

# =========================================================
# 📡 ADVANCED BROADCAST SYSTEM (PROFESSIONAL)
# =========================================================

# --- WORKER THREAD FOR SENDING ---
def broadcast_worker(m, targets, from_chat_id, msg_id):
    global BROADCAST_RUNNING, STOP_BROADCAST, LAST_BROADCAST_IDS
    
    LAST_BROADCAST_IDS.clear() # Clear old history
    
    total = len(targets)
    success = 0
    blocked = 0
    deleted_accounts = 0
    
    status_msg = bot.reply_to(m, "📡 Broadcasting message…\nPlease wait.")
    
    last_update_time = time.time()

    for i, chat_id in enumerate(targets):
        if STOP_BROADCAST:
            break
            
        try:
            # Copy message logic
            sent_msg = bot.copy_message(chat_id, from_chat_id, msg_id)
            LAST_BROADCAST_IDS[chat_id] = sent_msg.message_id
            success += 1
            time.sleep(0.04) # Safe delay
            
        except apihelper.ApiTelegramException as e:
            # Handle FloodWait
            if e.error_code == 429:
                retry_after = int(e.result_json['parameters']['retry_after'])
                time.sleep(retry_after)
                try:
                    sent_msg = bot.copy_message(chat_id, from_chat_id, msg_id)
                    LAST_BROADCAST_IDS[chat_id] = sent_msg.message_id
                    success += 1
                except:
                    blocked += 1
            # Handle Blocks/Kicks
            elif e.error_code in [403, 400]:
                blocked += 1
                deleted_accounts += 1
            else:
                blocked += 1
        except Exception:
            blocked += 1

        # Update Status every 3 seconds or at end
        if time.time() - last_update_time > 3 or i == total - 1:
            try:
                text = (
                    "📡 <b>Broadcast in progress…</b>\n\n"
                    f"👥 <b>Total Chats:</b> {total}\n"
                    f"💫 <b>Completed:</b> {i+1} / {total}\n"
                    f"✅ <b>Success:</b> {success}\n"
                    f"🚫 <b>Blocked:</b> {blocked}\n"
                    f"🚮 <b>Deleted:</b> {deleted_accounts}"
                )
                if STOP_BROADCAST:
                    text += "\n\n⏹️ <b>Broadcast stopped by admin.</b>"
                
                bot.edit_message_text(text, m.chat.id, status_msg.message_id, parse_mode="HTML")
                last_update_time = time.time()
            except:
                pass

    BROADCAST_RUNNING = False
    STOP_BROADCAST = False

# --- WORKER THREAD FOR DELETING ---
def delete_broadcast_worker(m):
    global DELETE_RUNNING, STOP_DELETE, LAST_BROADCAST_IDS
    
    total = len(LAST_BROADCAST_IDS)
    if total == 0:
        DELETE_RUNNING = False
        return bot.reply_to(m, "⚠️ No recent broadcast found to delete.")

    deleted = 0
    failed = 0
    
    status_msg = bot.reply_to(m, f"🗑️ <b>Deleting broadcast…</b>\nTarget: {total} chats")
    last_update_time = time.time()
    
    # Iterate over copy of dict keys
    chat_ids = list(LAST_BROADCAST_IDS.keys())
    
    for i, chat_id in enumerate(chat_ids):
        if STOP_DELETE:
            break
            
        msg_id = LAST_BROADCAST_IDS[chat_id]
        
        try:
            bot.delete_message(chat_id, msg_id)
            deleted += 1
            time.sleep(0.03)
        except:
            failed += 1
            
        # Update Status
        if time.time() - last_update_time > 3 or i == total - 1:
            try:
                text = (
                    "🗑️ <b>Deletion in progress…</b>\n\n"
                    f"🎯 <b>Target:</b> {total}\n"
                    f"✅ <b>Deleted:</b> {deleted}\n"
                    f"❌ <b>Failed:</b> {failed}"
                )
                if STOP_DELETE:
                    text += "\n\n⏹️ <b>Deletion stopped.</b>"
                    
                bot.edit_message_text(text, m.chat.id, status_msg.message_id, parse_mode="HTML")
                last_update_time = time.time()
            except:
                pass

    # Clear memory after deletion attempt
    if not STOP_DELETE:
        LAST_BROADCAST_IDS.clear()
        bot.send_message(m.chat.id, "🗑️ Broadcast message deleted.")
    else:
        bot.send_message(m.chat.id, "⏹️ Broadcast deletion stopped.")

    DELETE_RUNNING = False
    STOP_DELETE = False


# --- COMMAND: /broadcast ---
@bot.message_handler(commands=['broadcast'])
def broadcast_command(m):
    global BROADCAST_RUNNING, STOP_BROADCAST
    
    if not check_admin_strict(m): return
    
    if not m.reply_to_message:
        return bot.reply_to(m, "⚠️ Reply to a message to broadcast.")
        
    if BROADCAST_RUNNING:
        return bot.reply_to(m, "⚠️ A broadcast is already running.\nUse /stopbroadcast to stop it.")
    
    # Fetch all targets (Users + Groups)
    targets = []
    for u in users_col.find({}, {"_id": 1}): targets.append(u["_id"])
    for g in groups_col.find({}, {"_id": 1}): targets.append(g["_id"])
    targets = list(set(targets)) # Unique IDs
    
    if not targets:
        return bot.reply_to(m, "⚠️ Database is empty.")
        
    BROADCAST_RUNNING = True
    STOP_BROADCAST = False
    
    # Start Thread
    t = threading.Thread(target=broadcast_worker, args=(m, targets, m.chat.id, m.reply_to_message.message_id))
    t.start()

# --- COMMAND: /stopbroadcast ---
@bot.message_handler(commands=['stopbroadcast'])
def stop_broadcast_command(m):
    global STOP_BROADCAST, BROADCAST_RUNNING
    if not check_admin_strict(m): return
    
    if not BROADCAST_RUNNING:
        return bot.reply_to(m, "⚠️ No broadcast is running.")
        
    STOP_BROADCAST = True
    bot.reply_to(m, "🛑 Stopping broadcast...")

# --- COMMAND: /deletebroadcast ---
@bot.message_handler(commands=['deletebroadcast'])
def delete_broadcast_command(m):
    global DELETE_RUNNING, STOP_DELETE
    if not check_admin_strict(m): return
    
    if DELETE_RUNNING:
        return bot.reply_to(m, "⚠️ Deletion already in progress.\nUse /stopdelete to stop.")
        
    DELETE_RUNNING = True
    STOP_DELETE = False
    
    t = threading.Thread(target=delete_broadcast_worker, args=(m,))
    t.start()

# --- COMMAND: /stopdelete ---
@bot.message_handler(commands=['stopdelete'])
def stop_delete_command(m):
    global STOP_DELETE, DELETE_RUNNING
    if not check_admin_strict(m): return
    
    if not DELETE_RUNNING:
        return bot.reply_to(m, "⚠️ No deletion process running.")
        
    STOP_DELETE = True
    bot.reply_to(m, "🛑 Stopping deletion...")


# =========================================================
# 👤 USER COMMANDS
# =========================================================

@bot.message_handler(commands=['start'])
def start(message):
    get_user(message.from_user.id, message.from_user.first_name)
    track_chat(message)
    text = (
        "✨ <b>Hey, I’m Miku 🌸</b>\n"
        "━━━━━━━━━━━━━━\n"
        "💗 Simple, smart & friendly chat bot\n\n"
        "• 💬 Easy conversations\n"
        "• 🎮 Games and fun features\n"
        "• 👥 Group & private support\n"
        "• 🛡 Safe and smooth experience\n\n"
        "✦ <b>Choose an option below</b>"
    )
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("💬 Talk to Miku", callback_data="talk"),
        InlineKeyboardButton("🎮 Games", callback_data="games")
    )
    kb.add(InlineKeyboardButton("👥 Add to Group", url=f"https://t.me/{bot.get_me().username}?startgroup=true"))
    bot.send_message(message.chat.id, text, reply_markup=kb, parse_mode="HTML")

@bot.message_handler(commands=['close', 'open'])
def toggle_group_eco(m):
    if m.chat.type == 'private': 
        return bot.reply_to(m, "❌ This command works in groups only.", parse_mode="HTML")
    
    command_raw = m.text.split()[0].lower()
    command_name = command_raw.split("@")[0].replace("/", "")
    
    user_id = m.from_user.id
    is_authorized = False
    
    try:
        if str(user_id) == str(OWNER_ID) or user_id in ADMIN_IDS:
            is_authorized = True
        elif m.from_user.username == "GroupAnonymousBot":
            is_authorized = True
        else:
            chat_admins = bot.get_chat_administrators(m.chat.id)
            admin_ids = [admin.user.id for admin in chat_admins]
            if user_id in admin_ids:
                is_authorized = True
            else:
                is_authorized = False
    except Exception as e:
        print(f"Auth Error: {e}")
        is_authorized = False

    if not is_authorized:
        if command_name == "close":
            return bot.reply_to(m, "⚠️ Only group admins can close economy.", parse_mode="HTML")
        else:
            return bot.reply_to(m, "⚠️ Only group admins can open economy.", parse_mode="HTML")
        
    is_close = (command_name == "close")
    
    groups_col.update_one(
        {"_id": m.chat.id}, 
        {"$set": {"eco_disabled": is_close, "name": m.chat.title}}, 
        upsert=True
    )
    
    if is_close:
        bot.reply_to(m, "⛔ Economy commands are now disabled in this group.", parse_mode="HTML")
    else:
        bot.reply_to(m, "✅ Economy commands are now enabled in this group.", parse_mode="HTML")

@bot.message_handler(commands=['economy'])
def economy_guide(m):
    text = (
        "💰 <b>MIKU ECONOMY SYSTEM OVERVIEW</b>\n\n"
        "💬 <b>How it works:</b>\n"
        "Use Miku’s economy system to earn, manage, gift, and protect virtual money in your group.\n\n"
        "• /daily — Claim $1500 daily reward\n"
        "• /claim — Unlock group rewards based on members\n"
        "• /bal — Check your or another user’s balance\n"
        "• /rob (reply) &lt;amount&gt; — Rob money from a user\n"
        "• /kill (reply) — Kill a user & earn $200–$600\n"
        "• /revive — Revive yourself or a replied user\n"
        "• /protect 1d|2d|3d — Buy protection from robbery\n"
        "• /give (reply) &lt;amount&gt; — Transfer money\n"
        "• /toprich — Top 10 richest users\n"
        "• /topkill — Top 10 killers\n"
        "• /show — Check protection status (Costs $1000)"
    )
    try:
        bot.send_message(m.chat.id, text, parse_mode="HTML")
    except Exception as e:
        print(f"Economy Command Error: {e}")
        bot.reply_to(m, "❌ Error displaying economy guide.")

@bot.message_handler(commands=['daily'])
def daily(m):
    if not can_play(m): return
    uid = m.from_user.id
    u = get_user(uid, m.from_user.first_name)
    
    if time.time() - u["last_daily"] < DAY_SECONDS:
        rem = int(DAY_SECONDS - (time.time() - u["last_daily"]))
        hours, mins = rem // 3600, (rem % 3600) // 60
        return bot.reply_to(m, f"⏳ Come back in <b>{hours}h {mins}m</b>", parse_mode="HTML")
    
    users_col.update_one({"_id": uid}, {"$inc": {"balance": 1500}, "$set": {"last_daily": time.time()}})
    bot.reply_to(m, "✅ You received: $1500 daily reward!", parse_mode="HTML")

@bot.message_handler(commands=['claim'])
def claim_bonus(m):
    if m.chat.type == 'private':
        return bot.reply_to(m, "❌ <b>This command works in groups only.</b>\nAdd me to a group to claim bonus.", parse_mode="HTML")

    chat_id = m.chat.id
    
    try:
        members_count = bot.get_chat_member_count(chat_id)
    except:
        return bot.reply_to(m, "⚠️ Could not fetch member count. Make sure I'm Admin!", parse_mode="HTML")

    if members_count < 100:
        return bot.reply_to(m, "❌ This group needs at least 100 members to claim rewards.", parse_mode="HTML")

    group_data = groups_col.find_one({"_id": chat_id})
    if group_data and group_data.get("claimed", False):
        return bot.reply_to(m, "⚠️ This group has already claimed its reward.", parse_mode="HTML")

    reward_amount = 0
    if 100 <= members_count < 500:
        reward_amount = 10000
    elif 500 <= members_count < 1000:
        reward_amount = 20000
    elif members_count >= 1000:
        reward_amount = 30000
    
    if reward_amount == 0:
        return bot.reply_to(m, "❌ This group needs at least 100 members to claim rewards.", parse_mode="HTML")

    uid = m.from_user.id
    name = m.from_user.first_name
    get_user(uid, name)
    
    users_col.update_one({"_id": uid}, {"$inc": {"balance": reward_amount}})
    groups_col.update_one(
        {"_id": chat_id},
        {"$set": {
            "claimed": True, 
            "claimed_by": uid,
            "claimed_at": time.time(),
            "name": m.chat.title
        }},
        upsert=True
    )

    msg = (
        "✅ <b>Group Bonus Claimed!</b>\n\n"
        f"🎉 <b>{name}</b> received <b>${reward_amount:,}</b>\n"
        "for adding Miku to this group!"
    )
    bot.reply_to(m, msg, parse_mode="HTML")

@bot.message_handler(commands=['show'])
def show_protection_status(m):
    if not can_play(m): return 
    COST = 1000
    args = m.text.split()
    if len(args) != 2 or args[1] != "1000":
        return bot.reply_to(m, "❌ Invalid amount.\nUsage: /show 1000")

    if not m.reply_to_message:
        return bot.reply_to(m, "⚠️ Reply to a user to check protection.")

    sender_id = m.from_user.id
    sender = get_user(sender_id, m.from_user.first_name)

    if sender["balance"] < COST:
        return bot.reply_to(m, "⚠️ Not enough balance to perform this action.")

    users_col.update_one({"_id": sender_id}, {"$inc": {"balance": -COST}})
    target_id = m.reply_to_message.from_user.id
    target_name = m.reply_to_message.from_user.first_name
    user = users_col.find_one({"_id": target_id})
    protection_time = user.get("protection", 0) if user else 0
    current_time = time.time()

    # ====== 👁️ UPDATED SHOW DESIGN ======
    header = (
        "🛡️ <b>Protection status</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👤 User Name  : {target_name}\n"
        "💰 Checked Amount : $1000\n\n"
    )

    if protection_time > current_time:
        diff = int(protection_time - current_time)
        days = diff // 86400
        hours = (diff % 86400) // 3600
        mins = (diff % 3600) // 60
        final_msg = (
            f"{header}"
            "🛡️ Protection State: Active\n"
            f"⏳ Time Remaining : {days:02d}d {hours:02d}h {mins:02d}m"
        )
    else:
        final_msg = f"{header}🛡️ Protection State: Not Protected"

    try:
        bot.send_message(sender_id, final_msg, parse_mode="HTML")
        if m.chat.type in ['group', 'supergroup']:
            bot.reply_to(m, "📩 Protection details have been sent to your DM!")
    except Exception:
        bot.reply_to(m, "⚠️ Please start me in private to view protection details.")

@bot.message_handler(commands=['bal', 'balance'])
def bal(m):
    if not can_play(m): return 
    try:
        track_chat(m)
        if m.reply_to_message:
            uid = m.reply_to_message.from_user.id
            name = m.reply_to_message.from_user.first_name
        else:
            uid = m.from_user.id
            name = m.from_user.first_name
            
        u = get_user(uid, name)
        
        higher_bal = users_col.count_documents({"balance": {"$gt": u["balance"]}})
        same_bal_higher_id = users_col.count_documents({"balance": u["balance"], "_id": {"$lt": u["_id"]}})
        rank = higher_bal + same_bal_higher_id + 1
        
        status = "dead" if check_death(uid) else "alive"
        msg = f"👤 <b>Name:</b> {u['name']}\n💰 <b>Total Balance:</b> ${u['balance']}\n🏆 <b>Global Rank:</b> {rank}\n❤️ <b>Status:</b> {status}\n⚔️ <b>Kills:</b> {u['kills']}"
        bot.reply_to(m, msg, parse_mode="HTML")
    except Exception as e:
        bot.reply_to(m, "⚠️ Error checking balance. User might be invalid.", parse_mode="HTML")

@bot.message_handler(commands=['give'])
def give_money(m):
    if not can_play(m): return
    if not m.reply_to_message: return bot.reply_to(m, "⚠️ Reply to a user to give.", parse_mode="HTML")
    
    sender_id = m.from_user.id
    receiver_id = m.reply_to_message.from_user.id
    
    if sender_id == receiver_id: return bot.reply_to(m, "⚠️ Cannot give money to yourself.", parse_mode="HTML")
    
    try: amt = int(m.text.split()[1])
    except: return bot.reply_to(m, "⚠️ Usage: /give amount", parse_mode="HTML")
    
    if amt <= 0: return bot.reply_to(m, "❌ Invalid amount.", parse_mode="HTML")
    
    sender = get_user(sender_id, m.from_user.first_name)
    receiver = get_user(receiver_id, m.reply_to_message.from_user.first_name)
    
    if sender["balance"] < amt:
        return bot.reply_to(m, "❌ You don't have enough money.", parse_mode="HTML")
        
    users_col.update_one({"_id": sender_id}, {"$inc": {"balance": -amt}})
    users_col.update_one({"_id": receiver_id}, {"$inc": {"balance": amt}})
    
    bot.reply_to(m, f"✅ <b>${amt}</b> has been given to <b>{receiver['name']}</b> 💸", parse_mode="HTML")

@bot.message_handler(commands=['kill'])
def kill(m):
    if not can_play(m): return
    if not m.reply_to_message: return bot.reply_to(m, "⚠️ Reply to a user to kill.", parse_mode="HTML")
    
    try:
        k_id, v_id = m.from_user.id, m.reply_to_message.from_user.id
        if k_id == v_id: return bot.reply_to(m, "⚠️ Cannot kill yourself.", parse_mode="HTML")
        
        killer = get_user(k_id, m.from_user.first_name)
        victim = get_user(v_id, m.reply_to_message.from_user.first_name)
        
        if check_death(v_id): return bot.reply_to(m, f"💀 <b>{victim['name']}</b> is already dead.", parse_mode="HTML")
        if time.time() < victim["protection"]: return bot.reply_to(m, f"🛡️ <b>{victim['name']}</b> is protected.", parse_mode="HTML")
        
        reward = random.randint(200, 600)
        users_col.update_one({"_id": k_id}, {"$inc": {"kills": 1, "balance": reward}})
        users_col.update_one({"_id": v_id}, {"$set": {"status": "dead", "death_time": time.time()}})
        bot.reply_to(m, f"👤 {killer['name']} killed {victim['name']}!\n💰 Earned: ${reward}", parse_mode="HTML")
    except Exception as e:
        bot.reply_to(m, "⚠️ Error executing kill command.", parse_mode="HTML")

@bot.message_handler(commands=['protect'])
def protect(m):
    if not can_play(m): return
    uid = m.from_user.id
    u = get_user(uid, m.from_user.first_name)
    
    if u["protection"] > time.time():
        rem = int(u["protection"] - time.time())
        day, hour, mins = rem // 86400, (rem % 86400) // 3600, (rem % 3600) // 60
        return bot.reply_to(m, f"🛡️ You are already protected!\n⏳ Remaining: {day}d {hour}h {mins}m", parse_mode="HTML")
    
    try: plan = m.text.split()[1].lower()
    except: return bot.reply_to(m, "⚠️ Usage: /protect 1d 2d 3d", parse_mode="HTML")
    
    # ====== 🛡️ UPDATED COSTS ======
    costs = {"1d": 200, "2d": 400, "3d": 600}
    durs = {"1d": DAY_SECONDS, "2d": DAY_SECONDS*2, "3d": DAY_SECONDS*3}
    
    if plan not in costs: return bot.reply_to(m, "⚠️ Usage: /protect 1d 2d 3d", parse_mode="HTML")
    if u["balance"] < costs[plan]: return bot.reply_to(m, "⚠️ Not enough money.", parse_mode="HTML")
    
    new_time = time.time() + durs[plan]
    users_col.update_one({"_id": uid}, {"$inc": {"balance": -costs[plan]}, "$set": {"protection": new_time}})
    
    msg = f"🛡️ You are now protected for {plan}."
    if u.get("status") == "dead":
        msg += "\n⚠️ But your status is still dead until revive."
        
    bot.reply_to(m, msg, parse_mode="HTML")

@bot.message_handler(commands=['rob'])
def rob(m):
    if not can_play(m): return
    if not m.reply_to_message: return bot.reply_to(m, "⚠️ Reply to a user to rob.", parse_mode="HTML")
    
    r_id, v_id = m.from_user.id, m.reply_to_message.from_user.id
    if r_id == v_id: return bot.reply_to(m, "⚠️ Cannot rob yourself.", parse_mode="HTML")
    
    robber = get_user(r_id, m.from_user.first_name)
    victim = get_user(v_id, m.reply_to_message.from_user.first_name)
    
    if time.time() < victim["protection"]: return bot.reply_to(m, f"🛡️ <b>{victim['name']}</b> is protected.", parse_mode="HTML")
    
    try: amt = int(m.text.split()[1])
    except: amt = 1000
    
    if amt <= 0: return bot.reply_to(m, "❌ Invalid amount.", parse_mode="HTML")
    if victim["balance"] <= 0: return bot.reply_to(m, f"❌ {victim['name']} has no money.", parse_mode="HTML")
    if amt > victim["balance"]: return bot.reply_to(m, f"❌ {victim['name']} has only ${victim['balance']}.", parse_mode="HTML")
    
    users_col.update_one({"_id": r_id}, {"$inc": {"balance": amt}})
    users_col.update_one({"_id": v_id}, {"$inc": {"balance": -amt}})
    
    bot.reply_to(m, f"👤 <b>{robber['name']}</b> successfully robbed <b>${amt}</b> from <b>{victim['name']}</b>", parse_mode="HTML")

@bot.message_handler(commands=['revive'])
def revive(m):
    if not can_play(m): return
    sender_id = m.from_user.id
    sender = get_user(sender_id, m.from_user.first_name)
    cost = 400

    if m.reply_to_message:
        target_id = m.reply_to_message.from_user.id
        target = get_user(target_id, m.reply_to_message.from_user.first_name)
        
        if target["status"] == "alive":
            return bot.reply_to(m, f"⚠️ <b>{target['name']}</b> is already alive!", parse_mode="HTML")
            
        if sender["balance"] < cost:
            return bot.reply_to(m, f"❌ You need ${cost} to revive {target['name']}.", parse_mode="HTML")
            
        users_col.update_one({"_id": target_id}, {"$set": {"status": "alive", "death_time": 0}})
        users_col.update_one({"_id": sender_id}, {"$inc": {"balance": -cost}})
        bot.reply_to(m, f"🚑 You revived <b>{target['name']}</b> for ${cost}!", parse_mode="HTML")
    else:
        if sender["status"] == "alive":
            return bot.reply_to(m, "⚠️ You are already alive!", parse_mode="HTML")
        
        if sender["balance"] < cost:
            return bot.reply_to(m, f"❌ You need ${cost} to revive yourself.", parse_mode="HTML")
            
        users_col.update_one({"_id": sender_id}, {"$set": {"status": "alive", "death_time": 0}, "$inc": {"balance": -cost}})
        bot.reply_to(m, f"❤️ You revived yourself! -${cost}", parse_mode="HTML")

@bot.message_handler(commands=['items', 'shop'])
def shop(m):
    if not can_play(m): return
    text = "🛒 <b>ITEM SHOP</b>\n\n"
    for k, v in SHOP_ITEMS.items():
        text += f"{v['icon']} <b>{v['name']}</b> — ${v['price']}\n"
    text += "\n🎁 Usage: /gift (reply) itemname"
    bot.reply_to(m, text, parse_mode="HTML")

@bot.message_handler(commands=['gift'])
def gift(m):
    if not can_play(m): return
    if not m.reply_to_message: return bot.reply_to(m, "⚠️ Reply to a user to gift.", parse_mode="HTML")
    try: item = m.text.split(maxsplit=1)[1].lower()
    except: return bot.reply_to(m, "⚠️ Usage: /gift <itemname>", parse_mode="HTML")
    
    key = next((k for k, v in SHOP_ITEMS.items() if k in item or v['name'].lower() in item), None)
    if not key: return bot.reply_to(m, "❌ Item not found.", parse_mode="HTML")
    
    s_id, r_id = m.from_user.id, m.reply_to_message.from_user.id
    sender = get_user(s_id, m.from_user.first_name)
    rec = get_user(r_id, m.reply_to_message.from_user.first_name)
    
    price = SHOP_ITEMS[key]['price']
    if sender["balance"] < price: return bot.reply_to(m, "❌ Not enough money.", parse_mode="HTML")
    
    users_col.update_one({"_id": s_id}, {"$inc": {"balance": -price}})
    users_col.update_one({"_id": r_id}, {"$inc": {f"inventory.{key}": 1}})
    
    bot.reply_to(m, f"🎁 {sender['name']} sent a {SHOP_ITEMS[key]['icon']} {SHOP_ITEMS[key]['name']} to {rec['name']} 💖", parse_mode="HTML")

@bot.message_handler(commands=['toprich'])
def toprich(m):
    if not can_play(m): return 
    top_users = users_col.find().sort("balance", -1).limit(10)
    msg = "🏆 <b>TOP 10 RICHEST</b>\n\n"
    rank_icons = ["①","②","③","④","⑤","⑥","⑦","⑧","⑨","⑩"]
    for i, u in enumerate(top_users):
        name = u.get("name", "Unknown").replace("<", "&lt;")
        msg += f"{rank_icons[i]} {name} ➜ ${u['balance']}\n"
    bot.reply_to(m, msg, parse_mode="HTML")

@bot.message_handler(commands=['topkill'])
def topkill(m):
    if not can_play(m): return
    top_users = users_col.find().sort("kills", -1).limit(10)
    msg = "💀 <b>TOP 10 KILLERS</b>\n\n"
    rank_icons = ["①","②","③","④","⑤","⑥","⑦","⑧","⑨","⑩"]
    for i, u in enumerate(top_users):
        name = u.get("name", "Unknown").replace("<", "&lt;")
        msg += f"{rank_icons[i]} {name} ➜ {u['kills']} Kills\n"
    bot.reply_to(m, msg, parse_mode="HTML")

@bot.message_handler(commands=['status'])
def system_status(m):
    if not is_admin(m.from_user.id): return
    
    start_time = time.time()
    
    try:
        db_stats = users_col.database.command("dbstats")
        used_size_bytes = db_stats.get('storageSize', 0)
        used_mb = used_size_bytes / (1024 * 1024)
        free_mb = DB_LIMIT_MB - used_mb
        percentage = (used_mb / DB_LIMIT_MB) * 100
        total_objects = db_stats.get('objects', 0)
    except Exception as e:
        print(f"DB Stats Error: {e}")
        used_mb = 0
        free_mb = DB_LIMIT_MB
        percentage = 0
        total_objects = 0

    users_count = users_col.count_documents({})
    groups_count = groups_col.count_documents({})
    
    pipeline = [{"$group": {"_id": None, "total": {"$sum": "$balance"}}}]
    eco_res = list(users_col.aggregate(pipeline))
    total_eco = eco_res[0]['total'] if eco_res else 0
    
    dead_users = users_col.count_documents({"status": "dead"})
    
    end_time = time.time()
    ping = int((end_time - start_time) * 1000)
    
    uptime_s = int(time.time() - BOT_START_TIME)
    uptime_h = uptime_s // 3600
    uptime_m = (uptime_s % 3600) // 60
    
    msg = f"""
📊 <b>SYSTEM LIVE STATUS</b>
━━━━━━━━━━━━━━━━
⏱ <b>Uptime:</b> {uptime_h}h {uptime_m}m
📶 <b>Ping:</b> {ping}ms

💾 <b>DATABASE STORAGE</b>
├ <b>Used:</b> {used_mb:.2f} MB
├ <b>Free:</b> {free_mb:.2f} MB
├ <b>Total Limit:</b> {DB_LIMIT_MB} MB
└ <b>Usage:</b> {percentage:.1f}%

👥 <b>Total Users:</b> {users_count} ({total_objects} Docs)
🛡 <b>Total Groups:</b> {groups_count}
💰 <b>Total Economy:</b> ${total_eco:,}
💀 <b>Dead Users:</b> {dead_users}
━━━━━━━━━━━━━━━━
✅ <b>System:</b> Fully Operational
    """
    bot.reply_to(m, msg, parse_mode="HTML")

# =========================================================
# 👑 ADMIN COMMANDS
# =========================================================

@bot.message_handler(commands=['cleandb'])
def clean_database(m):
    if not check_admin(m): return

    bot.reply_to(m, "🧹 **Scanning for useless data...**", parse_mode="HTML")
    result = users_col.delete_many({
        "balance": {"$lt": 1000},
        "status": "dead"
    })
    bot.reply_to(m, f"✅ **Cleanup Complete!**\n\n🗑️ Deleted **{result.deleted_count}** useless users.\n💾 Space Freed successfully!", parse_mode="HTML")

@bot.message_handler(commands=['reviveall'])
def revive_all_command(m):
    if not check_admin(m): return

    result = users_col.update_many(
        {"status": "dead"},
        {"$set": {"status": "alive", "death_time": 0}}
    )
    msg = f"😇 <b>God Mode Activated!</b>\n\n✨ <b>{result.modified_count}</b> users have been revived instantly."
    bot.reply_to(m, msg, parse_mode="HTML")

@bot.message_handler(commands=['setbal'])
def setbal(m):
    if str(m.from_user.id) != str(OWNER_ID): return bot.reply_to(m, "⚠️ <b>Only owner/admin can use this command.</b>", parse_mode="HTML")
    if not m.reply_to_message: return bot.reply_to(m, "⚠️ Reply to user.", parse_mode="HTML")
    try: amt = int(m.text.split()[1])
    except: return bot.reply_to(m, "⚠️ Usage: /setbal <amount>", parse_mode="HTML")
    tid = m.reply_to_message.from_user.id
    get_user(tid, m.reply_to_message.from_user.first_name)
    users_col.update_one({"_id": tid}, {"$set": {"balance": amt}})
    bot.reply_to(m, f"✅ Balance set to ${amt}.", parse_mode="HTML")

@bot.message_handler(commands=['transfer'])
def transfer(m):
    if not check_admin(m): return
    if not m.reply_to_message: return bot.reply_to(m, "⚠️ Reply to user.", parse_mode="HTML")
    try: amt = int(m.text.split()[1])
    except: return bot.reply_to(m, "❌ Usage: /transfer <amount>", parse_mode="HTML")
    
    target_id = m.reply_to_message.from_user.id
    target_name = m.reply_to_message.from_user.first_name
    get_user(target_id, target_name)

    users_col.update_one({"_id": target_id}, {"$inc": {"balance": amt}})
    action = "Added" if amt > 0 else "Removed"
    bot.reply_to(m, f"💰 <b>{action} ${abs(amt)}</b> to {target_name}'s balance.", parse_mode="HTML")

@bot.message_handler(commands=['giveprot'])
def giveprot(m):
    if not check_admin(m): return
    if not m.reply_to_message: return bot.reply_to(m, "⚠️ Reply to user.", parse_mode="HTML")
    tid = m.reply_to_message.from_user.id
    target = get_user(tid, m.reply_to_message.from_user.first_name)
    new_prot = time.time() + (DAY_SECONDS * 2)
    users_col.update_one({"_id": tid}, {"$set": {"protection": new_prot}})
    bot.reply_to(m, f"🛡️ Given 2 Days Protection to {target['name']}.", parse_mode="HTML")

@bot.message_handler(commands=['breakshield'])
def breakprot(m):
    if not check_admin(m): return
    if not m.reply_to_message: return bot.reply_to(m, "⚠️ Reply to user.", parse_mode="HTML")
    tid = m.reply_to_message.from_user.id
    target = get_user(tid, m.reply_to_message.from_user.first_name)
    users_col.update_one({"_id": tid}, {"$set": {"protection": 0}})
    bot.reply_to(m, f"🛡️ Protection Removed from {target['name']}.", parse_mode="HTML")

@bot.message_handler(commands=['lockeconomy'])
def lockeco(m):
    if not check_admin(m): return
    config_col.update_one({"_id": "settings"}, {"$set": {"locked": True}}, upsert=True)
    bot.reply_to(m, "🔒 Economy LOCKED.", parse_mode="HTML")

@bot.message_handler(commands=['unlockeconomy'])
def unlockeco(m):
    if not check_admin(m): return
    config_col.update_one({"_id": "settings"}, {"$set": {"locked": False}}, upsert=True)
    bot.reply_to(m, "🔓 Economy UNLOCKED.", parse_mode="HTML")

@bot.message_handler(commands=['stopbroadcast'])
def stop_broadcast(m):
    global STOP_BROADCAST, BROADCAST_RUNNING
    if not check_admin(m): return
    
    if not BROADCAST_RUNNING:
        return bot.reply_to(m, "⚠️ <b>No broadcast is running!</b>", parse_mode="HTML")
    
    STOP_BROADCAST = True
    bot.reply_to(m, "🛑 <b>Stopping broadcast...</b> please wait.", parse_mode="HTML")

def broadcast_thread(m, targets, is_reply, msg_id, markup, msg_text, from_chat_id):
    global BROADCAST_RUNNING, STOP_BROADCAST
    
    sent = 0
    failed = 0
    
    status_msg = bot.reply_to(m, f"📢 <b>Broadcast Started!</b>\n🎯 Targets: {len(targets)}\n\n⏳ Sending...", parse_mode="HTML")
    
    for chat_id in targets:
        if STOP_BROADCAST:
            break
            
        try:
            if is_reply:
                bot.copy_message(chat_id, from_chat_id, msg_id, reply_markup=markup)
            else:
                bot.send_message(chat_id, msg_text, parse_mode="HTML")
            sent += 1
            time.sleep(0.05)
        except Exception:
            failed += 1
            
    final_text = f"✅ <b>Broadcast Complete!</b>\n\n📢 Sent to: {sent}\n❌ Failed: {failed}"
    if STOP_BROADCAST:
        final_text += "\n🛑 <b>Stopped by Admin</b>"
        
    try:
        bot.edit_message_text(final_text, m.chat.id, status_msg.message_id, parse_mode="HTML")
    except:
        bot.send_message(m.chat.id, final_text, parse_mode="HTML")
        
    BROADCAST_RUNNING = False
    STOP_BROADCAST = False

@bot.message_handler(commands=['broadcast'])
def broadcast(m):
    global BROADCAST_RUNNING, STOP_BROADCAST
    
    if not check_admin(m): return
    
    if BROADCAST_RUNNING:
        return bot.reply_to(m, "⚠️ <b>A broadcast is already running!</b>\nUse /stopbroadcast to stop it.", parse_mode="HTML")
    
    markup = None
    is_reply = False
    msg_text = None
    msg_id = None
    
    if m.reply_to_message:
        is_reply = True
        msg_id = m.reply_to_message.message_id
        markup = m.reply_to_message.reply_markup
    elif len(m.text.split()) > 1:
        msg_text = m.text.split(maxsplit=1)[1]
    else:
        return bot.reply_to(m, "⚠️ <b>Usage:</b>\n1. Reply to media/text with /broadcast\n2. Type /broadcast <message>", parse_mode="HTML")

    targets = []
    for u in users_col.find({}, {"_id": 1}): targets.append(u["_id"])
    for g in groups_col.find({}, {"_id": 1}): targets.append(g["_id"])
    targets = list(set(targets))
    
    if not targets:
        return bot.reply_to(m, "⚠️ No users found in database.", parse_mode="HTML")

    BROADCAST_RUNNING = True
    STOP_BROADCAST = False
    
    t = threading.Thread(target=broadcast_thread, args=(m, targets, is_reply, msg_id, markup, msg_text, m.chat.id))
    t.start()

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if call.data == "help": 
        economy_guide(call.message)
    elif call.data == "games":
        text = (
            "🎮 <b>Game Features</b>\n\n"
            "• /economy — View the complete Economy System guide\n"
            "• /close — Disable all gaming commands in the group\n"
            "• /open — Enable all gaming commands in the group"
        )
        bot.send_message(call.message.chat.id, text, parse_mode="HTML")
    elif call.data == "talk":
        bot.send_message(call.message.chat.id, "💬 Just say 'Hi Miku'!", parse_mode="HTML")
    bot.answer_callback_query(call.id)
