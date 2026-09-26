import os
import logging
import random
from datetime import datetime
import pytz
from threading import Thread

import psycopg2
from psycopg2 import pool
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters
)
from telegram.error import TelegramError

# --- CONFIGURATION (Environment Variables) ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@your_channel")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", 8080))

# Logging Setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Setup PostgreSQL Connection Pool
db_pool = psycopg2.pool.SimpleConnectionPool(1, 10, dsn=DATABASE_URL)

def get_db_connection():
    return db_pool.getconn()

def release_db_connection(conn):
    db_pool.putconn(conn)

# --- DUMMY WEB SERVER FOR UPTIMEROBOT ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive and running with PostgreSQL!"

def run_flask():
    app.run(host='0.0.0.0', port=PORT)

# --- DATABASE INITIALIZATION ---
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT
        );
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS gifts (
            id SERIAL PRIMARY KEY,
            gift_content TEXT NOT NULL,
            is_claimed INT DEFAULT 0,
            claimed_by BIGINT DEFAULT NULL
        );
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS winners (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            gift_content TEXT,
            won_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    
    conn.commit()
    cursor.close()
    release_db_connection(conn)

init_db()

# --- HELPER FUNCTIONS ---
async def check_membership(bot, user_id):
    try:
        member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
        return member.status in ['creator', 'administrator', 'member']
    except TelegramError:
        return False

def get_admin_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("➕ បន្ថែម Gift", callback_data="admin_addgift_hint"),
            InlineKeyboardButton("📦 ពិនិត្យ Stock", callback_data="admin_stock")
        ],
        [
            InlineKeyboardButton("🎲 ចាប់រង្វាន់ភ្លាមៗ (Draw)", callback_data="admin_draw_now"),
            InlineKeyboardButton("⏰ Set ម៉ោងរត់", callback_data="admin_set_time_hint")
        ],
        [
            InlineKeyboardButton("📢 Broadcast សារ", callback_data="admin_broadcast_hint"),
            InlineKeyboardButton("🗑️ លុបម៉ោង Set", callback_data="admin_cancel_time")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_user_keyboard():
    channel_clean = REQUIRED_CHANNEL.replace('@', '')
    keyboard = [
        [InlineKeyboardButton("📢 Join Telegram Channel", url=f"https://t.me/{channel_clean}")],
        [InlineKeyboardButton("✅ ខ្ញុំបាន Join រួចហើយ (Check Status)", callback_data="verify_join")],
        [InlineKeyboardButton("ℹ️ ព័ត៌មាន Bot", callback_data="user_info")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- USER COMMANDS & CALLBACKS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        '''
        INSERT INTO users (user_id, username, first_name)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id) 
        DO UPDATE SET username = EXCLUDED.username, first_name = EXCLUDED.first_name;
        ''',
        (user.id, user.username, user.first_name)
    )
    conn.commit()
    cursor.close()
    release_db_connection(conn)

    if user.id == ADMIN_ID:
        await update.message.reply_text(
            f"👑 **សួស្តីលោក Admin ({user.first_name})!**\n\nសូមជ្រើសរើស Menu គ្រប់គ្រងខាងក្រោម៖",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )
    else:
        is_joined = await check_membership(context.bot, user.id)
        if is_joined:
            await update.message.reply_text(
                f"ជម្រាបសួរ {user.first_name}! 👋\n\n"
                f"អ្នកបានចុះឈ្មោះក្នុងប្រព័ន្ធ និង Join Channel រួចរាល់ហើយ! 🎉\n"
                f"សូមរង់ចាំការ ចាប់រង្វាន់ស្វ័យប្រវត្តិតាមម៉ោងកំណត់!",
                reply_markup=get_user_keyboard()
            )
        else:
            await update.message.reply_text(
                f"ជម្រាបសួរ {user.first_name}! 👋\n\n"
                f"សូមមេត្តា Join Channel {REQUIRED_CHANNEL} ជាមុនសិន ទើបមានសិទ្ធិទទួលបានកាដូ! 🎁",
                reply_markup=get_user_keyboard()
            )

async def user_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user

    if data == "verify_join":
        is_joined = await check_membership(context.bot, user.id)
        if is_joined:
            await query.edit_message_text(
                "✅ **អបអរសាទរ!** អ្នកបានផ្ទៀងផ្ទាត់ជោគជ័យ។ ឈ្មោះរបស់អ្នកស្ថិតក្នុងបញ្ជីចាប់រង្វាន់ហើយ! 🎉",
                reply_markup=get_user_keyboard()
            )
        else:
            await query.answer("❌ អ្នកមិនទាន់បាន Join Channel នៅឡើយទេ! សូមចុច Join រួចសាកល្បងម្ដងទៀត។", show_alert=True)

    elif data == "user_info":
        await query.edit_message_text(
            "ℹ️ **អំពី Bot កាដូស្វ័យប្រវត្តិ**\n\n"
            "• ប្រព័ន្ធនឹងធ្វើការ Random ជ្រើសរើសអ្នកឈ្នះដោយស្វ័យប្រវត្តិ។\n"
            "• កាដូនឹងត្រូវផ្ញើចូល Private Chat របស់អ្នកឈ្នះភ្លាមៗ។\n"
            "• លក្ខខណ្ឌតែមួយគត់៖ ត្រូវតែជាសមាជិកនៅក្នុង Channel!",
            reply_markup=get_user_keyboard()
        )

# --- ADMIN COMMANDS & CALLBACKS ---
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ អ្នកមិនមានសិទ្ធិប្រើប្រាស់ Menu នេះទេ!", show_alert=True)
        return

    if data == "admin_stock":
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM gifts WHERE is_claimed = 0;")
        count = cursor.fetchone()[0]
        cursor.close()
        release_db_connection(conn)
        
        await query.edit_message_text(
            f"📦 **របាយការណ៍ស្តុក:**\n\nចំនួន Gift ដែលនៅសល់ក្នុង Stock: `{count}` 🎁",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )

    elif data == "admin_draw_now":
        await query.edit_message_text("⏳ កំពុងដំណើរការ Random ចាប់រង្វាន់...")
        await trigger_draw(context)
        await query.message.reply_text("✅ ការចាប់រង្វាន់ និងផ្ញើកាដូបានបញ្ចប់!", reply_markup=get_admin_keyboard())

    elif data == "admin_addgift_hint":
        await query.edit_message_text(
            "➕ **របៀបបន្ថែម Gift:**\n\n"
            "សូមវាយ Command តាមទម្រង់៖\n"
            "`/addgift example@gmail.com:pass123`",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )

    elif data == "admin_set_time_hint":
        await query.edit_message_text(
            "⏰ **របៀប Set ម៉ោងចាប់រង្វាន់ (One-time):**\n\n"
            "សូមវាយ Command តាមទម្រង់៖\n"
            "`/set YYYY-MM-DD HH:MM`\n\n"
            "ឧទាហរណ៍៖ `/set 2026-09-27 20:30` (ចាប់រង្វាន់ថ្ងៃទី 27 ខែកញ្ញា ម៉ោង 8:30 យប់)",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )

    elif data == "admin_broadcast_hint":
        await query.edit_message_text(
            "📢 **របៀប Broadcast សារ:**\n\n"
            "សូមវាយ Command តាមទម្រង់៖\n"
            "`/broadcast សួស្តីអ្នកទាំងអស់គ្នា!`",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )

    elif data == "admin_cancel_time":
        current_jobs = context.job_queue.get_jobs_by_name("scheduled_draw")
        if not current_jobs:
            await query.edit_message_text("⚠️ មិនមានការកំណត់ Time ចាប់រង្វាន់ដែលកំពុងរង់ចាំនោះទេ។", reply_markup=get_admin_keyboard())
            return

        for job in current_jobs:
            job.schedule_removal()
        await query.edit_message_text("🗑️ បានលុបការកំណត់ Time ចាប់រង្វាន់ស្វ័យប្រវត្តិចោលរួចរាល់!", reply_markup=get_admin_keyboard())

# --- ADMIN COMMAND FUNCTIONS ---
async def add_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("❌ សូមបញ្ចូល Gift Content! ឧទាហរណ៍:\n`/addgift example@gmail.com:pass123`", parse_mode="Markdown")
        return

    gift_content = " ".join(context.args)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO gifts (gift_content) VALUES (%s);", (gift_content,))
    conn.commit()
    cursor.close()
    release_db_connection(conn)

    await update.message.reply_text("✅ បានបន្ថែម Gift ចូលក្នុង System រួចរាល់!", reply_markup=get_admin_keyboard())

async def set_draw_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "❌ **ទម្រង់មិនត្រឹមត្រូវ!**\n\n"
            "សូមប្រើប្រាស់ទម្រង់៖ `/set YYYY-MM-DD HH:MM`\n"
            "ឧទាហរណ៍៖ `/set 2026-09-27 20:30`",
            parse_mode="Markdown"
        )
        return

    date_str, time_str = context.args[0], context.args[1]
    
    try:
        cambodia_tz = pytz.timezone('Asia/Phnom_Penh')
        scheduled_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        scheduled_dt = cambodia_tz.localize(scheduled_dt)
        
        now = datetime.now(cambodia_tz)
        if scheduled_dt <= now:
            await update.message.reply_text("❌ ម៉ោងដែលបានកំណត់គឺនៅក្នុងអតីតកាល! សូមជ្រើសរើសម៉ោងនៅពេលអនាគត។")
            return

        current_jobs = context.job_queue.get_jobs_by_name("scheduled_draw")
        for job in current_jobs:
            job.schedule_removal()

        context.job_queue.run_once(trigger_draw, when=scheduled_dt, name="scheduled_draw")

        formatted_time = scheduled_dt.strftime("%d-%m-%Y ម៉ោង %H:%M")
        await update.message.reply_text(
            f"✅ **កំណត់ម៉ោងចាប់រង្វាន់ជោគជ័យ!**\n\n"
            f"📅 ថ្ងៃ និងម៉ោងត្រូវរត់៖ `{formatted_time}` ( Asia/Phnom_Penh )\n"
            f"💡 Bot នឹងចាប់រង្វាន់ស្វ័យប្រវត្តិតែមួយលើកនេះប៉ុណ្ណោះ។",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )
    except ValueError:
        await update.message.reply_text("❌ ទម្រង់កាលបរិច្ឆេទ ឬម៉ោងមិនត្រឹមត្រូវ (YYYY-MM-DD HH:MM)!")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    msg_text = " ".join(context.args)
    if not msg_text:
        await update.message.reply_text("❌ សូមបញ្ចូលសារដែលចង់ Broadcast! ឧទាហរណ៍:\n`/broadcast សួស្តីអ្នកទាំងអស់គ្នា`")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users;")
    users = cursor.fetchall()
    cursor.close()
    release_db_connection(conn)

    success, failed = 0, 0
    for u in users:
        try:
            await context.bot.send_message(chat_id=u[0], text=f"📢 **ការជូនដំណឹង:**\n\n{msg_text}", parse_mode="Markdown")
            success += 1
        except Exception:
            failed += 1

    await update.message.reply_text(f"✅ Broadcast រួចរាល់:\n- ជោគជ័យ: {success}\n- បរាជ័យ: {failed}", reply_markup=get_admin_keyboard())

# --- AUTO DRAW ENGINE ---
async def trigger_draw(context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, gift_content FROM gifts WHERE is_claimed = 0;")
    available_gifts = cursor.fetchall()

    if not available_gifts:
        cursor.close()
        release_db_connection(conn)
        return

    cursor.execute("SELECT user_id, username, first_name FROM users;")
    all_users = cursor.fetchall()
    
    if not all_users:
        cursor.close()
        release_db_connection(conn)
        return

    winners_list = []

    for gift in available_gifts:
        gift_id, gift_content = gift
        random.shuffle(all_users)
        
        selected_user = None
        for u in all_users:
            u_id, u_name, u_fname = u
            if await check_membership(context.bot, u_id):
                selected_user = u
                break
        
        if selected_user:
            u_id, u_name, u_fname = selected_user
            try:
                await context.bot.send_message(
                    chat_id=u_id,
                    text=f"🎉 **អបអរសាទរ! អ្នកទទួលបានកាដូពិសេស:**\n\n🎁 `{gift_content}`\n\nសូមអរគុណសម្រាប់ការចូលរួម!",
                    parse_mode="Markdown"
                )
                
                cursor.execute("UPDATE gifts SET is_claimed = 1, claimed_by = %s WHERE id = %s;", (u_id, gift_id))
                cursor.execute("INSERT INTO winners (user_id, gift_content) VALUES (%s, %s);", (u_id, gift_content))
                
                user_display = f"@{u_name}" if u_name else u_fname
                winners_list.append(user_display)
                all_users.remove(selected_user)
            except Exception as e:
                logging.error(f"Failed to send gift to {u_id}: {e}")

    conn.commit()
    cursor.close()
    release_db_connection(conn)

    if winners_list:
        announcement_text = "🎉 **ប្រកាសលទ្ធផលអ្នកឈ្នះរង្វាន់ Auto Gift!** 🎁\n\n"
        for idx, w in enumerate(winners_list, 1):
            announcement_text += f"{idx}. {w}\n"
        announcement_text += "\nសូមពិនិត្យមើល Telegram Chat ជាមួយ Bot ដើម្បីទទួលយកកាដូ! ❤️"
        
        await context.bot.send_message(chat_id=REQUIRED_CHANNEL, text=announcement_text, parse_mode="Markdown")

# --- MAIN FUNCTION ---
def main():
    server_thread = Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()

    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("addgift", add_gift))
    app_bot.add_handler(CommandHandler("broadcast", broadcast))
    app_bot.add_handler(CommandHandler("set", set_draw_time))

    # Callback Query Handlers
    app_bot.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
    app_bot.add_handler(CallbackQueryHandler(user_callback_handler))

    print("Bot is running with Inline Dashboard Buttons...")
    app_bot.run_polling()

if __name__ == "__main__":
    main()
