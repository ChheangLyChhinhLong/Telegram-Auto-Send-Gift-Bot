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
)
from telegram.error import TelegramError

# --- CONFIGURATION (Environment Variables) ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@your_channel")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", 8080))

# Setup Logging
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

# --- USER COMMANDS ---
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

    is_joined = await check_membership(context.bot, user.id)
    
    if is_joined:
        await update.message.reply_text(
            f"ជម្រាបសួរ {user.first_name}! 👋\n\n"
            f"អ្នកបានចុះឈ្មោះក្នុងប្រព័ន្ធរួចរាល់ហើយ។ Bot នឹងធ្វើការ Random ផ្ញើកាដូជូននៅពេលដល់ម៉ោងកំណត់! ❤️"
        )
    else:
        channel_clean = REQUIRED_CHANNEL.replace('@', '')
        keyboard = [
            [InlineKeyboardButton("📢 Join Telegram Channel", url=f"https://t.me/{channel_clean}")],
            [InlineKeyboardButton("✅ ខ្ញុំបាន Join រួចហើយ (Check)", callback_data="verify_join")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"សូមមេត្តា Join Channel {REQUIRED_CHANNEL} ជាមុនសិន ទើបមានសិទ្ធិទទួលបានកាដូ! 🎁",
            reply_markup=reply_markup
        )

async def verify_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    is_joined = await check_membership(context.bot, query.from_user.id)
    if is_joined:
        await query.edit_message_text("អបអរសាទរ! អ្នកបានផ្ទៀងផ្ទាត់ជោគជ័យ។ សូមរង់ចាំការចាប់រង្វាន់! 🎉")
    else:
        await query.answer("អ្នកមិនទាន់បាន Join Channel នៅឡើយទេ! សូមពិនិត្យមើលឡើងវិញ។", show_alert=True)

# --- ADMIN COMMANDS ---
async def add_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("សូមបញ្ចូល Gift Content! ឧទាហរណ៍:\n`/addgift example@gmail.com:pass123`", parse_mode="Markdown")
        return

    gift_content = " ".join(context.args)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO gifts (gift_content) VALUES (%s);", (gift_content,))
    conn.commit()
    cursor.close()
    release_db_connection(conn)

    await update.message.reply_text("✅ បានបន្ថែម Gift ចូលក្នុង System រួចរាល់!")

async def count_gifts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM gifts WHERE is_claimed = 0;")
    count = cursor.fetchone()[0]
    cursor.close()
    release_db_connection(conn)

    await update.message.reply_text(f"📦 ចំនួន Gift ដែលនៅសល់ក្នុង Stock: {count}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    msg_text = " ".join(context.args)
    if not msg_text:
        await update.message.reply_text("សូមបញ្ចូលសារដែលចង់ Broadcast! ឧទាហរណ៍:\n`/broadcast សួស្តីអ្នកទាំងអស់គ្នា`")
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

    await update.message.reply_text(f"✅ Broadcast រួចរាល់:\n- ជោគជ័យ: {success}\n- បរាជ័យ: {failed}")

# --- AUTO DRAW SYSTEM ---
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

async def manual_draw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text("⏳ កំពុងដំណើរការ Random ចាប់រង្វាន់...")
    await trigger_draw(context)
    await update.message.reply_text("✅ ការចាប់រង្វាន់ និងផ្ញើកាដូបានបញ្ចប់!")

# --- MAIN ENGINE ---
def main():
    server_thread = Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()

    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("addgift", add_gift))
    app_bot.add_handler(CommandHandler("stock", count_gifts))
    app_bot.add_handler(CommandHandler("broadcast", broadcast))
    app_bot.add_handler(CommandHandler("draw", manual_draw_command))
    app_bot.add_handler(CallbackQueryHandler(verify_join_callback, pattern="^verify_join$"))

    # Schedule Auto Draw (ម៉ោង 20:00 Phnom Penh Time)
    job_queue = app_bot.job_queue
    cambodia_tz = pytz.timezone('Asia/Phnom_Penh')
    target_time = datetime.now(cambodia_tz).replace(hour=20, minute=0, second=0).time()
    job_queue.run_daily(trigger_draw, time=target_time)

    print("Bot and Web server are running with PostgreSQL...")
    app_bot.run_polling()

if __name__ == "__main__":
    main()
