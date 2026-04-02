import os
import requests
import schedule
import time
import threading
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler,
    MessageHandler, Filters, CallbackContext, ConversationHandler
)

TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
TP_TOKEN = os.environ.get("TP_TOKEN")

# Израильские аэропорты
ISRAEL_AIRPORTS = {
    "TLV": "Тель-Авив (Бен-Гурион)",
    "ETH": "Эйлат",
    "HFA": "Хайфа",
    "VDA": "Эйлат (Рамон)",
}

# Популярные направления из Израиля
POPULAR_DESTINATIONS = {
    "IST": "Стамбул 🇹🇷",
    "ATH": "Афины 🇬🇷",
    "FCO": "Рим 🇮🇹",
    "BCN": "Барселона 🇪🇸",
    "AMS": "Амстердам 🇳🇱",
    "LHR": "Лондон 🇬🇧",
    "CDG": "Париж 🇫🇷",
    "DXB": "Дубай 🇦🇪",
    "PRG": "Прага 🇨🇿",
    "BUD": "Будапешт 🇭🇺",
}

ORIGIN, DESTINATION, MAX_PRICE, HOTEL_CITY, HOTEL_PRICE = range(5)

user_searches = {}


def start(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("✈️ Найти авиабилеты", callback_data="flights")],
        [InlineKeyboardButton("🏨 Найти отели", callback_data="hotels")],
        [InlineKeyboardButton("⏰ Включить авто-поиск 24/7", callback_data="auto")],
        [InlineKeyboardButton("📍 Популярные направления", callback_data="popular")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(
        "🇮🇱 Шалом! Я ищу дешёвые билеты и отели из Израиля.\n\n"
        "Все цены в шекелях (₪). Вылет по умолчанию из Тель-Авива (TLV).\n\n"
        "Что хотите найти?",
        reply_markup=reply_markup
    )


def button(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    if query.data == "flights":
        keyboard = [
            [InlineKeyboardButton("✈️ TLV — Тель-Авив", callback_data="origin_TLV")],
            [InlineKeyboardButton("✈️ ETH — Эйлат", callback_data="origin_ETH")],
            [InlineKeyboardButton("✏️ Ввести вручную", callback_data="origin_manual")],
        ]
        query.edit_message_text(
            "Выберите аэропорт вылета:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "hotels":
        query.edit_message_text(
            "🏨 Введите название города для поиска отеля\n"
            "(на английском, например: istanbul, paris, dubai, rome):"
        )
        return HOTEL_CITY

    elif query.data == "auto":
        query.edit_message_text(
            "⏰ Авто-поиск включён!\n\n"
            "Каждые 6 часов я буду проверять билеты и отели по вашим последним запросам "
            "и сразу сообщать о дешёвых находках 🔔\n\n"
            "Сначала сделайте хотя бы один поиск билетов, чтобы я знал ваш маршрут."
        )

    elif query.data == "popular":
        text = "📍 *Популярные направления из Израиля:*\n\n"
        for code, name in POPULAR_DESTINATIONS.items():
            text += f"• `{code}` — {name}\n"
        text += "\nИспользуйте эти коды при поиске билетов."
        query.edit_message_text(text, parse_mode="Markdown")

    elif query.data.startswith("origin_"):
        origin = query.data.replace("origin_", "")
        if origin == "manual":
            query.edit_message_text(
                "Введите IATA-код аэропорта вылета\n"
                "(например: TLV — Тель-Авив, ETH — Эйлат):"
            )
        else:
            context.user_data["origin"] = origin
            keyboard = []
            for code, name in POPULAR_DESTINATIONS.items():
                keyboard.append([InlineKeyboardButton(f"{name} ({code})", callback_data=f"dest_{code}")])
            keyboard.append([InlineKeyboardButton("✏️ Ввести город вручную", callback_data="dest_manual")])
            query.edit_message_text(
                f"Вылет из {ISRAEL_AIRPORTS.get(origin, origin)} ✅\n\n"
                "Выберите направление:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    elif query.data.startswith("dest_"):
        dest = query.data.replace("dest_", "")
        if dest == "manual":
            query.edit_message_text("Введите IATA-код города назначения (например: IST, BCN, FCO):")
            return DESTINATION
        else:
            context.user_data["destination"] = dest
            query.edit_message_text(
                f"Направление: {POPULAR_DESTINATIONS.get(dest, dest)} ✅\n\n"
                "Введите максимальную цену билета в шекелях ₪\n"
                "(например: 500 — это примерно бюджетный перелёт):"
            )
            return MAX_PRICE


def get_origin(update: Update, context: CallbackContext):
    context.user_data["origin"] = update.message.text.upper().strip()
    update.message.reply_text(
        "Введите IATA-код города назначения\n"
        "Например: IST (Стамбул), ATH (Афины), BCN (Барселона)\n\n"
        "Напишите /popular чтобы увидеть список популярных кодов."
    )
    return DESTINATION


def get_destination(update: Update, context: CallbackContext):
    context.user_data["destination"] = update.message.text.upper().strip()
    update.message.reply_text(
        "Введите максимальную цену в шекелях ₪\n"
        "Например: 400 или 800"
    )
    return MAX_PRICE


def get_max_price(update: Update, context: CallbackContext):
    try:
        max_price = int(update.message.text.strip())
        context.user_data["max_price"] = max_price
        origin = context.user_data.get("origin", "TLV")
        destination = context.user_data["destination"]

        user_searches[update.message.chat_id] = {
            "origin": origin,
            "destination": destination,
            "max_price": max_price
        }

        update.message.reply_text(
            f"🔍 Ищу билеты {origin} → {destination} до {max_price}₪...\nПодождите немного!"
        )

        results = search_flights(origin, destination, max_price)

        if results:
            update.message.reply_text(f"✅ Найдено {len(results[:5])} вариантов:")
            for r in results[:5]:
                depart = r.get("depart_date", "").replace("-", "")
                link = f"https://www.aviasales.com/search/{r['origin']}{depart}1{r['destination']}1"
                update.message.reply_text(
                    f"✈️ *Билет найден!*\n"
                    f"Маршрут: {r['origin']} → {r['destination']}\n"
                    f"Дата: {r.get('depart_date', 'уточните на сайте')}\n"
                    f"Цена: *{r['value']}₪*\n"
                    f"[🔗 Купить билет]({link})",
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
        else:
            update.message.reply_text(
                f"😔 Билетов дешевле {max_price}₪ не найдено.\n\n"
                f"Попробуйте:\n"
                f"• Увеличить бюджет\n"
                f"• Поменять даты\n"
                f"• Выбрать другое направление"
            )
    except ValueError:
        update.message.reply_text("Пожалуйста, введите только число. Например: 500")
        return MAX_PRICE

    return ConversationHandler.END


def get_hotel_city(update: Update, context: CallbackContext):
    context.user_data["hotel_city"] = update.message.text.lower().strip()
    update.message.reply_text(
        "Введите максимальную цену за ночь в шекелях ₪\n"
        "Например: 300 или 600"
    )
    return HOTEL_PRICE


def get_hotel_price(update: Update, context: CallbackContext):
    try:
        max_price = int(update.message.text.strip())
        city = context.user_data["hotel_city"]

        update.message.reply_text(f"🔍 Ищу отели в {city} до {max_price}₪ за ночь...")

        results = search_hotels(city, max_price)

        if results:
            update.message.reply_text(f"✅ Найдено отелей: {len(results[:5])}")
            for h in results[:5]:
                name = h.get("hotelName", "Без названия")
                price = h.get("priceFrom", "?")
                stars = int(h.get("stars", 0))
                stars_str = "⭐" * stars if stars > 0 else "Без звёзд"
                link = f"https://hotellook.com/search/{city}"
                update.message.reply_text(
                    f"🏨 *{name}*\n"
                    f"{stars_str}\n"
                    f"Цена от: *{price}₪ за ночь*\n"
                    f"[🔗 Смотреть и забронировать]({link})",
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
        else:
            update.message.reply_text(
                f"😔 Отелей дешевле {max_price}₪ за ночь в {city} не найдено.\n"
                f"Попробуйте увеличить бюджет или выбрать другой город."
            )
    except ValueError:
        update.message.reply_text("Пожалуйста, введите только число. Например: 400")
        return HOTEL_PRICE

    return ConversationHandler.END


def search_flights(origin, destination, max_price):
    try:
        url = "https://api.travelpayouts.com/v2/prices/latest"
        params = {
            "origin": origin,
            "destination": destination,
            "currency": "ils",       # Израильский шекель
            "period_type": "month",
            "one_way": "true",
            "token": TP_TOKEN,
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        return [f for f in data.get("data", []) if f.get("value", 9999999) <= max_price]
    except Exception as e:
        print(f"Ошибка поиска билетов: {e}")
        return []


def search_hotels(city, max_price):
    try:
        url = "https://engine.hotellook.com/api/v2/cache.json"
        params = {
            "location": city,
            "currency": "ils",       # Израильский шекель
            "token": TP_TOKEN,
            "limit": 10,
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if isinstance(data, list):
            return [h for h in data if h.get("priceFrom", 9999999) <= max_price]
        return []
    except Exception as e:
        print(f"Ошибка поиска отелей: {e}")
        return []


def popular(update: Update, context: CallbackContext):
    text = "📍 *Популярные направления из Израиля:*\n\n"
    for code, name in POPULAR_DESTINATIONS.items():
        text += f"• `{code}` — {name}\n"
    text += "\n*Аэропорты Израиля:*\n"
    for code, name in ISRAEL_AIRPORTS.items():
        text += f"• `{code}` — {name}\n"
    update.message.reply_text(text, parse_mode="Markdown")


def auto_check():
    from telegram import Bot
    bot = Bot(token=TOKEN)
    for chat_id, search in user_searches.items():
        try:
            results = search_flights(
                search["origin"],
                search["destination"],
                search["max_price"]
            )
            if results:
                r = results[0]
                bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🔔 *Авто-поиск сработал!*\n"
                        f"✈️ {search['origin']} → {search['destination']}\n"
                        f"Цена: *{r['value']}₪* (ваш лимит: {search['max_price']}₪)\n"
                        f"Дата: {r.get('depart_date', '?')}"
                    ),
                    parse_mode="Markdown"
                )
        except Exception as e:
            print(f"Ошибка авто-поиска: {e}")


def run_schedule():
    schedule.every(6).hours.do(auto_check)
    while True:
        schedule.run_pending()
        time.sleep(60)


def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Отменено. Напишите /start чтобы начать заново.")
    return ConversationHandler.END


def help_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(
        "📖 *Команды бота:*\n\n"
        "/start — главное меню\n"
        "/popular — коды аэропортов и направлений\n"
        "/cancel — отменить текущий поиск\n"
        "/help — эта справка\n\n"
        "💡 *Советы:*\n"
        "• TLV = Тель-Авив Бен-Гурион\n"
        "• Цены в шекелях ₪\n"
        "• Авто-поиск работает каждые 6 часов",
        parse_mode="Markdown"
    )


def main():
    updater = Updater(TOKEN)
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button)],
        states={
            ORIGIN: [MessageHandler(Filters.text & ~Filters.command, get_origin)],
            DESTINATION: [MessageHandler(Filters.text & ~Filters.command, get_destination)],
            MAX_PRICE: [MessageHandler(Filters.text & ~Filters.command, get_max_price)],
            HOTEL_CITY: [MessageHandler(Filters.text & ~Filters.command, get_hotel_city)],
            HOTEL_PRICE: [MessageHandler(Filters.text & ~Filters.command, get_hotel_price)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("popular", popular))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(conv_handler)

    # Запуск авто-поиска в фоне
    t = threading.Thread(target=run_schedule, daemon=True)
    t.start()

    print("🤖 Бот запущен! Нажмите Ctrl+C для остановки.")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
