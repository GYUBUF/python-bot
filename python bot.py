import logging
import asyncio
import random
from datetime import datetime, timedelta
from typing import Dict
from collections import defaultdict

import aiohttp
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

# Конфигурация
TOKEN = "8398666469:AAFJuFpeUieZOnLVxStaviHr1X--O3yAAu8"
ADMIN_ID = 8386169734
BOT_NAME = "Закатун"
BOT_VERSION = "5.3"
MISTRAL_API_KEY = "HCxrOgMwskodETQDGvITs4f65Qzwemiz"
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

BASE_TOKEN_LIMIT = 1000
TOKENS_PER_MSG = 50

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== ДОСТИЖЕНИЯ ====================

ACHIEVEMENTS = {
    'over_5': {'name': '⚡ Новичок', 'req': 5, 'bonus': 200},
    'over_20': {'name': '⚡⚡ Любитель', 'req': 20, 'bonus': 500},
    'over_50': {'name': '⚡⚡⚡ Профи', 'req': 50, 'bonus': 1000},
    'over_100': {'name': '💥 Мастер', 'req': 100, 'bonus': 2000},
    'over_300': {'name': '🔥 Легенда', 'req': 300, 'bonus': 5000},
    'streak_3': {'name': '🔥 3 дня', 'req': 3, 'bonus': 800},
    'streak_7': {'name': '🔥🔥 7 дней', 'req': 7, 'bonus': 2000},
    'streak_30': {'name': '👑 Месяц', 'req': 30, 'bonus': 5000},
}

class UserData:
    def __init__(self):
        self.messages = 0
        self.tokens_used = 0
        self.limit = BASE_TOKEN_LIMIT
        self.over_today = 0
        self.over_total = 0
        self.over_streak = 0
        self.streak_day = None
        self.achievements = []
        self.last_date = None

class DB:
    def __init__(self):
        self.users = defaultdict(UserData)
    
    def get(self, uid): return self.users[uid]
    
    def add_msg(self, uid):
        user = self.users[uid]
        user.messages += 1
        
        today = datetime.now().date()
        if user.last_date != today:
            user.over_today = 0
            user.tokens_used = 0
            user.last_date = today
            
            if user.streak_day and user.streak_day == today - timedelta(days=1):
                user.over_streak += 1
            else:
                user.over_streak = 1
            user.streak_day = today

db = DB()

class MistralAI:
    def __init__(self, key): self.key = key
    
    async def ask(self, msg):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(MISTRAL_API_URL,
                    headers={'Authorization': f'Bearer {self.key}'},
                    json={'model': 'mistral-medium', 'messages': [{'role': 'user', 'content': f"Ты {BOT_NAME}. Ответь: {msg}"}]}) as r:
                    return (await r.json())['choices'][0]['message']['content'] if r.status == 200 else None
        except: return None

ai = MistralAI(MISTRAL_API_KEY)

async def start(update, context):
    user = db.get(update.effective_user.id)
    await update.message.reply_text(
        f"👋 Я {BOT_NAME} v{BOT_VERSION}\n"
        f"💰 Лимит: {user.limit}\n"
        f"⚡ Осталось: {user.limit - user.tokens_used}\n"
        f"🔥 Превышений: {user.over_total}\n"
        f"/ach - достижения"
    )

async def achievements(update, context):
    user = db.get(update.effective_user.id)
    text = "🏆 Достижения:\n"
    for a in user.achievements:
        text += f"✅ {a}\n"
    text += f"\n💰 Лимит: {user.limit}"
    await update.message.reply_text(text)

async def handle_msg(update, context):
    if update.effective_user.is_bot: return
    
    uid = update.effective_user.id
    msg = update.message.text
    is_group = update.effective_chat.type != 'private'
    
    db.add_msg(uid)
    user = db.get(uid)
    
    if not is_group:
        can_respond = user.tokens_used < user.limit
        
        if not can_respond:
            user.over_today += 1
            user.over_total += 1
            
            # Проверка достижений
            new = []
            for ach, data in ACHIEVEMENTS.items():
                if ach in user.achievements: continue
                if ach.startswith('over_') and user.over_total >= int(ach.split('_')[1]):
                    user.limit += data['bonus']
                    user.achievements.append(ach)
                    new.append(f"{data['name']} +{data['bonus']}")
                elif ach.startswith('streak_') and user.over_streak >= int(ach.split('_')[1]):
                    user.limit += data['bonus']
                    user.achievements.append(ach)
                    new.append(f"{data['name']} +{data['bonus']}")
            
            if new:
                await update.message.reply_text("🔥 Новое: " + ', '.join(new))
    
    await update.message.reply_chat_action("typing")
    resp = await ai.ask(msg)
    
    if resp:
        await update.message.reply_text(resp)
        if not is_group and can_respond:
            user.tokens_used += TOKENS_PER_MSG
    else:
        await update.message.reply_text(random.choice(["Ага", "Понял", "Ок", "Интересно", "Ясно"]))

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ach", achievements))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    print(f"✅ {BOT_NAME} v{BOT_VERSION}")
    app.run_polling()

if __name__ == "__main__":
    main()
