import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, WebAppInfo
import requests
import time
import threading

BOT_TOKEN = '8610173918:AAEoAi6_QsCc_JTBkgKYJtST6I7OADIpqE0'
MINI_APP_URL = 'https://incomebot.pages.dev/' # আপনার ওয়েব অ্যাপ লিংক
VIDEO_URL = 'https://t.me/Tutorial_Video_Xvm/10' # টেলিগ্রাম ফাইল আইডি

bot = telebot.TeleBot(BOT_TOKEN)

ADMIN_ID = [6863990982]

# ================= 2 Firebase Databases (From index.html) =================
DB_URLS = [
    "https://freeincomexv-default-rtdb.firebaseio.com",
    "https://freeincomexv2-default-rtdb.firebaseio.com"
]

# ================= Mandatory Channels =================
# আপনার দেওয়া নতুন চ্যানেল যুক্ত করা হয়েছে
REQUIRED_CHANNELS = [
    {"username": "@FreeIncomeXv", "name": "Free Income XV", "url": "https://t.me/FreeIncomeXv"}
]

# গ্লোবাল ভেরিয়েবল (ব্রডকাস্ট ক্যানসেল করার জন্য)
broadcast_status = {"is_running": False, "cancel": False}

# ================= Debug Helper =================
def safe_json(response, context=""):
    """
    Firebase theke HTTP 200 e vul/permission error asleo seta valid JSON hওয়ায়
    ager code bhulbhabe seta 'data ache' dhore nito (karon dict shobshomoy truthy).
    Ekhon status_code check kora hocche ebong {"error": ...} response ele
    sorasori console-e print kore None return kora hocche, jate asol karon bojha jay.
    """
    try:
        data = response.json()
    except Exception as e:
        print(f"[FIREBASE ERROR][{context}] JSON parse failed | status={response.status_code} | body={response.text[:200]} | err={e}")
        return None

    if response.status_code != 200:
        print(f"[FIREBASE ERROR][{context}] status {response.status_code} | body={data}")
        return None

    if isinstance(data, dict) and "error" in data:
        print(f"[FIREBASE ERROR][{context}] permission/rule error: {data.get('error')}  "
              f"-> Check your Firebase Rules (Read/Write must be allowed).")
        return None

    return data

# ================= Database Routing Logic =================
def get_user_db_url(uid):
    uid_str = str(uid)
    # যেহেতু ওয়েব অ্যাপে র‍্যান্ডম ডাটাবেজ সিলেক্ট হয়, তাই আগে চেক করতে হবে ইউজার কোন ডাটাবেজে আছে
    try:
        r0 = requests.get(f"{DB_URLS[0]}/users/{uid_str}.json?shallow=true")
        if safe_json(r0, f"get_user_db_url:{uid_str}:db0"):
            return DB_URLS[0]
        r1 = requests.get(f"{DB_URLS[1]}/users/{uid_str}.json?shallow=true")
        if safe_json(r1, f"get_user_db_url:{uid_str}:db1"):
            return DB_URLS[1]
    except Exception as e:
        print(f"[FIREBASE ERROR][get_user_db_url:{uid_str}] {e}")
    
    # নতুন ইউজার হলে 50/50 সিস্টেমে ভাগ করে দেওয়া হবে
    return DB_URLS[int(uid) % 2]

def get_referral_reward():
    # অ্যাডমিন প্যানেল থেকে রেফার বোনাস ডাটা ফেচ করা, না পেলে ডিফল্ট 50 টাকা
    try:
        r = requests.get(f"{DB_URLS[0]}/admin_settings/referral_reward.json")
        res = safe_json(r, "get_referral_reward")
        if res is not None:
            return float(res)
    except Exception as e:
        print(f"[FIREBASE ERROR][get_referral_reward] {e}")
    return 50.0

# ================= 1. Membership Check Logic =================
def is_subscribed(user_id):
    for ch in REQUIRED_CHANNELS:
        try:
            status = bot.get_chat_member(ch["username"], user_id).status
            if status in ['left', 'kicked']:
                return False
        except Exception as e:
            # যদি বট এডমিন না থাকে বা ইউজারকে খুঁজে না পায়, তাহলে False ধরবে
            print(f"[SUBSCRIBE CHECK ERROR] channel={ch['username']} user={user_id} err={e} -> সাধারণত এর মানে বট ওই চ্যানেলে Admin নেই।")
            return False
    return True

def get_join_markup(ref_id="None"):
    markup = InlineKeyboardMarkup(row_width=1)
    
    # ডাইনামিকভাবে রিকোয়ার্ড চ্যানেলের বাটন তৈরি
    for ch in REQUIRED_CHANNELS:
        markup.add(InlineKeyboardButton(text=f"📢 {ch['name']}", url=ch['url']))
        
    # কনফার্ম বাটন
    btn_confirm = InlineKeyboardButton(text="✅ কনফার্ম", callback_data=f"check_join_{ref_id}")
    markup.add(btn_confirm)
    return markup

# ================= 2. Main Logic (Registration & Menu) =================
def process_user_registration_and_menu(chat_id, uid, name, ref_id):
    db_url = get_user_db_url(uid)
    
    # ইউজার ডাটাবেজে আছে কি না চেক করা
    # গুরুত্বপূর্ণ: শুধু 'channel_left' ফিল্ড থাকলেই সেটা "আগে থেকে রেজিস্ট্রার্ড" ধরা যাবে না —
    # track_channel_membership হ্যান্ডলার চ্যানেলে জয়েন করা মাত্রই (কনফার্ম করার আগেই)
    # শুধু channel_left ফিল্ড লিখে দেয়। আসল রেজিস্ট্রেশন হয়েছে কিনা বোঝার জন্য 'joined' ফিল্ড চেক করা হচ্ছে।
    r_check = requests.get(f"{db_url}/users/{uid}.json")
    check_user = safe_json(r_check, f"check_user:{uid}")
    is_already_registered = bool(check_user) and "joined" in check_user
    print(f"[REGISTER DEBUG] uid={uid} check_user={check_user} is_already_registered={is_already_registered}")
    
    if not is_already_registered:
        # নতুন ইউজার সেভ করা (ঠিক index.html এর ভেরিয়েবল অনুযায়ী)
        new_user_data = {
            "name": name, 
            "balance": 0, 
            "lifetime_earned": 0, 
            "refs": 0, 
            "ref_income": 0, 
            "completed_tasks": {},
            "joined": int(time.time() * 1000)
        }
        requests.patch(f"{db_url}/users/{uid}.json", json=new_user_data)
        
        # রেফারেল চেক করা (যদি কনফার্ম বাটনের সাথে রেফার আইডি এসে থাকে)
        print(f"[REFERRAL DEBUG] new_user={uid} ref_id={ref_id!r}")
        try:
            if ref_id and ref_id != "None" and ref_id.isdigit():
                if ref_id != str(uid):
                    ref_db = get_user_db_url(ref_id)
                    r_ref = requests.get(f"{ref_db}/users/{ref_id}.json")
                    ref_data = safe_json(r_ref, f"referral_lookup:{ref_id}")
                    print(f"[REFERRAL DEBUG] ref_db={ref_db} ref_data_found={bool(ref_data)}")

                    if ref_data:
                        reward = get_referral_reward()
                        print(f"[REFERRAL DEBUG] reward={reward}")

                        # আগের ব্যালেন্সগুলো ফেচ করা
                        curr_bal = ref_data.get('balance', 0)
                        curr_life = ref_data.get('lifetime_earned', curr_bal)
                        curr_refs = ref_data.get('refs', 0)
                        curr_ref_inc = ref_data.get('ref_income', 0)

                        # নতুন ডাটা আপডেট করা
                        update_data = {
                            "balance": curr_bal + reward,
                            "lifetime_earned": curr_life + reward,
                            "refs": curr_refs + 1,
                            "ref_income": curr_ref_inc + reward
                        }
                        r_patch = requests.patch(f"{ref_db}/users/{ref_id}.json", json=update_data)
                        patched = safe_json(r_patch, f"referral_patch:{ref_id}")
                        print(f"[REFERRAL DEBUG] patch_success={patched is not None}")

                        # রেফারারকে মেসেজ পাঠানো
                        try:
                            bot.send_message(ref_id, f"🎉 রেফার সাকসেসফুল! আপনার একাউন্টে ৳{reward} জমা হয়েছে।")
                        except Exception as e:
                            print(f"[REFERRAL DEBUG] could not DM referrer {ref_id}: {e}  (ইউজার হয়তো বট ব্লক করেছে, বা কখনো /start দেয়নি)")
                    else:
                        print(f"[REFERRAL DEBUG] referrer id {ref_id} not found in either database, or Firebase denied read.")
        except Exception as e:
            print(f"[REFERRAL ERROR] referral processing crashed for new_user={uid}, ref_id={ref_id}: {e}")

    # ইনলাইন বাটন তৈরি (Mini App, Video & Referral)
    markup = InlineKeyboardMarkup(row_width=1)
    web_app = WebAppInfo(url=MINI_APP_URL)
    btn_app = InlineKeyboardButton(text="💰 ইনকাম শুরু করুন", web_app=web_app)
    btn_video = InlineKeyboardButton(text="🎬 কাজ যেভাবে করবেন ভিডিও", callback_data="send_video")
    btn_refer = InlineKeyboardButton(text="👥 রেফার করুন", callback_data="get_referral")
    
    markup.add(btn_app, btn_video, btn_refer)

    welcome_text = (
        f"🎁 অভিনন্দন আপনাকে - {name} স্বাগতম 💸\n\n"
        "Free Income XV 💸 থেকে ইনকাম শুরু করতে এখনি 'ইনকাম শুরু করুন' বাটনে ক্লিক করুন 👇"
    )
    
    bot.send_message(chat_id, welcome_text, reply_markup=markup)

    # এডমিন হলে ড্যাশবোর্ড কিবোর্ড দেখাবে (এখানে == এর বদলে in ব্যবহার করা হয়েছে)
    if int(uid) in ADMIN_ID:
        admin_markup = ReplyKeyboardMarkup(resize_keyboard=True)
        admin_markup.add(KeyboardButton("Total User"), KeyboardButton("Notice"))
        admin_markup.add(KeyboardButton("🔙 Back"))
        bot.send_message(chat_id, "👨‍💻 Admin Panel Access Granted:", reply_markup=admin_markup)

# ================= 3. Start Command =================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    uid = str(message.from_user.id)
    name = message.from_user.first_name
    
    # রেফার আইডি বের করা
    args = message.text.split()
    ref_id = args[1] if len(args) > 1 else "None"
    
    # চ্যানেল চেক
    if not is_subscribed(uid):
        bot.send_message(
            message.chat.id, 
            "⚠️ আমাদের বটটি ব্যবহার করতে হলে অবশ্যই নিচের চ্যানেলে জয়েন করতে হবে।\n\nচ্যানেলে জয়েন করে '✅ কনফার্ম' বাটনে ক্লিক করুন:", 
            reply_markup=get_join_markup(ref_id)
        )
        return
        
    # জয়েন থাকলে সরাসরি মূল মেনু এবং একাউন্ট সেভ হবে
    process_user_registration_and_menu(message.chat.id, uid, name, ref_id)

# ================= 4. Confirm Button Callback =================
@bot.callback_query_handler(func=lambda call: call.data.startswith("check_join_"))
def verify_join(call):
    uid = str(call.from_user.id)
    name = call.from_user.first_name
    ref_id = call.data.split("_")[2] # check_join_123456 থেকে 123456 বের করা
    
    if is_subscribed(uid):
        bot.delete_message(call.message.chat.id, call.message.message_id)
        process_user_registration_and_menu(call.message.chat.id, uid, name, ref_id)
    else:
        bot.answer_callback_query(call.id, "❌ আপনি এখনো চ্যানেলে জয়েন করেননি! দয়া করে চ্যানেলে জয়েন করে আবার কনফার্ম করুন।", show_alert=True)

# ================= 5. Video Callback =================
@bot.callback_query_handler(func=lambda call: call.data == "send_video")
def handle_video(call):
    bot.send_video(call.message.chat.id, VIDEO_URL, caption="এভাবে সঠিক নিয়মে কাজ করুন।")
    bot.answer_callback_query(call.id)

# ================= 5.5 Referral Callback =================
@bot.callback_query_handler(func=lambda call: call.data == "get_referral")
def handle_referral(call):
    uid = call.from_user.id
    bot_username = bot.get_me().username # ডাইনামিকভাবে বটের ইউজারনেম নেওয়া
    
    ref_link = f"https://t.me/{bot_username}?start={uid}"
    
    msg_text = (
        f"🔗 *আপনার রেফারেল লিংক:*\n\n"
        f"`{ref_link}`\n\n"
        f"☝️ লিংকটি কপি করে আপনার বন্ধুদের সাথে শেয়ার করুন। "
        f"আপনার বন্ধু চ্যানেলগুলোতে জয়েন করে কনফার্ম করলে আপনি পেয়ে যাবেন রেফার বোনাস!"
    )
    
    bot.send_message(call.message.chat.id, msg_text, parse_mode="Markdown")
    bot.answer_callback_query(call.id)

# ================= 5.6 Channel Leave Detection =================
# যখন কোনো ইউজার REQUIRED_CHANNELS এর কোনো চ্যানেল থেকে লিভ নেয় বা কিক হয়,
# তখন তাকে নোটিশ পাঠানো হবে এবং তার ডাটাবেজে channel_left ফ্ল্যাগ সেট হবে।
# NOTE: বট এই চ্যানেলে অবশ্যই অ্যাডমিন থাকতে হবে, এবং নিচে infinity_polling()
# কল করার সময় allowed_updates এ 'chat_member' যুক্ত থাকতে হবে (নিচে করা আছে)।
REQUIRED_CHANNEL_USERNAMES = [ch["username"] for ch in REQUIRED_CHANNELS]
LEFT_STATUSES = ['left', 'kicked']

@bot.chat_member_handler()
def track_channel_membership(update):
    try:
        chat_username = f"@{update.chat.username}" if update.chat.username else None
        if chat_username not in REQUIRED_CHANNEL_USERNAMES:
            return  # শুধু আমাদের রিকোয়ার্ড চ্যানেলের ইভেন্ট নিয়ে কাজ করবে

        old_status = update.old_chat_member.status
        new_status = update.new_chat_member.status
        uid = update.new_chat_member.user.id
        name = update.new_chat_member.user.first_name or "User"

        was_member = old_status not in LEFT_STATUSES
        is_member_now = new_status not in LEFT_STATUSES

        db_url = get_user_db_url(uid)

        if was_member and not is_member_now:
            # ইউজার চ্যানেল থেকে বের হয়ে গেছে / কিক হয়েছে
            try:
                requests.patch(f"{db_url}/users/{uid}.json", json={"channel_left": True})
            except Exception:
                pass

            markup = InlineKeyboardMarkup(row_width=1)
            for ch in REQUIRED_CHANNELS:
                markup.add(InlineKeyboardButton(text=f"📢 {ch['name']}", url=ch['url']))
            markup.add(InlineKeyboardButton(text="✅ আবার জয়েন করেছি, ভেরিফাই করুন", callback_data="check_join_None"))

            try:
                bot.send_message(
                    uid,
                    f"⚠️ {name}, আপনি আমাদের মেইন চ্যানেল থেকে বের হয়ে গেছেন!\n\n"
                    "এই কারণে আপনার টাস্ক/ইনকাম কাউন্টডাউন সাময়িকভাবে বন্ধ হয়ে গেছে। "
                    "পুনরায় ইনকাম চালু করতে হলে নিচের চ্যানেলে আবার জয়েন করুন, তারপর "
                    "'✅ আবার জয়েন করেছি' বাটনে ক্লিক করে ভেরিফাই করুন 👇",
                    reply_markup=markup
                )
            except Exception:
                pass  # যদি ইউজার বটকে ব্লক করে থাকে

        elif not was_member and is_member_now:
            # ইউজার আবার জয়েন করেছে
            try:
                requests.patch(f"{db_url}/users/{uid}.json", json={"channel_left": False})
            except Exception:
                pass
    except Exception:
        pass  # কোনো আনএক্সপেক্টেড আপডেট ফরম্যাটে যেন বট ক্র্যাশ না করে

# ================= 6. Admin Features =================
# এখানে == এর বদলে in ব্যবহার করা হয়েছে
@bot.message_handler(func=lambda message: message.text == "Total User" and message.from_user.id in ADMIN_ID)
def total_users(message):
    total = 0
    bot.send_message(message.chat.id, "⏳ হিসাব করা হচ্ছে...")
    # ২টি ডাটাবেজ থেকে মোট ইউজার কাউন্ট করা
    for db in DB_URLS:
        try:
            res = requests.get(f"{db}/users.json?shallow=true").json()
            if res:
                total += len(res)
        except:
            pass
    bot.send_message(message.chat.id, f"📊 সমস্ত ডাটাবেজ মিলিয়ে মোট ইউজার: {total} জন")

# ব্যাক বাটন - এডমিন কিবোর্ড সরিয়ে মূল মেনুতে ফিরিয়ে দেয়
@bot.message_handler(func=lambda message: message.text == "🔙 Back" and message.from_user.id in ADMIN_ID)
def admin_back(message):
    bot.send_message(
        message.chat.id,
        "🔙 আপনি মূল মেনুতে ফিরে এসেছেন।",
        reply_markup=ReplyKeyboardRemove()
    )

# এখানে == এর বদলে in ব্যবহার করা হয়েছে
@bot.message_handler(func=lambda message: message.text == "Notice" and message.from_user.id in ADMIN_ID)
def ask_notice(message):
    if broadcast_status["is_running"]:
        bot.send_message(message.chat.id, "⚠️ একটি ব্রডকাস্ট অলরেডি চলছে!")
        return
    msg = bot.send_message(message.chat.id, "দয়া করে আপনার নোটিশটি লিখুন। যা লিখে সেন্ড করবেন, সবার কাছে তা চলে যাবে:")
    bot.register_next_step_handler(msg, start_broadcast)

def start_broadcast(message):
    notice_text = message.text
    broadcast_status["is_running"] = True
    broadcast_status["cancel"] = False
    
    # ব্রডকাস্ট থ্রেডে চালু করা হচ্ছে যাতে বট হ্যাং না হয়
    threading.Thread(target=run_broadcast_task, args=(message.chat.id, notice_text)).start()

def run_broadcast_task(admin_chat_id, notice_text):
    all_uids = []
    bot.send_message(admin_chat_id, "⏳ সমস্ত ইউজার আইডি সংগ্রহ করা হচ্ছে...")
    
    for db in DB_URLS:
        try:
            res = requests.get(f"{db}/users.json?shallow=true").json()
            if res:
                all_uids.extend(res.keys())
        except:
            pass
            
    total_target = len(all_uids)
    success = 0
    failed = 0
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🛑 Cancel Broadcast", callback_data="cancel_broadcast"))
    
    status_msg = bot.send_message(
        admin_chat_id, 
        f"🚀 ব্রডকাস্ট শুরু হয়েছে...\n\n🎯 টার্গেট: {total_target} জন\n✅ সফল: {success}\n❌ ব্যর্থ: {failed}",
        reply_markup=markup
    )

    for i, uid in enumerate(all_uids):
        if broadcast_status["cancel"]:
            break
            
        try:
            bot.send_message(uid, notice_text)
            success += 1
        except:
            failed += 1
            
        # প্রতি ১০ জনকে পাঠানোর পর ১ সেকেন্ড স্লিপ (Rate limit safe - Telegram allows 30 msg/sec)
        time.sleep(0.1) 
        
        # প্রতি ৫০ মেসেজ পর পর এডমিন প্যানেলে স্ট্যাটাস আপডেট
        if i % 50 == 0 and i > 0:
            try:
                bot.edit_message_text(
                    chat_id=admin_chat_id, message_id=status_msg.message_id,
                    text=f"🚀 ব্রডকাস্ট চলছে...\n\n🎯 টার্গেট: {total_target} জন\n✅ সফল: {success}\n❌ ব্যর্থ: {failed}",
                    reply_markup=markup
                )
            except:
                pass

    broadcast_status["is_running"] = False
    
    final_text = (
        f"🛑 ব্রডকাস্ট ক্যানসেল করা হয়েছে!\n\n✅ {success} জনের কাছে সেন্ড হয়েছে\n❌ {failed} জন ব্যর্থ" 
        if broadcast_status["cancel"] else 
        f"✅ ব্রডকাস্ট সম্পন্ন!\n\n✅ {success} জনের কাছে সেন্ড হয়েছে\n❌ {failed} জন ব্যর্থ"
    )
    
    bot.edit_message_text(chat_id=admin_chat_id, message_id=status_msg.message_id, text=final_text)

@bot.callback_query_handler(func=lambda call: call.data == "cancel_broadcast")
def cancel_broadcast(call):
    # এখানে == এর বদলে in ব্যবহার করা হয়েছে
    if call.from_user.id in ADMIN_ID:
        broadcast_status["cancel"] = True
        bot.answer_callback_query(call.id, "ব্রডকাস্ট থামানো হচ্ছে...")

# বট চালু রাখা
# allowed_updates এ 'chat_member' যুক্ত না করলে চ্যানেল লিভ/জয়েন ইভেন্ট বট পাবে না
print("Bot is running with Force Join Channel, Leave Detection and 2 Databases...")
bot.infinity_polling(allowed_updates=["message", "callback_query", "chat_member"])
