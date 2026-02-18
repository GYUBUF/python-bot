import logging
import asyncio
import random
from datetime import datetime, timedelta
from collections import defaultdict

import aiohttp
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

# ==================== НАСТРОЙКИ ====================
TOKEN = "8398666469:AAFJuFpeUieZOnLVxStaviHr1X--O3yAAu8"
MISTRAL_KEY = "HCxrOgMwskodETQDGvITs4f65Qzwemiz"
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"

BASE_LIMIT = 10000  # 10 000 токенов в день!
TOKENS_PER_MSG = 50  # 1 сообщение = 50 токенов (200 сообщений в день!)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== ДАННЫЕ ====================
class UserData:
    def __init__(self):
        self.over_total = 0
        self.over_streak = 0
        self.limit = BASE_LIMIT
        self.tokens = 0
        self.achs = []
        self.last_date = None

users = defaultdict(UserData)

# ==================== ДОСТИЖЕНИЯ ====================
ACHIEVEMENTS = {
    'over_5': ('⚡ Новичок', 5, 500),
    'over_20': ('⚡⚡ Любитель', 20, 1000),
    'over_50': ('⚡⚡⚡ Профи', 50, 2000),
    'over_100': ('💥 Мастер', 100, 4000),
    'streak_3': ('🔥 3 дня', 3, 1000),
    'streak_7': ('🔥🔥 7 дней', 7, 3000),
    'streak_30': ('👑 Легенда', 30, 10000),
}

# ==================== MISTRAL AI ====================
async def ask_mistral(msg):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(MISTRAL_URL,
                headers={'Authorization': f'Bearer {MISTRAL_KEY}'},
                json={
                    'model': 'mistral-medium',
                    'messages': [{'role': 'user', 'content': f"Отвечай коротко по-русски: {msg}"}],
                    'temperature': 0.8,
                    'max_tokens': 50
                }) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['choices'][0]['message']['content']
    except Exception as e:
        logger.error(f"AI Error: {e}")
    return random.choice(["Ага", "Понял", "Ок", "Интересно", "Ясно", "Бывает"])

# ==================== КОМАНДЫ ====================
async def start(update, context):
    uid = update.effective_user.id
    user = users[uid]
    remaining = user.limit - user.tokens
    await update.message.reply_text(
        f"👋 Привет!\n"
        f"💰 Лимит: {user.limit} токенов\n"
        f"⚡ Осталось: {remaining}\n"
        f"🔥 Превышений: {user.over_total}\n"
        f"🏆 /ach - достижения"
    )

async def achievements(update, context):
    uid = update.effective_user.id
    user = users[uid]
    text = "🏆 Достижения:\n"
    for a in user.achs:
        text += f"✅ {a}\n"
    if not user.achs:
        text += "Пока нет\n"
    text += f"\n💰 Лимит: {user.limit}"
    await update.message.reply_text(text)

# ==================== ОБРАБОТЧИК ====================
async def handle_message(update, context):
    if update.effective_user.is_bot:
        return
    
    uid = update.effective_user.id
    msg = update.message.text
    is_group = update.effective_chat.type != 'private'
    
    user = users[uid]
    
    # Проверка дня
    today = datetime.now().date()
    if user.last_date != today:
        user.tokens = 0
        if user.last_date and user.last_date == today - timedelta(days=1):
            user.over_streak += 1
        else:
            user.over_streak = 1
        user.last_date = today
    
    # Лимиты в личке
    if not is_group and user.tokens >= user.limit:
        user.over_total += 1
    
    # Ответ
    await update.message.reply_chat_action("typing")
    response = await ask_mistral(msg)
    await update.message.reply_text(response)
    
    # Тратим токены
    if not is_group and user.tokens < user.limit:
        user.tokens += TOKENS_PER_MSG
        if user.tokens >= user.limit:
            await update.message.reply_text("⚠️ Лимит на сегодня исчерпан! Дальше будут копиться превышения 🔥")
    
    # Проверка достижений
    new = []
    for key, (name, req, bonus) in ACHIEVEMENTS.items():
        if key in user.achs:
            continue
        if key.startswith('over_') and user.over_total >= req:
            user.limit += bonus
            user.achs.append(key)
            new.append(f"{name} +{bonus}")
        elif key.startswith('streak_') and user.over_streak >= req:
            user.limit += bonus
            user.achs.append(key)
            new.append(f"{name} +{bonus}")
    
    if new:
        await update.message.reply_text("🔥 " + ", ".join(new))

# ==================== ЗАПУСК ====================
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ach", achievements))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("=" * 40)
    print("🤖 Закатун запущен!")
    print(f"💰 Лимит: {BASE_LIMIT} токенов/день")
    print(f"💬 ~{BASE_LIMIT//TOKENS_PER_MSG} сообщений в день")
    print("🏆 Достижения: 7 штук")
    print("=" * 40)
    
    app.run_polling()

if __name__ == "__main__":
    main()
