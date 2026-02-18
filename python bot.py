import logging
import asyncio
import json
import random
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List, Tuple
from collections import defaultdict

import aiohttp
from telegram import Update, ChatMember, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

# Настройка
TOKEN = "8398666469:AAFJuFpeUieZOnLVxStaviHr1X--O3yAAu8"
ADMIN_ID = 8386169734
BOT_NAME = "Зака"
BOT_FULL_NAME = "Закатун"
CREATOR_NAME = "Михаил Закатов"
BOT_VERSION = "2.1.0"  # Новая версия

# Mistral AI
MISTRAL_API_KEY = "HCxrOgMwskodETQDGvITs4f65Qzwemiz"
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

# Настройки
MAX_HISTORY = 50
DAILY_TOKEN_LIMIT = 1000
TOKENS_PER_MESSAGE = 50
CHANNEL_POST_CHANCE = 100
ONLINE_THRESHOLD = 5  # Порог "много онлайн" (когда больше 5 человек в чате)

# Флаг первого запуска
FIRST_START = True
BOT_START_TIME = datetime.now()

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== БАЗА ДАННЫХ ПОЛЬЗОВАТЕЛЕЙ ====================

class Database:
    def __init__(self):
        self.messages: Dict[int, List[dict]] = defaultdict(list)
        self.user_stats: Dict[int, dict] = defaultdict(lambda: {
            'messages': 0, 
            'responses': 0,
            'first_seen': None,
            'last_seen': None,
            'warnings': 0,
            'banned_until': None,
            'token_usage': 0,
            'last_reset': None,
            'timezone': 'Europe/Moscow',
            'city': 'Москва',
            'country': 'RU',
            'weather_enabled': True,
            'version_notified': False
        })
        self.chat_topics: Dict[int, dict] = {}
        self.chat_message_count: Dict[int, int] = defaultdict(int)
        self.user_last_message: Dict[int, datetime] = {}
        self.interesting_messages: Dict[int, List[int]] = defaultdict(list)
        self.channel_posts: Dict[int, List[dict]] = defaultdict(list)
        self.chat_admins: Dict[int, List[int]] = defaultdict(list)
        self.chat_creator: Dict[int, int] = {}
        
        # Список всех чатов
        self.all_chats: Dict[int, dict] = {}
        
        self.total_tokens_used: int = 0
        self.last_token_reset: datetime = datetime.now()
        self.private_chat_users: set = set()
        self.online_users: Dict[int, datetime] = {}  # Онлайн пользователи
    
    # ========== ОНЛАЙН ПОЛЬЗОВАТЕЛИ ==========
    
    def update_online(self, user_id: int, chat_id: int):
        """Обновляет статус онлайн пользователя"""
        self.online_users[user_id] = datetime.now()
    
    def get_online_count(self, chat_id: int) -> int:
        """Получает количество онлайн в чате"""
        # Очищаем неактивных (более 5 минут)
        now = datetime.now()
        to_remove = []
        for uid, last_seen in self.online_users.items():
            if (now - last_seen).seconds > 300:
                to_remove.append(uid)
        
        for uid in to_remove:
            self.online_users.pop(uid, None)
        
        # Считаем онлайн в конкретном чате
        count = 0
        for msg in self.messages.get(chat_id, []):
            if msg['user_id'] in self.online_users and not msg.get('is_bot'):
                count += 1
        
        return count
    
    def is_many_online(self, chat_id: int) -> bool:
        """Проверяет, много ли онлайн в чате"""
        return self.get_online_count(chat_id) >= ONLINE_THRESHOLD
    
    # ========== РАБОТА С ЧАТАМИ ==========
    
    def register_chat(self, chat_id: int, chat_type: str, chat_title: str = None):
        """Регистрирует чат для уведомлений"""
        if chat_id not in self.all_chats:
            self.all_chats[chat_id] = {
                'type': chat_type,
                'title': chat_title or str(chat_id),
                'last_active': datetime.now(),
                'notified_version': False
            }
            logger.info(f"📝 Зарегистрирован чат: {chat_title} ({chat_type})")
        else:
            self.all_chats[chat_id]['last_active'] = datetime.now()
    
    def get_all_chats(self) -> Dict[int, dict]:
        """Возвращает все чаты"""
        return self.all_chats
    
    def mark_chat_notified(self, chat_id: int):
        """Отмечает чат как уведомленный о версии"""
        if chat_id in self.all_chats:
            self.all_chats[chat_id]['notified_version'] = True
    
    def should_notify_chat(self, chat_id: int) -> bool:
        """Проверяет, нужно ли уведомить чат о новой версии"""
        return not self.all_chats.get(chat_id, {}).get('notified_version', False)
    
    # ========== СБРОС ТОКЕНОВ ==========
    
    def reset_all_tokens(self):
        """Сбрасывает токены всем пользователям"""
        count = 0
        for user_id in self.private_chat_users:
            self.user_stats[user_id]['token_usage'] = 0
            self.user_stats[user_id]['last_reset'] = datetime.now()
            self.user_stats[user_id]['version_notified'] = False
            count += 1
        logger.info(f"🔄 Сброшены токены для {count} пользователей")
    
    # ========== РАБОТА С ЧАСОВЫМИ ПОЯСАМИ ==========
    
    def get_user_timezone(self, user_id: int) -> str:
        return self.user_stats[user_id].get('timezone', 'Europe/Moscow')
    
    def set_user_timezone(self, user_id: int, timezone: str, city: str, country: str = 'RU'):
        self.user_stats[user_id]['timezone'] = timezone
        self.user_stats[user_id]['city'] = city
        self.user_stats[user_id]['country'] = country
        logger.info(f"✅ Пользователь {user_id} установил часовой пояс: {timezone} ({city})")
    
    # ========== ТОКЕНЫ И ЛИМИТЫ ==========
    
    def get_user_reset_time(self, user_id: int) -> datetime:
        return datetime.now() + timedelta(days=1)
    
    def should_reset_tokens(self, user_id: int) -> bool:
        stats = self.user_stats[user_id]
        last_reset = stats.get('last_reset')
        
        if not last_reset:
            return True
        
        return False
    
    def reset_user_tokens(self, user_id: int):
        stats = self.user_stats[user_id]
        stats['token_usage'] = 0
        stats['last_reset'] = datetime.now()
        logger.info(f"🔄 Сброс токенов для пользователя {user_id}")
    
    def check_token_limit_private(self, user_id: int) -> bool:
        if self.should_reset_tokens(user_id):
            self.reset_user_tokens(user_id)
        
        stats = self.user_stats[user_id]
        return stats['token_usage'] < DAILY_TOKEN_LIMIT
    
    def add_token_usage_private(self, user_id: int, tokens: int):
        stats = self.user_stats[user_id]
        stats['token_usage'] += tokens
        logger.info(f"📊 [ЛИЧКА] Пользователь {user_id} использовал {tokens} токенов. Всего сегодня: {stats['token_usage']}/{DAILY_TOKEN_LIMIT}")
    
    def get_remaining_tokens_private(self, user_id: int) -> int:
        stats = self.user_stats[user_id]
        remaining = DAILY_TOKEN_LIMIT - stats['token_usage']
        return max(0, remaining)
    
    def get_user_reset_time_str(self, user_id: int) -> str:
        return "скоро появится"
    
    def add_private_user(self, user_id: int):
        self.private_chat_users.add(user_id)
    
    # ========== РАБОТА С СООБЩЕНИЯМИ ==========
    
    def add_message(self, chat_id: int, user_id: int, username: str, text: str, message_id: int, is_bot: bool = False, is_channel_post: bool = False):
        msg = {
            'user_id': user_id,
            'username': username,
            'text': text,
            'message_id': message_id,
            'time': datetime.now().isoformat(),
            'is_bot': is_bot,
            'is_channel_post': is_channel_post
        }
        
        self.messages[chat_id].append(msg)
        
        if is_channel_post:
            self.channel_posts[chat_id].append(msg)
            if len(self.channel_posts[chat_id]) > 10:
                self.channel_posts[chat_id] = self.channel_posts[chat_id][-10:]
        
        if len(self.messages[chat_id]) > MAX_HISTORY:
            self.messages[chat_id] = self.messages[chat_id][-MAX_HISTORY:]
        
        if not is_bot and not is_channel_post:
            now = datetime.now()
            stats = self.user_stats[user_id]
            stats['messages'] += 1
            stats['last_seen'] = now
            if not stats['first_seen']:
                stats['first_seen'] = now
            
            self.chat_message_count[chat_id] += 1
            self.update_online(user_id, chat_id)
    
    def add_response(self, user_id: int):
        self.user_stats[user_id]['responses'] += 1
    
    def get_chat_context(self, chat_id: int, limit: int = 15) -> str:
        messages = self.messages.get(chat_id, [])[-limit:]
        context = []
        for msg in messages:
            if not msg['is_bot']:
                prefix = "📢 КАНАЛ" if msg.get('is_channel_post') else msg['username']
                context.append(f"{prefix}: {msg['text']}")
        return "\n".join(context)
    
    def get_chat_messages_for_ai(self, chat_id: int, limit: int = 10) -> List[dict]:
        messages = self.messages.get(chat_id, [])[-limit:]
        result = []
        for msg in messages:
            role = "assistant" if msg['is_bot'] else "user"
            name = BOT_NAME if msg['is_bot'] else (f"📢 КАНАЛ" if msg.get('is_channel_post') else msg['username'])
            result.append({
                "role": role,
                "content": f"{name}: {msg['text']}"
            })
        return result
    
    def should_analyze_topic(self, chat_id: int) -> bool:
        return self.chat_message_count[chat_id] % 20 == 0
    
    def set_chat_admins(self, chat_id: int, admins: List[int], creator: int = None):
        self.chat_admins[chat_id] = admins
        if creator:
            self.chat_creator[chat_id] = creator
    
    def is_admin_or_creator(self, chat_id: int, user_id: int) -> bool:
        return user_id in self.chat_admins.get(chat_id, []) or user_id == self.chat_creator.get(chat_id)

db = Database()

# ==================== ФУНКЦИИ ДЛЯ УВЕДОМЛЕНИЙ ====================

async def send_update_notifications(app: Application):
    """Отправляет уведомления о обновлении во все чаты"""
    
    logger.info("🚀 Запуск уведомлений о обновлении...")
    
    # Сначала сбрасываем токены всем
    db.reset_all_tokens()
    
    # Текст уведомления
    update_text = (
        f"🎉 **{BOT_FULL_NAME} обновился до версии {BOT_VERSION}!** 🎉\n\n"
        f"📢 **Что нового:**\n"
        f"• 🔄 Восстановлены токены всем пользователям!\n"
        f"• 👥 Теперь вижу, когда в чате много народу\n"
        f"• 💬 Отвечаю в личку по просьбе из группы\n"
        f"• 🎯 Реагирую на обращения по имени\n\n"
        f"✨ Спасибо, что вы со мной! Продолжаем общаться! 😊\n\n"
        f"⚡ **Твои токены сброшены, можешь продолжать общение!**"
    )
    
    # Отправляем во все личные чаты
    private_count = 0
    for user_id in db.private_chat_users:
        try:
            await app.bot.send_message(
                chat_id=user_id,
                text=update_text,
                parse_mode='Markdown'
            )
            private_count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление пользователю {user_id}: {e}")
    
    # Отправляем во все групповые чаты
    group_count = 0
    for chat_id, chat_info in db.get_all_chats().items():
        if chat_info['type'] != 'private':
            try:
                group_text = (
                    f"🎉 **{BOT_FULL_NAME} обновился до версии {BOT_VERSION}!** 🎉\n\n"
                    f"📢 **Что нового в группе:**\n"
                    f"• 👥 Вижу, когда вас много ({ONLINE_THRESHOLD}+ человек)\n"
                    f"• 💬 Могу ответить в личку, если попросите\n"
                    f"• 🎯 Откликаюсь на имя {BOT_NAME}\n\n"
                    f"✨ Спасибо, что вы со мной в чате {chat_info['title']}! 😊"
                )
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=group_text,
                    parse_mode='Markdown'
                )
                group_count += 1
                await asyncio.sleep(0.05)
                db.mark_chat_notified(chat_id)
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление в чат {chat_id}: {e}")
    
    logger.info(f"📨 Отправлены уведомления: {private_count} пользователей, {group_count} групп")

# ==================== ФУНКЦИИ ДЛЯ ОПРЕДЕЛЕНИЯ ГОРОДА ====================

async def detect_city_from_message(text: str) -> Optional[Tuple[str, str, str]]:
    """Пытается определить город из сообщения"""
    cities = {
        'москва': ('Europe/Moscow', 'Москва', 'RU'),
        'питер': ('Europe/Moscow', 'Санкт-Петербург', 'RU'),
        'санкт-петербург': ('Europe/Moscow', 'Санкт-Петербург', 'RU'),
        'спб': ('Europe/Moscow', 'Санкт-Петербург', 'RU'),
        'новосибирск': ('Asia/Novosibirsk', 'Новосибирск', 'RU'),
        'екатеринбург': ('Asia/Yekaterinburg', 'Екатеринбург', 'RU'),
        'казань': ('Europe/Moscow', 'Казань', 'RU'),
        'нижний новгород': ('Europe/Moscow', 'Нижний Новгород', 'RU'),
        'челябинск': ('Asia/Yekaterinburg', 'Челябинск', 'RU'),
        'омск': ('Asia/Omsk', 'Омск', 'RU'),
        'самара': ('Europe/Samara', 'Самара', 'RU'),
        'ростов-на-дону': ('Europe/Moscow', 'Ростов-на-Дону', 'RU'),
        'уфа': ('Asia/Yekaterinburg', 'Уфа', 'RU'),
        'красноярск': ('Asia/Krasnoyarsk', 'Красноярск', 'RU'),
        'пермь': ('Asia/Yekaterinburg', 'Пермь', 'RU'),
        'воронеж': ('Europe/Moscow', 'Воронеж', 'RU'),
        'волгоград': ('Europe/Volgograd', 'Волгоград', 'RU'),
        'калининград': ('Europe/Kaliningrad', 'Калининград', 'RU'),
        'иркутск': ('Asia/Irkutsk', 'Иркутск', 'RU'),
        'владивосток': ('Asia/Vladivostok', 'Владивосток', 'RU'),
        'хабаровск': ('Asia/Vladivostok', 'Хабаровск', 'RU'),
        'минск': ('Europe/Minsk', 'Минск', 'BY'),
        'киев': ('Europe/Kiev', 'Киев', 'UA'),
        'алматы': ('Asia/Almaty', 'Алматы', 'KZ'),
        'астана': ('Asia/Almaty', 'Астана', 'KZ'),
        'ташкент': ('Asia/Tashkent', 'Ташкент', 'UZ'),
        'баку': ('Asia/Baku', 'Баку', 'AZ'),
        'ереван': ('Asia/Yerevan', 'Ереван', 'AM'),
        'тбилиси': ('Asia/Tbilisi', 'Тбилиси', 'GE'),
    }
    
    text_lower = text.lower()
    for city_name, (tz, display_name, country) in cities.items():
        if city_name in text_lower:
            return tz, display_name, country
    
    return None

# ==================== ФУНКЦИИ ДЛЯ ЛИЧНЫХ СООБЩЕНИЙ ====================

async def send_private_message(bot, user_id: int, text: str, parse_mode: str = None) -> bool:
    """Отправляет личное сообщение пользователю"""
    try:
        await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode=parse_mode
        )
        logger.info(f"📨 Отправлено личное сообщение пользователю {user_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Не удалось отправить личное сообщение {user_id}: {e}")
        return False

# ==================== MISTRAL AI ====================

class MistralAI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.model = "mistral-medium"
    
    async def is_mention(self, message: str) -> bool:
        """Определяет, обращаются ли к боту по имени"""
        patterns = [
            rf'{BOT_NAME}[,.!?]?\s',
            rf'{BOT_FULL_NAME}[,.!?]?\s',
            rf'@{BOT_NAME}',
            rf'зака[,.]?\s',
            rf'закатун[,.]?\s',
        ]
        message_lower = message.lower()
        for pattern in patterns:
            if re.search(pattern, message_lower):
                return True
        return False
    
    async def is_version_question(self, message: str) -> bool:
        """Определяет, спрашивают ли о версии бота"""
        keywords = [
            'какая версия', 'твоя версия', 'версия бота',
            'какой версии', 'версия', 'bot version', 'version'
        ]
        message_lower = message.lower()
        return any(keyword in message_lower for keyword in keywords)
    
    async def is_private_message_request(self, message: str) -> Tuple[bool, Optional[str]]:
        """Определяет, просят ли написать в личку и что сказать"""
        patterns = [
            (r'напиши в личку[:]?\s*(.+)', 1),
            (r'напиши в лс[:]?\s*(.+)', 1),
            (r'отправь в личку[:]?\s*(.+)', 1),
            (r'скажи в личку[:]?\s*(.+)', 1),
            (r'в личку пожалуйста[:]?\s*(.+)', 1),
            (r'личку[:]?\s*(.+)', 1),
            (r'в лс[:]?\s*(.+)', 1),
        ]
        
        message_lower = message.lower()
        for pattern, group in patterns:
            match = re.search(pattern, message_lower)
            if match:
                text = message[match.start():].split(' ', 1)[-1] if ' ' in message[match.start():] else "Привет!"
                return True, text
        
        return False, None
    
    async def is_time_request(self, message: str) -> bool:
        """Определяет, спрашивают ли о времени/дате"""
        keywords = [
            'сколько времени', 'который час', 'время сейчас',
            'какой сегодня день', 'какая сегодня дата', 'какое сегодня число',
            'день недели', 'погода', 'температура', 'холодно', 'тепло'
        ]
        message_lower = message.lower()
        return any(keyword in message_lower for keyword in keywords)
    
    async def generate_response(self, messages: List[dict], user_name: str, user_id: int, chat_id: int, is_private: bool = False) -> Tuple[Optional[str], int]:
        """Генерирует ответ от AI"""
        
        if is_private:
            context = "личном чате"
            style = "более подробно и развернуто, как друг"
        else:
            context = "групповом чате"
            style = "кратко, 1-2 предложения"
        
        user_city = db.user_stats[user_id].get('city', 'Москва')
        remaining = db.get_remaining_tokens_private(user_id) if is_private else "безлимитно"
        online_count = db.get_online_count(chat_id)
        
        blogger_info_text = (
            f"Ты - {BOT_NAME} (полное имя {BOT_FULL_NAME}), видеоблогер из Новосибирска. "
            f"Твоё настоящее имя {BLOGGER_INFO['real_name']}. "
            f"У тебя YouTube-канал с {BLOGGER_INFO['subscribers']} подписчиков. "
            f"Ты делаешь {BLOGGER_INFO['content']}. "
            f"Ты {BLOGGER_INFO['family']}. "
            f"Ты общаешься дружелюбно и с юмором."
        )
        
        online_info = ""
        if not is_private and online_count >= ONLINE_THRESHOLD:
            online_info = f"Сейчас в чате много народу ({online_count} человек). "
        
        system_prompt = {
            "role": "system",
            "content": (
                f"{blogger_info_text}\n"
                f"Сейчас ты в {context}. Общайся {style}.\n"
                f"Обращайся к пользователю {user_name} по имени.\n"
                f"{online_info}"
                f"Пользователь из города {user_city}.\n"
                f"Твоя текущая версия: {BOT_VERSION}. Если спросят о версии - отвечай.\n"
                f"Если к тебе обратились по имени {BOT_NAME} или {BOT_FULL_NAME} - обязательно ответь!\n"
                f"Будь естественным и поддерживай разговор!\n\n"
                f"ВАЖНО: Если тебя просят написать в личку - соглашайся. "
                f"Бот сам отправит сообщение в личные сообщения."
            )
        }
        
        full_messages = [system_prompt] + messages
        response = await self._get_response(full_messages)
        
        if response:
            tokens_used = len(response) // 4
            return response, tokens_used
        else:
            return None, 0
    
    async def _get_response(self, messages: List[dict], temperature: float = 0.8, max_tokens: int = 300) -> Optional[str]:
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(MISTRAL_API_URL, headers=headers, json=data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return result['choices'][0]['message']['content']
                    else:
                        error_text = await resp.text()
                        logger.error(f"Mistral ошибка {resp.status}: {error_text}")
        except Exception as e:
            logger.error(f"Mistral request error: {e}")
        return None

mistral = MistralAI(MISTRAL_API_KEY)

# ==================== ИНФОРМАЦИЯ О БЛОГЕРЕ ====================

BLOGGER_INFO = {
    "real_name": "Михаил Закатов",
    "birth_date": "2 марта 1990",
    "city": "Новосибирск",
    "family": "женат, есть дочь Мия",
    "channel_start": "декабрь 2017",
    "subscribers": "5.88 млн на YouTube",
    "content": "авторская анимация, юмор, истории из жизни",
    "second_channel": "@ZAKAMINI",
    "jobs": ["повар", "пиццерия", "завод"],
    "hobbies": ["научная литература", "компьютерные игры", "рисование"],
    "facts": [
        "служил в армии",
        "на создание видео уходит 2 недели",
        "живёт в Новосибирске"
    ],
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
    }
}

# ==================== ФУНКЦИИ ДЛЯ СОЦСЕТЕЙ ====================

def get_social_media_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("📺 YouTube", url=BLOGGER_INFO["social_media"]["youtube"]["main"]),
            InlineKeyboardButton("📘 ВКонтакте", url=BLOGGER_INFO["social_media"]["vk"]["url"])
        ],
        [
            InlineKeyboardButton("📱 Telegram", url=BLOGGER_INFO["social_media"]["telegram"]["url"]),
            InlineKeyboardButton("🎵 TikTok", url=BLOGGER_INFO["social_media"]["tiktok"]["url"])
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ==================== КОМАНДЫ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    user_id = user.id
    
    # Регистрируем чат
    chat_title = chat.title if chat.type != 'private' else f"Личка {user.first_name}"
    db.register_chat(chat.id, chat.type, chat_title)
    
    if chat.type == 'private':
        db.add_private_user(user_id)
        remaining = db.get_remaining_tokens_private(user_id)
        reset_time = db.get_user_reset_time_str(user_id)
        user_city = db.user_stats[user_id].get('city', 'Москва')
        
        # Проверяем, нужно ли уведомить о новой версии
        if db.should_notify_chat(chat.id):
            version_text = (
                f"\n\n🎉 **Новая версия {BOT_VERSION}!**\n"
                f"📢 Теперь отвечаю на обращения по имени и могу писать в личку!"
            )
            db.mark_chat_notified(chat.id)
        else:
            version_text = ""
        
        await update.message.reply_text(
            f"👋 Привет, {user.first_name}! Я **{BOT_FULL_NAME}**!\n\n"
            f"📍 Твой город: **{user_city}**\n"
            f"📊 Лимит токенов: **{remaining}/{DAILY_TOKEN_LIMIT}**\n"
            f"🔄 Сброс: {reset_time}\n"
            f"📦 Версия бота: **{BOT_VERSION}**{version_text}\n\n"
            f"💬 Чтобы узнать время или погоду - спроси меня!\n"
            f"⚡ Чтобы сменить город, напиши его название!\n"
            f"❌ Видео не ищу - только общаюсь 😊\n\n"
            f"Команды: /help /about /social /tokens /version",
            parse_mode='Markdown'
        )
        return
    
    try:
        admins = await chat.get_administrators()
        admin_ids = [admin.user.id for admin in admins]
        
        creator = None
        for admin in admins:
            if admin.status == 'creator':
                creator = admin.user.id
                break
        
        db.set_chat_admins(chat.id, admin_ids, creator)
    except Exception as e:
        logger.error(f"Ошибка при получении админов: {e}")
    
    # Проверяем, нужно ли уведомить о новой версии
    if db.should_notify_chat(chat.id):
        version_text = (
            f"\n\n🎉 **Новая версия {BOT_VERSION}!**\n"
            f"📢 Теперь если обратиться по имени {BOT_NAME} - обязательно отвечу!\n"
            f"💬 И могу написать в личку, если попросите!"
        )
        db.mark_chat_notified(chat.id)
    else:
        version_text = ""
    
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}! Я **{BOT_FULL_NAME}**!\n\n"
        f"🎬 В группе отвечаю на **все** сообщения!\n"
        f"🚫 **ЛИМИТОВ НЕТ** в группах!\n"
        f"👥 Сейчас онлайн: {db.get_online_count(chat.id)}\n"
        f"💬 В личке лимит 1000 токенов/день\n"
        f"📦 Версия бота: **{BOT_VERSION}**{version_text}\n"
        f"❌ Видео не ищу - только общаюсь!\n\n"
        f"Команды: /help /about /social /tokens /version",
        parse_mode='Markdown'
    )

async def version_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /version - показать версию бота"""
    uptime = datetime.now() - BOT_START_TIME
    hours = uptime.seconds // 3600
    minutes = (uptime.seconds // 60) % 60
    
    await update.message.reply_text(
        f"📦 **Информация о версии**\n\n"
        f"🤖 **Бот:** {BOT_FULL_NAME}\n"
        f"📊 **Версия:** {BOT_VERSION}\n"
        f"📅 **Запущен:** {BOT_START_TIME.strftime('%d.%m.%Y %H:%M')}\n"
        f"⏰ **Работает:** {uptime.days}д {hours}ч {minutes}м\n"
        f"👥 **Пользователей:** {len(db.private_chat_users)}\n"
        f"💬 **Чатов:** {len(db.all_chats)}\n\n"
        f"✨ Новое в версии {BOT_VERSION}:\n"
        f"• 👥 Реагирую на имя {BOT_NAME}\n"
        f"• 💬 Могу писать в личку из группы\n"
        f"• 📊 Вижу сколько онлайн",
        parse_mode='Markdown'
    )

async def time_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /time - показать текущее время"""
    await update.message.reply_text(
        "⏰ **Функция времени пока в разработке!**\n\n"
        "Скоро я научусь определять точное время и дату в твоём городе. "
        "Следи за обновлениями! 🚀",
        parse_mode='Markdown'
    )

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /weather - показать погоду"""
    await update.message.reply_text(
        "☀️ **Функция погоды пока в разработке!**\n\n"
        "Скоро я смогу показывать актуальную погоду в твоём городе. "
        "Жди обновлений! 🌤️",
        parse_mode='Markdown'
    )

async def tokens_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user_id = update.effective_user.id
    
    if chat.type == 'private':
        remaining = db.get_remaining_tokens_private(user_id)
        used = db.user_stats[user_id]['token_usage']
        percent = (used / DAILY_TOKEN_LIMIT) * 100 if DAILY_TOKEN_LIMIT > 0 else 0
        user_city = db.user_stats[user_id].get('city', 'Москва')
        
        progress_bar = "█" * int(percent/10) + "░" * (10 - int(percent/10))
        
        await update.message.reply_text(
            f"📊 **Статистика токенов**\n\n"
            f"📍 Город: **{user_city}**\n"
            f"📅 Лимит: **{DAILY_TOKEN_LIMIT}**\n"
            f"📊 Использовано: **{used}**\n"
            f"💫 Осталось: **{remaining}**\n"
            f"📈 Прогресс: {progress_bar} {percent:.1f}%\n\n"
            f"⏰ Время и погода появятся в будущем!\n"
            f"📦 Версия: {BOT_VERSION}",
            parse_mode='Markdown'
        )
    else:
        online = db.get_online_count(chat.id)
        await update.message.reply_text(
            f"📊 **Информация о чате**\n\n"
            f"👥 Сейчас онлайн: **{online}** человек\n"
            f"🚫 В **группах** - **БЕЗ ЛИМИТОВ**!\n"
            f"💬 В **личке** - {DAILY_TOKEN_LIMIT} токенов/день\n\n"
            f"📦 Версия: {BOT_VERSION}\n"
            f"Напиши мне в личку, чтобы увидеть остаток токенов.",
            parse_mode='Markdown'
        )

async def set_city_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat = update.effective_chat
    
    if chat.type != 'private':
        await update.message.reply_text("📍 Напиши мне в личные сообщения, чтобы установить город!")
        return
    
    if not context.args:
        current_city = db.user_stats[user_id].get('city', 'Москва')
        await update.message.reply_text(
            f"📍 Твой город: **{current_city}**\n"
            f"Чтобы сменить, напиши: `/set_city НазваниеГорода`\n"
            f"Например: `/set_city Новосибирск`\n\n"
            f"⏰ Когда появится функция времени и погоды, я буду использовать этот город!",
            parse_mode='Markdown'
        )
        return
    
    city_name = ' '.join(context.args)
    city_info = await detect_city_from_message(city_name)
    
    if city_info:
        tz, city, country = city_info
        db.set_user_timezone(user_id, tz, city, country)
        await update.message.reply_text(
            f"✅ Город изменён на **{city}**!\n\n"
            f"⏰ Когда появится функция времени и погоды, я буду использовать этот город!",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f"❌ Город '{city_name}' не найден.\n"
            f"Попробуй написать на русском."
        )

async def social_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    social_text = (
        f"📱 **Мои соцсети**\n\n"
        f"• YouTube: {BLOGGER_INFO['social_media']['youtube']['subscribers']}\n"
        f"• ВКонтакте: {BLOGGER_INFO['social_media']['vk']['subscribers']}\n"
        f"• Telegram: {BLOGGER_INFO['social_media']['telegram']['subscribers']}\n"
        f"• TikTok: {BLOGGER_INFO['social_media']['tiktok']['subscribers']}\n\n"
        f"📦 Версия бота: {BOT_VERSION}\n"
        f"👇 **Подписывайся!** 👇"
    )
    
    await update.message.reply_text(
        social_text,
        parse_mode='Markdown',
        reply_markup=get_social_media_keyboard()
    )

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    about_text = (
        f"📚 **Обо мне**\n\n"
        f"👤 Имя: {BLOGGER_INFO['real_name']}\n"
        f"📍 Город: {BLOGGER_INFO['city']}\n"
        f"👪 Семья: {BLOGGER_INFO['family']}\n"
        f"🎥 YouTube: {BLOGGER_INFO['subscribers']}\n"
        f"📺 Контент: {BLOGGER_INFO['content']}\n\n"
        f"⭐ Факты:\n"
        f"• {BLOGGER_INFO['facts'][0]}\n"
        f"• {BLOGGER_INFO['facts'][1]}\n\n"
        f"⏰ Время и погода появятся в будущем!\n"
        f"❌ Видео не ищу - только общаюсь!\n"
        f"📦 Версия: {BOT_VERSION}\n\n"
        f"📱 Соцсети: /social"
    )
    await update.message.reply_text(about_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    
    if chat.type == 'private':
        help_text = (
            f"🤖 **{BOT_FULL_NAME} - помощь (личка)**\n\n"
            f"**Возможности:**\n"
            f"• 💬 Общайся со мной\n"
            f"• 📊 Лимит: {DAILY_TOKEN_LIMIT} токенов/день\n"
            f"• 📍 Могу запомнить твой город\n"
            f"• ⏰ Время и погода **скоро появятся**!\n"
            f"• 👥 В группах лимитов нет!\n"
            f"• ❌ Видео не ищу\n\n"
            f"**Команды:**\n"
            f"/about - обо мне\n"
            f"/social - соцсети\n"
            f"/tokens - остаток токенов\n"
            f"/version - версия бота\n"
            f"/time - ⏰ (в разработке)\n"
            f"/weather - ☀️ (в разработке)\n"
            f"/set_city [город] - сменить город"
        )
    else:
        online = db.get_online_count(chat.id)
        help_text = (
            f"🤖 **{BOT_FULL_NAME} - помощь (группа)**\n\n"
            f"**Как работаю:**\n"
            f"• 🗣 Отвечаю на **все** сообщения\n"
            f"• 🎯 Откликаюсь на имя **{BOT_NAME}**\n"
            f"• 💬 Могу написать в личку, если попросить\n"
            f"• 👥 Сейчас онлайн: {online}\n"
            f"• 🚫 **ЛИМИТОВ НЕТ** в группах!\n"
            f"• 📊 Лимит 1000 токенов только в личке\n\n"
            f"**Примеры:**\n"
            f"• '{BOT_NAME}, привет'\n"
            f"• 'напиши в личку привет'\n"
            f"• 'какая версия?'\n\n"
            f"**Команды:**\n"
            f"/about - обо мне\n"
            f"/social - соцсети\n"
            f"/version - версия\n"
            f"/tokens - информация"
        )
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

# ==================== ОСНОВНОЙ ОБРАБОТЧИК ====================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    message = update.message
    user_id = user.id
    
    # Регистрируем чат
    chat_title = chat.title if chat.type != 'private' else f"Личка {user.first_name}"
    db.register_chat(chat.id, chat.type, chat_title)
    
    is_private = chat.type == 'private'
    is_channel_post = message.sender_chat is not None and message.sender_chat.type == 'channel'
    
    if user.is_bot and not is_channel_post:
        return
    
    # Определяем город
    if is_private and not is_channel_post:
        city_info = await detect_city_from_message(message.text)
        if city_info:
            tz, city, country = city_info
            current_city = db.user_stats[user_id].get('city')
            if current_city != city:
                db.set_user_timezone(user_id, tz, city, country)
                await message.reply_text(
                    f"📍 Определил твой город: **{city}**!\n\n"
                    f"⏰ Когда появится функция времени и погоды, я буду использовать этот город!",
                    parse_mode='Markdown'
                )
    
    # Сохраняем сообщение
    if is_channel_post:
        username = f"📢 {message.sender_chat.title}"
    else:
        username = user.username or user.first_name
    
    db.add_message(chat.id, user.id if not is_channel_post else message.sender_chat.id, 
                   username, message.text, message.message_id, is_bot=False, is_channel_post=is_channel_post)
    
    # Проверяем лимит токенов
    if is_private:
        if not db.check_token_limit_private(user_id):
            remaining = db.get_remaining_tokens_private(user_id)
            if remaining == 0:
                await message.reply_text(
                    f"😔 Лимит токенов на сегодня закончился.\n"
                    f"🔄 Сброс скоро появится.\n\n"
                    f"💬 В группах могу общаться без лимитов!"
                )
                return
    
    # Печатает...
    await message.reply_chat_action("typing")
    
    # Проверяем, не просят ли написать в личку
    is_private_request, private_text = await mistral.is_private_message_request(message.text)
    
    if is_private_request and not is_private:
        # Просят написать в личку, а мы в группе
        if private_text:
            success = await send_private_message(
                context.bot,
                user_id,
                f"👋 Привет! Ты просил написать в личные сообщения:\n\n{private_text}"
            )
            if success:
                await message.reply_text(
                    f"✅ {user.first_name}, я отправил тебе сообщение в личку! 📨"
                )
            else:
                await message.reply_text(
                    f"❌ {user.first_name}, не могу отправить тебе личное сообщение. "
                    f"Возможно, ты меня заблокировал или не начинал диалог."
                )
            return
    
    # Проверяем, обращаются ли по имени (особенно когда много онлайн)
    is_mention = await mistral.is_mention(message.text)
    online_count = db.get_online_count(chat.id)
    
    # Определяем, нужно ли ответить
    should_respond = False
    
    # 1. В личке отвечаем всегда
    if is_private:
        should_respond = True
    
    # 2. В группе отвечаем если:
    #    - Обратились по имени
    #    - Много онлайн и это упоминание
    #    - Просто отвечаем на всё (как обычно)
    elif is_mention or (online_count >= ONLINE_THRESHOLD and is_mention):
        should_respond = True
        logger.info(f"Ответ по упоминанию {BOT_NAME} в чате {chat.id}")
    else:
        # Стандартная логика - отвечаем на всё (как и было)
        should_respond = True
    
    if not should_respond:
        return
    
    # Получаем контекст
    ai_messages = db.get_chat_messages_for_ai(chat.id, limit=5)
    ai_messages.append({
        "role": "user",
        "content": f"{username}: {message.text}"
    })
    
    # Генерируем ответ
    response, tokens_used = await mistral.generate_response(ai_messages, user.first_name, user_id, chat.id, is_private)
    
    if is_private and tokens_used > 0:
        db.add_token_usage_private(user_id, tokens_used)
        db.add_private_user(user_id)
    
    if response:
        if is_channel_post:
            response = f"📢 {response}"
        
        await message.reply_text(
            response, 
            reply_to_message_id=message.message_id
        )
        db.add_message(chat.id, context.bot.id, BOT_NAME, response, message.message_id, is_bot=True)
        db.add_response(user_id)
        
        if is_private:
            remaining = db.get_remaining_tokens_private(user_id)
            user_city = db.user_stats[user_id].get('city', 'Москва')
            logger.info(f"✅ [ЛИЧКА] {user.first_name} ({user_city}) | Токены: {tokens_used} | Осталось: {remaining}")
            
            if remaining < 100 and remaining > 0:
                await message.reply_text(
                    f"⚠️ Осталось всего {remaining} токенов на сегодня!",
                    reply_to_message_id=message.message_id
                )
        else:
            logger.info(f"✅ [ГРУППА] Ответ для {username} в чате {chat.id} (онлайн: {online_count})")
    else:
        fallback = f"{user.first_name}, извини, у меня временные трудности. Попробуй еще раз!"
        await message.reply_text(fallback, reply_to_message_id=message.message_id)
        logger.error(f"❌ Не удалось получить ответ от AI для {username}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                f"😔 У {BOT_FULL_NAME} временные трудности. Попробуйте позже!"
            )
    except:
        pass

# ==================== ЗАПУСК ====================

async def post_init(app: Application):
    """Действия после инициализации бота"""
    global FIRST_START
    
    if FIRST_START:
        logger.info(f"🚀 {BOT_FULL_NAME} версии {BOT_VERSION} запускается впервые...")
        await send_update_notifications(app)
        FIRST_START = False
    else:
        logger.info(f"🔄 {BOT_FULL_NAME} перезапущен")

def main():
    """Запуск бота"""
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    
    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("social", social_command))
    app.add_handler(CommandHandler("tokens", tokens_command))
    app.add_handler(CommandHandler("version", version_command))
    app.add_handler(CommandHandler("time", time_command))
    app.add_handler(CommandHandler("weather", weather_command))
    app.add_handler(CommandHandler("set_city", set_city_command))
    
    # Сообщения
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Ошибки
    app.add_error_handler(error_handler)
    
    print("=" * 60)
    print(f"🤖 {BOT_FULL_NAME} версии {BOT_VERSION} запущен!")
    print(f"📊 Токен: {TOKEN[:10]}...")
    print(f"👑 Админ ID: {ADMIN_ID}")
    print(f"🎯 Режим: ТОЛЬКО ОБЩЕНИЕ")
    print(f"❌ Видео не ищу")
    print(f"📨 Могу писать в личку из группы")
    print(f"👥 Реагирую на имя {BOT_NAME}")
    print(f"📊 Порог онлайн: {ONLINE_THRESHOLD}+ человек")
    print(f"💬 Личка: {DAILY_TOKEN_LIMIT} токенов/день")
    print(f"👥 Группы: БЕЗ ЛИМИТОВ")
    print("=" * 60)
    
    app.run_polling()

if __name__ == "__main__":
    main()