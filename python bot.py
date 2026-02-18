import logging
import asyncio
import random
from datetime import datetime, timedelta
from typing import Dict, Optional
from collections import defaultdict

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

# Конфигурация
TOKEN = "8398666469:AAFJuFpeUieZOnLVxStaviHr1X--O3yAAu8"
ADMIN_ID = 8386169734
BOT_NAME = "Закатун"
BOT_VERSION = "5.0"
MISTRAL_API_KEY = "HCxrOgMwskodETQDGvITs4f65Qzwemiz"
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

# Базовый лимит токенов
BASE_TOKEN_LIMIT = 1000
TOKENS_PER_MESSAGE = 50

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== СИСТЕМА ДОСТИЖЕНИЙ ====================

ACHIEVEMENTS = {
    # Базовые достижения (по сообщениям)
    'novice': {'name': '🌱 Новичок', 'desc': 'Отправил 10 сообщений', 'req': 10, 'bonus': 100},
    'talker': {'name': '💬 Болтун', 'desc': 'Отправил 50 сообщений', 'req': 50, 'bonus': 250},
    'chatty': {'name': '🗣 Говорун', 'desc': 'Отправил 100 сообщений', 'req': 100, 'bonus': 500},
    'master': {'name': '🎯 Мастер чата', 'desc': 'Отправил 500 сообщений', 'req': 500, 'bonus': 1000},
    'legend': {'name': '👑 Легенда', 'desc': 'Отправил 1000 сообщений', 'req': 1000, 'bonus': 2000},
    
    # Дневные достижения
    'regular': {'name': '📅 Постоянный', 'desc': '5 дней подряд', 'req': 5, 'bonus': 300},
    'veteran': {'name': '⭐ Ветеран', 'desc': '30 дней подряд', 'req': 30, 'bonus': 1500},
    
    # Специальные временные
    'early': {'name': '🌅 Ранний', 'desc': 'Писал до 6 утра 3 раза', 'req': 3, 'bonus': 200},
    'night': {'name': '🌙 Ночной', 'desc': 'Писал после полуночи 3 раза', 'req': 3, 'bonus': 200},
    'weekend': {'name': '🎉 Выходной', 'desc': 'Писал в выходные 2 раза', 'req': 2, 'bonus': 150},
    
    # ===== ДОСТИЖЕНИЯ ПРЕВЫШЕНИЯ ЛИМИТА =====
    # Получаются только когда токены кончились, а ты продолжаешь общаться
    'over_limit_1': {
        'name': '⚡ Превышение 1 ур.', 
        'desc': 'Отправил 5 сообщений после превышения лимита', 
        'req': 5, 
        'bonus': 300,
        'type': 'over_limit'
    },
    'over_limit_2': {
        'name': '⚡⚡ Превышение 2 ур.', 
        'desc': 'Отправил 20 сообщений после превышения лимита', 
        'req': 20, 
        'bonus': 800,
        'type': 'over_limit'
    },
    'over_limit_3': {
        'name': '⚡⚡⚡ Превышение 3 ур.', 
        'desc': 'Отправил 50 сообщений после превышения лимита', 
        'req': 50, 
        'bonus': 2000,
        'type': 'over_limit'
    },
    'over_limit_4': {
        'name': '💥 Абсолютное превышение', 
        'desc': 'Отправил 100 сообщений после превышения лимита', 
        'req': 100, 
        'bonus': 5000,
        'type': 'over_limit'
    },
    
    # Превышение несколько дней подряд
    'over_streak_3': {
        'name': '🔥 3 дня превышения', 
        'desc': 'Превышал лимит 3 дня подряд', 
        'req': 3, 
        'bonus': 1000,
        'type': 'over_streak'
    },
    'over_streak_7': {
        'name': '🔥🔥 7 дней превышения', 
        'desc': 'Превышал лимит 7 дней подряд', 
        'req': 7, 
        'bonus': 3000,
        'type': 'over_streak'
    },
    'over_streak_30': {
        'name': '🔥🔥🔥 Месяц без тормозов', 
        'desc': 'Превышал лимит 30 дней подряд', 
        'req': 30, 
        'bonus': 10000,
        'type': 'over_streak'
    },
    
    # Абсолютные рекорды
    'over_total_100': {
        'name': '💪 100+ превышений', 
        'desc': 'Всего превысил лимит 100 раз', 
        'req': 100, 
        'bonus': 2000,
        'type': 'over_total'
    },
    'over_total_500': {
        'name': '💪💪 500+ превышений', 
        'desc': 'Всего превысил лимит 500 раз', 
        'req': 500, 
        'bonus': 5000,
        'type': 'over_total'
    },
    'over_total_1000': {
        'name': '👾 Легенда превышения', 
        'desc': 'Всего превысил лимит 1000 раз', 
        'req': 1000, 
        'bonus': 15000,
        'type': 'over_total'
    },
    
    # Экстремальные
    'over_limit_day': {
        'name': '📈 100+ за день', 
        'desc': 'Превысил лимит на 100+ сообщений за один день', 
        'req': 100, 
        'bonus': 3000,
        'type': 'over_day'
    },
    'over_limit_day_300': {
        'name': '📈📈 300+ за день', 
        'desc': 'Превысил лимит на 300+ сообщений за один день', 
        'req': 300, 
        'bonus': 8000,
        'type': 'over_day'
    },
}

class AchievementSystem:
    def __init__(self):
        self.user_stats = defaultdict(lambda: {
            'messages': 0,
            'tokens_used': 0,
            'last_seen': None,
            'streak': 0,
            'streak_last': None,
            'achievements': [],
            'token_limit': BASE_TOKEN_LIMIT,
            'night_count': 0,
            'early_count': 0,
            'weekend_count': 0,
            'reg_date': datetime.now(),
            
            # Статистика превышений
            'over_limit_count': 0,           # Сколько раз превышал лимит
            'over_limit_total': 0,            # Всего сообщений после превышения
            'over_limit_streak': 0,           # Дней подряд с превышением
            'over_limit_streak_last': None,    # Последний день превышения
            'over_limit_today': 0,             # Сколько превысил сегодня
            'over_limit_max_day': 0,           # Максимум за день
            'over_limit_days': 0,               # Сколько дней было превышение
        })
    
    def add_message(self, user_id):
        stats = self.user_stats[user_id]
        stats['messages'] += 1
        
        # Проверка времени
        now = datetime.now()
        stats['last_seen'] = now
        
        # Стрик (дни подряд)
        if stats['streak_last']:
            diff = (now.date() - stats['streak_last'].date()).days
            if diff == 1:
                stats['streak'] += 1
            elif diff > 1:
                stats['streak'] = 1
        else:
            stats['streak'] = 1
        stats['streak_last'] = now
        
        # Специальные счётчики
        hour = now.hour
        if hour < 6:
            stats['early_count'] += 1
        if hour >= 23 or hour < 4:
            stats['night_count'] += 1
        if now.weekday() >= 5:
            stats['weekend_count'] += 1
    
    def add_over_limit_message(self, user_id):
        """Сообщение после превышения лимита"""
        stats = self.user_stats[user_id]
        stats['over_limit_total'] += 1
        stats['over_limit_today'] += 1
        stats['over_limit_count'] += 1
        
        # Проверяем рекорд за день
        if stats['over_limit_today'] > stats['over_limit_max_day']:
            stats['over_limit_max_day'] = stats['over_limit_today']
        
        # Проверяем стрик превышений
        today = datetime.now().date()
        if stats['over_limit_streak_last']:
            if stats['over_limit_streak_last'] == today - timedelta(days=1):
                stats['over_limit_streak'] += 1
            elif stats['over_limit_streak_last'] != today:
                stats['over_limit_streak'] = 1
        else:
            stats['over_limit_streak'] = 1
            stats['over_limit_days'] += 1
        
        stats['over_limit_streak_last'] = today
    
    def reset_daily_over_limit(self, user_id):
        """Сброс дневного счётчика превышений"""
        stats = self.user_stats[user_id]
        stats['over_limit_today'] = 0
    
    def check_achievements(self, user_id):
        stats = self.user_stats[user_id]
        new_achievements = []
        
        for ach_id, ach in ACHIEVEMENTS.items():
            if ach_id in stats['achievements']:
                continue
            
            unlocked = False
            
            # Базовые
            if ach_id == 'novice' and stats['messages'] >= 10:
                unlocked = True
            elif ach_id == 'talker' and stats['messages'] >= 50:
                unlocked = True
            elif ach_id == 'chatty' and stats['messages'] >= 100:
                unlocked = True
            elif ach_id == 'master' and stats['messages'] >= 500:
                unlocked = True
            elif ach_id == 'legend' and stats['messages'] >= 1000:
                unlocked = True
            
            # Дневные
            elif ach_id == 'regular' and stats['streak'] >= 5:
                unlocked = True
            elif ach_id == 'veteran' and stats['streak'] >= 30:
                unlocked = True
            
            # Специальные
            elif ach_id == 'early' and stats['early_count'] >= 3:
                unlocked = True
            elif ach_id == 'night' and stats['night_count'] >= 3:
                unlocked = True
            elif ach_id == 'weekend' and stats['weekend_count'] >= 2:
                unlocked = True
            
            # ===== ПРЕВЫШЕНИЯ =====
            elif ach_id == 'over_limit_1' and stats['over_limit_total'] >= 5:
                unlocked = True
            elif ach_id == 'over_limit_2' and stats['over_limit_total'] >= 20:
                unlocked = True
            elif ach_id == 'over_limit_3' and stats['over_limit_total'] >= 50:
                unlocked = True
            elif ach_id == 'over_limit_4' and stats['over_limit_total'] >= 100:
                unlocked = True
            
            # Стрик превышений
            elif ach_id == 'over_streak_3' and stats['over_limit_streak'] >= 3:
                unlocked = True
            elif ach_id == 'over_streak_7' and stats['over_limit_streak'] >= 7:
                unlocked = True
            elif ach_id == 'over_streak_30' and stats['over_limit_streak'] >= 30:
                unlocked = True
            
            # Общее количество
            elif ach_id == 'over_total_100' and stats['over_limit_count'] >= 100:
                unlocked = True
            elif ach_id == 'over_total_500' and stats['over_limit_count'] >= 500:
                unlocked = True
            elif ach_id == 'over_total_1000' and stats['over_limit_count'] >= 1000:
                unlocked = True
            
            # За день
            elif ach_id == 'over_limit_day' and stats['over_limit_max_day'] >= 100:
                unlocked = True
            elif ach_id == 'over_limit_day_300' and stats['over_limit_max_day'] >= 300:
                unlocked = True
            
            if unlocked:
                stats['achievements'].append(ach_id)
                stats['token_limit'] += ach['bonus']
                new_achievements.append(ach)
        
        return new_achievements
    
    def get_token_limit(self, user_id):
        return self.user_stats[user_id]['token_limit']
    
    def add_token_usage(self, user_id, tokens):
        self.user_stats[user_id]['tokens_used'] += tokens
    
    def get_remaining_tokens(self, user_id):
        limit = self.get_token_limit(user_id)
        used = self.user_stats[user_id]['tokens_used']
        return max(0, limit - used)
    
    def can_use_tokens(self, user_id):
        return self.get_remaining_tokens(user_id) > 0
    
    def get_over_limit_stats(self, user_id):
        stats = self.user_stats[user_id]
        return {
            'total': stats['over_limit_total'],
            'today': stats['over_limit_today'],
            'streak': stats['over_limit_streak'],
            'max_day': stats['over_limit_max_day'],
            'count': stats['over_limit_count']
        }

achievements = AchievementSystem()

# ==================== MISTRAL AI ====================

class MistralAI:
    def __init__(self, key):
        self.key = key
    
    async def ask(self, msg, user, is_group=False):
        style = "Кратко, 1-2 предложения." if is_group else "Как в обычном разговоре."
        prompt = f"Ты {BOT_NAME}, видеоблогер. {style}\n{user}: {msg}"
        
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(MISTRAL_API_URL, 
                    headers={'Authorization': f'Bearer {self.key}'},
                    json={'model': 'mistral-medium', 'messages': [{'role': 'user', 'content': prompt}], 'temperature': 0.8}) as r:
                    if r.status == 200:
                        data = await r.json()
                        return data['choices'][0]['message']['content']
        except Exception as e:
            logger.error(f"AI Error: {e}")
        return None

ai = MistralAI(MISTRAL_API_KEY)

# ==================== КОМАНДЫ ====================

async def start(update, context):
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type == 'private':
        limit = achievements.get_token_limit(user.id)
        remaining = achievements.get_remaining_tokens(user.id)
        over = achievements.get_over_limit_stats(user.id)
        
        await update.message.reply_text(
            f"👋 Привет! Я {BOT_NAME} v{BOT_VERSION}\n\n"
            f"💰 Твой лимит: {limit} токенов/день\n"
            f"⚡ Осталось: {remaining}\n"
            f"⚡ Превышений сегодня: {over['today']}\n\n"
            f"🏆 /achievements - достижения\n"
            f"📊 /stats - статистика\n"
            f"🔥 /overstats - статистика превышений\n"
            f"📝 /note - заметки\n"
            f"⏰ /remind - напоминания"
        )
    else:
        await update.message.reply_text(f"👋 Всем привет! Я {BOT_NAME}")

async def achievements_command(update, context):
    user = update.effective_user
    stats = achievements.user_stats[user.id]
    
    text = "🏆 **Твои достижения**\n\n"
    
    # Полученные
    if stats['achievements']:
        text += "✅ **Получено:**\n"
        for ach_id in stats['achievements']:
            ach = ACHIEVEMENTS[ach_id]
            text += f"{ach['name']} +{ach['bonus']} токенов\n"
        text += "\n"
    
    # Доступные
    text += "📋 **Доступно:**\n"
    for ach_id, ach in ACHIEVEMENTS.items():
        if ach_id not in stats['achievements']:
            text += f"{ach['name']}: {ach['desc']} (+{ach['bonus']})\n"
    
    text += f"\n💰 Твой лимит: {stats['token_limit']} токенов"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def over_stats(update, context):
    user = update.effective_user
    over = achievements.get_over_limit_stats(user.id)
    
    text = (
        f"🔥 **Статистика превышений**\n\n"
        f"📊 Всего превышений: {over['total']}\n"
        f"📈 Сегодня: {over['today']}\n"
        f"⚡ Дней подряд: {over['streak']}\n"
        f"🏆 Рекорд за день: {over['max_day']}\n"
        f"🔄 Всего раз: {over['count']}\n\n"
        f"⚡ Чем больше превышаешь, тем круче достижения!"
    )
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def stats(update, context):
    user = update.effective_user
    stats = achievements.user_stats[user.id]
    over = achievements.get_over_limit_stats(user.id)
    
    text = (
        f"📊 **Твоя статистика**\n\n"
        f"💬 Сообщений: {stats['messages']}\n"
        f"🔥 Стрик дней: {stats['streak']}\n"
        f"💰 Лимит: {stats['token_limit']}\n"
        f"⚡ Осталось: {achievements.get_remaining_tokens(user.id)}\n"
        f"🏆 Достижений: {len(stats['achievements'])}\n\n"
        f"🔥 Превышений: {over['total']}\n"
        f"📈 Сегодня: {over['today']}"
    )
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def note(update, context):
    user = update.effective_user
    if not context.args:
        notes = achievements.user_stats[user.id].get('notes', [])[-5:]
        if notes:
            text = '\n'.join([f"• {n}" for n in notes])
            await update.message.reply_text(f"📝 Заметки:\n{text}")
        else:
            await update.message.reply_text("📝 Заметок нет. Напиши /note текст")
    else:
        if 'notes' not in achievements.user_stats[user.id]:
            achievements.user_stats[user.id]['notes'] = []
        text = ' '.join(context.args)
        achievements.user_stats[user.id]['notes'].append(f"{datetime.now().strftime('%d.%m')}: {text}")
        await update.message.reply_text("✅ Сохранено")

async def remind(update, context):
    user = update.effective_user
    if len(context.args) < 3:
        await update.message.reply_text("Пример: /remind Позвонить через 30м")
        return
    
    text = ' '.join(context.args[:-2])
    time_str = context.args[-2] + context.args[-1]
    
    try:
        seconds = 0
        if 'ч' in time_str:
            seconds = int(time_str.replace('ч', '')) * 3600
        elif 'м' in time_str:
            seconds = int(time_str.replace('м', '')) * 60
        else:
            seconds = 300
        
        await update.message.reply_text(f"⏰ Напомню: {text}")
        
        async def job(context):
            await context.bot.send_message(chat_id=user.id, text=f"⏰ {text}")
        
        context.job_queue.run_once(job, seconds)
    except:
        await update.message.reply_text("❌ Ошибка. Используй: через 30м или через 2ч")

async def translate(update, context):
    if not context.args:
        await update.message.reply_text("Напиши текст для перевода")
        return
    text = ' '.join(context.args)
    response = await ai.ask(f"Переведи на английский: {text}", "", False)
    await update.message.reply_text(f"🌍 {response or 'Ошибка'}")

async def random_number(update, context):
    try:
        if context.args and '-' in context.args[0]:
            a, b = map(int, context.args[0].split('-'))
            num = random.randint(a, b)
        else:
            num = random.randint(1, 100)
        await update.message.reply_text(f"🎲 {num}")
    except:
        await update.message.reply_text("Пример: /random 1-100")

async def time_command(update, context):
    await update.message.reply_text(f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}")

# ==================== ОСНОВНОЙ ОБРАБОТЧИК ====================

async def handle_message(update, context):
    if update.effective_user.is_bot:
        return
    
    user = update.effective_user
    msg = update.message.text
    is_group = update.effective_chat.type != 'private'
    
    # Добавляем сообщение в статистику
    achievements.add_message(user.id)
    
    # Проверяем новые достижения
    new_achs = achievements.check_achievements(user.id)
    if new_achs:
        text = "🎉 **Новые достижения!**\n\n"
        for ach in new_achs:
            text += f"{ach['name']}: +{ach['bonus']} токенов\n"
        await update.message.reply_text(text, parse_mode='Markdown')
    
    # Проверяем лимит токенов в личке
    if not is_group:
        if achievements.can_use_tokens(user.id):
            # Есть токены - обычный режим
            await update.message.reply_chat_action("typing")
            response = await ai.ask(msg, user.first_name, is_group)
            
            if response:
                await update.message.reply_text(response)
                achievements.add_token_usage(user.id, TOKENS_PER_MESSAGE)
            else:
                await update.message.reply_text(random.choice(["Ага", "Понял", "Интересно"]))
        else:
            # Токены кончились - режим превышения
            achievements.add_over_limit_message(user.id)
            
            # Специальное уведомление о превышении
            over = achievements.get_over_limit_stats(user.id)
            
            await update.message.reply_chat_action("typing")
            
            # AI отвечает даже без токенов
            response = await ai.ask(msg, user.first_name, is_group)
            
            if response:
                await update.message.reply_text(
                    f"{response}\n\n⚡ Превышение лимита! Сегодня: {over['today']}"
                )
            else:
                await update.message.reply_text(
                    f"{random.choice(['Ага', 'Понял', 'Интересно'])}\n\n⚡ Превышение лимита! Сегодня: {over['today']}"
                )
            
            # Проверяем достижения за превышение
            new_achs = achievements.check_achievements(user.id)
            if new_achs:
                text = "🔥 **Достижения за превышение!**\n\n"
                for ach in new_achs:
                    text += f"{ach['name']}: +{ach['bonus']} токенов\n"
                await update.message.reply_text(text, parse_mode='Markdown')
    else:
        # В группе без лимитов
        await update.message.reply_chat_action("typing")
        response = await ai.ask(msg, user.first_name, is_group)
        
        if response:
            await update.message.reply_text(response)
        else:
            await update.message.reply_text(random.choice(["Ага", "Понял", "Интересно"]))

# ==================== ЕЖЕДНЕВНЫЙ СБРОС ====================

async def daily_reset(context):
    """Сбрасывает дневные счётчики"""
    for user_id in achievements.user_stats:
        achievements.reset_daily_over_limit(user_id)
        achievements.user_stats[user_id]['tokens_used'] = 0
    logger.info("🔄 Ежедневный сброс выполнен")

# ==================== ЗАПУСК ====================

def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("achievements", achievements_command))
    app.add_handler(CommandHandler("overstats", over_stats))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("note", note))
    app.add_handler(CommandHandler("remind", remind))
    app.add_handler(CommandHandler("translate", translate))
    app.add_handler(CommandHandler("random", random_number))
    app.add_handler(CommandHandler("time", time_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Ежедневный сброс в полночь
    if app.job_queue:
        app.job_queue.run_daily(daily_reset, time=datetime.strptime("00:00", "%H:%M").time())
    
    print(f"✅ {BOT_NAME} v{BOT_VERSION} с системой превышений")
    print(f"💰 Базовый лимит: {BASE_TOKEN_LIMIT} токенов")
    print(f"🏆 Всего достижений: {len(ACHIEVEMENTS)}")
    print(f"🔥 В том числе за превышение: 10")
    app.run_polling()

if __name__ == "__main__":
    main()
