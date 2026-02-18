import logging
import asyncio
import json
import random
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from collections import defaultdict

import aiohttp
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

# Настройка
TOKEN = "8398666469:AAFJuFpeUieZOnLVxStaviHr1X--O3yAAu8"
ADMIN_ID = 8386169734
BOT_NAME = "Зака"
BOT_FULL_NAME = "Закатун"
CREATOR_NAME = "Михаил Закатов"
BOT_VERSION = "3.1"

# Mistral AI
MISTRAL_API_KEY = "HCxrOgMwskodETQDGvITs4f65Qzwemiz"
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

# Настройки для авто-сообщений
AUTO_MESSAGE_DELAY = 300  # 5 минут бездействия в группе
MAX_AUTO_MESSAGES_PER_DAY = 5

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== ПОЛНЫЙ ПРОФИЛЬ ЗАКАТУНА ====================

ZAKATOON_PROFILE = {
    "name": "Михаил Закатов",
    "nickname": "Закатун",
    "channel_name": "ZAKATOON",
    "birth_date": "2 марта 1990",
    "city": "Новосибирск",
    "family": "женат, есть дочь Мия",
    
    # Биография
    "bio": [
        "Родился в Новосибирске 2 марта 1990 года",
        "Служил в Вооружённых силах России",
        "Работал поваром, в пиццерии и на заводе",
        "Увлекается научной литературой, компьютерными играми и рисованием"
    ],
    
    # YouTube каналы
    "youtube": {
        "main": {
            "name": "@ZAKATOON",
            "url": "https://youtube.com/@ZAKATOON",
            "start_date": "12 декабря 2017",
            "subscribers": "5.88 млн (январь 2025)",
            "total_views": "1.1 млрд",
            "videos_count": "250+",
            "genre": "авторская анимация, юмор, истории из жизни",
            "top_video": {
                "title": "Всё! Про летний лагерь… (сборник)",
                "views": "32 млн"
            },
            "categories": ["Фильмы и анимация"],
            "upload_frequency": "2-3 видео в неделю",
            "ranking_russia": "#76",
            "ranking_world": "#5,475"
        },
        "second": {
            "name": "@ZAKAMINI",
            "url": "https://youtube.com/@ZAKAMINI",
            "start_date": "апрель 2018",
            "content": "видеоуроки и короткие мультфильмы"
        }
    },
    
    # Социальные сети
    "social_media": {
        "youtube": {
            "main": "https://youtube.com/@ZAKATOON",
            "second": "https://youtube.com/@ZAKAMINI",
            "subscribers": "5.88 млн"
        },
        "vk": {
            "url": "https://vk.com/zakatoon",
            "subscribers": "318 тыс."
        },
        "telegram": {
            "url": "https://t.me/zakatoon",
            "subscribers": "134 тыс."
        },
        "tiktok": {
            "url": "https://tiktok.com/@zakintok",
            "subscribers": "163 тыс."
        },
        "rutube": {
            "url": "https://rutube.ru/u/zakatoon",
            "subscribers": "12 тыс."
        },
        "dzen": {
            "url": "https://dzen.ru/zakatoon",
            "subscribers": "5 тыс."
        }
    },
    
    # Известные видео
    "popular_videos": [
        {
            "title": "Всё! Про летний лагерь… (сборник)",
            "views": "32 млн",
            "platform": "YouTube"
        },
        {
            "title": "100 фактов про ЗАКАТУНА",
            "views": "100K",
            "url": "https://rutube.ru/video/f04362e7c24bd0655a5a30fac11f0319/",
            "platform": "RuTube"
        },
        {
            "title": "Больничные истории (ремейк)",
            "views": "13.4K",
            "url": "https://rutube.ru/video/271458ac871d252d7a9bd91fb3eaf918/",
            "platform": "RuTube"
        },
        {
            "title": "Как я стал блогером",
            "views": "5.4K",
            "url": "https://vk.com/video-183318409_456283604",
            "platform": "VK Видео"
        }
    ],
    
    # Процесс создания
    "content_creation": {
        "animation_editing": "1 неделя",
        "voice_over": "1 неделя",
        "total_per_video": "2 недели",
        "average_length": "8 минут"
    },
    
    # Интересные факты
    "facts": [
        "На создание одного видео уходит около 2 недель: неделя на анимацию и монтаж, неделя на озвучивание",
        "Самый популярный ролик про летний лагерь набрал 32 миллиона просмотров",
        "До того как стать блогером, работал поваром, в пиццерии и на заводе",
        "Служил в армии",
        "Увлекается научной литературой, компьютерными играми и рисованием"
    ],
    
    # Хобби
    "hobbies": ["научная литература", "компьютерные игры", "рисование"],
    
    # Характер
    "personality": [
        "дружелюбный",
        "с юмором",
        "любит рассказывать истории из жизни",
        "самоирония",
        "простые, понятные рифмы в песнях",
        "местами смешно, местами трогательно"
    ]
}

# ==================== БАЗА ДАННЫХ ====================

class Database:
    def __init__(self):
        self.last_message_time: Dict[int, datetime] = defaultdict(lambda: datetime.now())
        self.auto_messages_count: Dict[int, int] = defaultdict(int)
        self.last_auto_message_date: Dict[int, datetime] = defaultdict(lambda: datetime.now().date())
        self.messages: Dict[int, List[dict]] = defaultdict(list)
    
    def update_last_message(self, chat_id: int):
        self.last_message_time[chat_id] = datetime.now()
    
    def should_send_auto_message(self, chat_id: int) -> bool:
        time_diff = datetime.now() - self.last_message_time[chat_id]
        if time_diff.total_seconds() < AUTO_MESSAGE_DELAY:
            return False
        
        today = datetime.now().date()
        if self.last_auto_message_date[chat_id] != today:
            self.auto_messages_count[chat_id] = 0
            self.last_auto_message_date[chat_id] = today
        
        return self.auto_messages_count[chat_id] < MAX_AUTO_MESSAGES_PER_DAY
    
    def add_auto_message(self, chat_id: int):
        self.auto_messages_count[chat_id] += 1
    
    def add_message(self, chat_id: int, username: str, text: str, is_bot: bool = False):
        self.messages[chat_id].append({
            'username': username,
            'text': text,
            'time': datetime.now().isoformat(),
            'is_bot': is_bot
        })
        if len(self.messages[chat_id]) > 20:
            self.messages[chat_id] = self.messages[chat_id][-20:]
    
    def get_context(self, chat_id: int, limit: int = 5) -> str:
        messages = self.messages.get(chat_id, [])[-limit:]
        context = []
        for msg in messages:
            name = "Закатун" if msg['is_bot'] else msg['username']
            context.append(f"{name}: {msg['text']}")
        return "\n".join(context)

db = Database()

# ==================== MISTRAL AI ====================

class MistralAI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.model = "mistral-medium"
    
    async def get_response(self, message: str, context: str, chat_type: str, username: str = "Пользователь") -> Optional[str]:
        """Получает ответ от Mistral AI с учётом личности Закатуна"""
        
        # Определяем стиль общения
        if chat_type == 'private':
            style = "Ты в личном чате. Общайся дружелюбно, как с другом."
        else:
            style = "Ты в групповом чате. Отвечай кратко, 1-2 предложения."
        
        # Формируем полный профиль Закатуна
        profile_text = f"""
Ты - {ZAKATOON_PROFILE['nickname']} (настоящее имя {ZAKATOON_PROFILE['name']}).

ЛИЧНЫЕ ДАННЫЕ:
• Родился: {ZAKATOON_PROFILE['birth_date']} в {ZAKATOON_PROFILE['city']}
• Семья: {ZAKATOON_PROFILE['family']}
• До блога: работал поваром, в пиццерии, на заводе, служил в армии
• Увлечения: {', '.join(ZAKATOON_PROFILE['hobbies'])}

YOUTUBE КАНАЛ:
• Название: {ZAKATOON_PROFILE['youtube']['main']['name']}
• Создан: {ZAKATOON_PROFILE['youtube']['main']['start_date']}
• Подписчиков: {ZAKATOON_PROFILE['youtube']['main']['subscribers']}
• Просмотров: {ZAKATOON_PROFILE['youtube']['main']['total_views']}
• Контент: {ZAKATOON_PROFILE['youtube']['main']['genre']}
• Популярное видео: "{ZAKATOON_PROFILE['youtube']['main']['top_video']['title']}" - {ZAKATOON_PROFILE['youtube']['main']['top_video']['views']} просмотров
• Второй канал: {ZAKATOON_PROFILE['youtube']['second']['name']} для уроков анимации

СОЦСЕТИ:
• YouTube: {ZAKATOON_PROFILE['social_media']['youtube']['main']}
• ВК: {ZAKATOON_PROFILE['social_media']['vk']['url']} ({ZAKATOON_PROFILE['social_media']['vk']['subscribers']})
• Telegram: {ZAKATOON_PROFILE['social_media']['telegram']['url']} ({ZAKATOON_PROFILE['social_media']['telegram']['subscribers']})
• TikTok: {ZAKATOON_PROFILE['social_media']['tiktok']['url']} ({ZAKATOON_PROFILE['social_media']['tiktok']['subscribers']})

ХАРАКТЕР:
• {', '.join(ZAKATOON_PROFILE['personality'])}

ИНТЕРЕСНЫЕ ФАКТЫ:
• {ZAKATOON_PROFILE['facts'][0]}
• {ZAKATOON_PROFILE['facts'][1]}
• {ZAKATOON_PROFILE['facts'][2]}
• {ZAKATOON_PROFILE['facts'][3]}

Сейчас ты общаешься с пользователем {username}. {style}

Важно:
1. Отвечай как реальный человек, от первого лица
2. Используй информацию о себе, когда это уместно
3. Будь дружелюбным, с юмором
4. Не говори, что ты бот или AI - ты Закатун
5. Если спросят про соцсети - давай ссылки
6. Рассказывай истории из жизни, как в своих видео
"""
        
        prompt = {
            "role": "user",
            "content": (
                f"{profile_text}\n\n"
                f"Контекст разговора:\n{context}\n\n"
                f"Новое сообщение от {username}: {message}\n\n"
                f"Ответь как Закатун, естественно и с юмором. Не используй markdown."
            )
        }
        
        response = await self._get_response([prompt])
        return response
    
    async def get_auto_message(self, context: str) -> Optional[str]:
        """Генерирует авто-сообщение для группы"""
        
        prompt = {
            "role": "user",
            "content": (
                f"Ты - {BOT_FULL_NAME}, видеоблогер из Новосибирска. В группе давно никто не писал.\n"
                f"Последние сообщения:\n{context}\n\n"
                f"Придумай что-нибудь, чтобы начать разговор. Напиши 1 предложение как Закатун."
            )
        }
        
        response = await self._get_response([prompt])
        return response
    
    async def _get_response(self, messages: List[dict]) -> Optional[str]:
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.8,
            "max_tokens": 200
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(MISTRAL_API_URL, headers=headers, json=data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return result['choices'][0]['message']['content']
                    else:
                        error = await resp.text()
                        logger.error(f"Mistral ошибка: {error}")
        except Exception as e:
            logger.error(f"Mistral request error: {e}")
        return None

# Инициализация AI
mistral = MistralAI(MISTRAL_API_KEY)

# ==================== КОМАНДЫ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    chat = update.effective_chat
    
    logger.info(f"Старт от {user.first_name} в {chat.type}")
    
    db.update_last_message(chat.id)
    
    if chat.type == 'private':
        await update.message.reply_text(
            f"👋 Привет! Я **{BOT_FULL_NAME}**!\n\n"
            f"Я видеоблогер из Новосибирска, делаю анимацию на YouTube. Можем поболтать о чём угодно! 😊\n\n"
            f"Команды: /help",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f"👋 Всем привет! Я **{BOT_FULL_NAME}**!\n"
            f"Рад поболтать в вашей компании!\n\n"
            f"Команды: /help",
            parse_mode='Markdown'
        )

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /about - информация о Закатуне"""
    about_text = (
        f"📚 **Обо мне**\n\n"
        f"👤 **Личное:**\n"
        f"• Имя: {ZAKATOON_PROFILE['name']}\n"
        f"• Псевдоним: {ZAKATOON_PROFILE['nickname']}\n"
        f"• Родился: {ZAKATOON_PROFILE['birth_date']}\n"
        f"• Город: {ZAKATOON_PROFILE['city']}\n"
        f"• Семья: {ZAKATOON_PROFILE['family']}\n\n"
        
        f"🎥 **YouTube:**\n"
        f"• Канал: {ZAKATOON_PROFILE['youtube']['main']['name']}\n"
        f"• Создан: {ZAKATOON_PROFILE['youtube']['main']['start_date']}\n"
        f"• Подписчиков: {ZAKATOON_PROFILE['youtube']['main']['subscribers']}\n"
        f"• Просмотров: {ZAKATOON_PROFILE['youtube']['main']['total_views']}\n"
        f"• Топ видео: \"{ZAKATOON_PROFILE['youtube']['main']['top_video']['title']}\" ({ZAKATOON_PROFILE['youtube']['main']['top_video']['views']})\n"
        f"• Второй канал: {ZAKATOON_PROFILE['youtube']['second']['name']}\n\n"
        
        f"📱 **Соцсети:**\n"
        f"• YouTube: {ZAKATOON_PROFILE['social_media']['youtube']['main']}\n"
        f"• ВК: {ZAKATOON_PROFILE['social_media']['vk']['url']}\n"
        f"• Telegram: {ZAKATOON_PROFILE['social_media']['telegram']['url']}\n"
        f"• TikTok: {ZAKATOON_PROFILE['social_media']['tiktok']['url']}\n\n"
        
        f"⭐ **Интересные факты:**\n"
        f"• {ZAKATOON_PROFILE['facts'][0]}\n"
        f"• {ZAKATOON_PROFILE['facts'][1]}\n"
        f"• {ZAKATOON_PROFILE['facts'][2]}"
    )
    await update.message.reply_text(about_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    chat = update.effective_chat
    
    db.update_last_message(chat.id)
    
    help_text = (
        f"🤖 **{BOT_FULL_NAME} - помощь**\n\n"
        f"**Что я умею:**\n"
        f"• Общаться на любые темы\n"
        f"• Рассказывать о себе и своей жизни\n"
        f"• Давать ссылки на соцсети\n"
        f"• Поддерживать беседу\n\n"
        f"**Команды:**\n"
        f"/start - приветствие\n"
        f"/about - информация обо мне\n"
        f"/help - это сообщение"
    )
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

# ==================== ОСНОВНОЙ ОБРАБОТЧИК ====================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений с AI"""
    chat = update.effective_chat
    user = update.effective_user
    message = update.message
    
    # Игнорируем ботов
    if user.is_bot:
        return
    
    # Обновляем время
    db.update_last_message(chat.id)
    
    # Сохраняем сообщение
    username = user.first_name
    db.add_message(chat.id, username, message.text, is_bot=False)
    
    logger.info(f"Сообщение от {username}: {message.text[:50]}...")
    
    # Печатает...
    await message.reply_chat_action("typing")
    
    # Получаем контекст
    context_text = db.get_context(chat.id, limit=5)
    
    # Получаем ответ от AI
    response = await mistral.get_response(
        message.text, 
        context_text,
        chat.type,
        username
    )
    
    if response:
        # В личке без реплая, в группе с реплаем
        if chat.type == 'private':
            await message.reply_text(response)
        else:
            await message.reply_text(response, reply_to_message_id=message.message_id)
        
        # Сохраняем ответ
        db.add_message(chat.id, BOT_NAME, response, is_bot=True)
        logger.info(f"✅ Ответ отправлен")
    else:
        # Запасной вариант если AI не ответил
        fallback = "Ой, задумался немного... Давай еще раз?"
        if chat.type == 'private':
            await message.reply_text(fallback)
        else:
            await message.reply_text(fallback, reply_to_message_id=message.message_id)

# ==================== АВТО-СООБЩЕНИЯ ====================

async def auto_message_job(context: ContextTypes.DEFAULT_TYPE):
    """Периодически проверяет, нужно ли отправить авто-сообщение"""
    for chat_id, last_time in list(db.last_message_time.items()):
        # Только группы (отрицательные ID)
        if chat_id > 0:
            continue
        
        if db.should_send_auto_message(chat_id):
            try:
                # Получаем контекст
                context_text = db.get_context(chat_id, limit=3)
                
                # Генерируем авто-сообщение
                auto_message = await mistral.get_auto_message(context_text)
                
                if auto_message:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=auto_message
                    )
                    db.add_auto_message(chat_id)
                    db.update_last_message(chat_id)
                    db.add_message(chat_id, BOT_NAME, auto_message, is_bot=True)
                    logger.info(f"🤖 Авто-сообщение в чат {chat_id}")
            except Exception as e:
                logger.error(f"Ошибка авто-сообщения: {e}")

# ==================== ОБРАБОТЧИК ОШИБОК ====================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Ошибка: {context.error}")
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "😔 Ой, что-то пошло не так... Попробуй еще раз!"
            )
    except:
        pass

# ==================== ЗАПУСК ====================

def main():
    """Запуск бота"""
    app = Application.builder().token(TOKEN).build()
    
    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    
    # Сообщения
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Планировщик для авто-сообщений
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(auto_message_job, interval=60, first=30)
    
    # Ошибки
    app.add_error_handler(error_handler)
    
    print("=" * 60)
    print(f"🤖 {BOT_FULL_NAME} с полным профилем запущен!")
    print(f"📊 Токен: {TOKEN[:10]}...")
    print(f"👑 Админ ID: {ADMIN_ID}")
    print(f"📋 Профиль загружен: {ZAKATOON_PROFILE['name']}")
    print(f"🎥 YouTube: {ZAKATOON_PROFILE['youtube']['main']['subscribers']}")
    print(f"💬 В личке: просто сообщения")
    print(f"👥 В группах: авто-разговор")
    print("=" * 60)
    
    app.run_polling()

if __name__ == "__main__":
    main()
