import os
import threading
import schedule
import time
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler,
    MessageHandler, Filters, CallbackContext, ConversationHandler
)

TOKEN = os.environ.get("BOT_TOKEN")

ISRAEL_AIRPORTS = {
    "TLV": "Тель-Авив (Бен-Гурион)",
    "ETH": "Эйлат",
    "HFA": "Хайфа",
    "VDA": "Эйлат (Рамон)",
}

POPULAR_DESTINATIONS = {
    "IST": ("Стамбул 🇹🇷", "istanbul"),
    "ATH": ("Афины 🇬🇷", "athens"),
    "FCO": ("Рим 🇮🇹", "rome"),
    "BCN": ("Барселона 🇪🇸", "barcelona"),
    "AMS": ("Амстердам 🇳🇱", "amsterdam"),
    "LHR": ("Лондон 🇬🇧", "london"),
    "CDG": ("Париж 🇫🇷", "paris"),
    "DXB": ("Дубай 🇦🇪", "dubai"),
    "PRG": ("Прага 🇨🇿", "prague"),
    "BUD": ("Будапешт 🇭🇺", "budapest"),
    "MXP": ("Милан 🇮🇹", "milan"),
    "MAD": ("Мадрид 🇪🇸", "madrid"),
}

# IATA -> название города для Booking
CITY_NAMES = {code: names[1] for code, names in POPULAR_DESTINATIONS.items()}

ORIGIN, DESTINATION, CHECKIN, CHECKOUT, HOTEL_CITY, HOTEL_CHECKIN, HOTEL_CHECKOUT = range(7)


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✈️ Найти авиабилеты", callback_data="flights")],
        [InlineKeyboardButton("🏨 Найти отели", callback_data="hotels")],
        [InlineKeyboardButton("✈️+🏨 Билеты и отели вместе", callback_data="both")],
        [InlineKeyboardButton("📍 Популярные направления", callback_data="popular")],
    ])


def show_main_menu(update: Update, text="Что ещё хотите найти?"):
    update.message.reply_text(text, reply_markup=main_menu_keyboard())


def make_google_flights_link(origin, destination, date_str):
    # date_str format: YYYY-MM-DD
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        date_formatted = d.strftime("%Y-%m-%d")
    except Exception:
        date_formatted = date_str
    return (
        f"https://www.google.com/travel/flights/search?"
        f"tfs=CBwQAhoeEgoyMDI1LTAxLTAxagcIARIDVExWcgcIARIDSVNU"
        f"&q=flights+from+{origin}+to+{destination}+on+{date_formatted}"
    )


def make_aviasales_link(origin, destination):
    # Ссылка на поиск без конкретной даты — покажет дешевые варианты на месяц
    return f"https://www.aviasales.com/search/{origin}1{destination}1"


def make_booking_link(city, checkin, checkout):
    # checkin/checkout format: YYYY-MM-DD
    return (
        f"https://www.booking.com/search.html"
        f"?ss={city}"
        f"&checkin={checkin}"
        f"&checkout={checkout}"
        f"&lang=ru"
        f"&selected_currency=ILS"
    )


def make_hotels_com_link(city, checkin, checkout):
    return (
        f"https://www.hotels.com/search.do"
        f"?q-destination={city}"
        f"&q-check-in={checkin}"
        f"&q-check-out={checkout}"
        f"&currency=ILS"
    )


def next_months_dates():
    """Возвращает даты на ближайшие 3 месяца для кнопок"""
    today = datetime.today()
    dates = []
    for i in range(1, 4):
        d = today + timedelta(days=30 * i)
        dates.append(d.strftime("%Y-%m-%d"))
    return dates


def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🇮🇱 Шалом! Я помогу найти дешёвые билеты и отели из Израиля.\n\n"
        "Отправляю прямые ссылки на Google Flights и Booking.com — "
        "вы сразу видите реальные цены в шекелях ₪\n\n"
        "Что хотите найти?",
        reply_markup=main_menu_keyboard()
    )


def button(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    if query.data == "flights":
        context.user_data["mode"] = "flights"
        keyboard = [
            [InlineKeyboardButton("✈️ TLV — Тель-Авив", callback_data="origin_TLV")],
            [InlineKeyboardButton("✈️ ETH — Эйлат", callback_data="origin_ETH")],
            [InlineKeyboardButton("✏️ Другой аэропорт", callback_data="origin_manual")],
        ]
        query.edit_message_text("Выберите аэропорт вылета:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "hotels":
        context.user_data["mode"] = "hotels"
        keyboard = []
        for code, (name, _) in list(POPULAR_DESTINATIONS.items())[:6]:
            keyboard.append([InlineKeyboardButton(name, callback_data=f"hcity_{code}")])
        keyboard.append([InlineKeyboardButton("✏️ Другой город", callback_data="hcity_manual")])
        query.edit_message_text("Выберите город для отеля:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "both":
        context.user_data["mode"] = "both"
        keyboard = [
            [InlineKeyboardButton("✈️ TLV — Тель-Авив", callback_data="origin_TLV")],
            [InlineKeyboardButton("✈️ ETH — Эйлат", callback_data="origin_ETH")],
            [InlineKeyboardButton("✏️ Другой аэропорт", callback_data="origin_manual")],
        ]
        query.edit_message_text("Выберите аэропорт вылета:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "popular":
        text = "📍 *Популярные направления из Израиля:*\n\n"
        for code, (name, _) in POPULAR_DESTINATIONS.items():
            text += f"• `{code}` — {name}\n"
        text += "\n*Аэропорты Израиля:*\n"
        for code, name in ISRAEL_AIRPORTS.items():
            text += f"• `{code}` — {name}\n"
        query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_menu")]
            ])
        )

    elif query.data == "back_to_menu":
        query.edit_message_text("Что хотите найти?", reply_markup=main_menu_keyboard())

    elif query.data.startswith("origin_"):
        origin = query.data.replace("origin_", "")
        if origin == "manual":
            query.edit_message_text("Введите IATA-код аэропорта вылета (например: TLV, ETH):")
            return ORIGIN
        context.user_data["origin"] = origin
        # Показать направления
        keyboard = []
        for code, (name, _) in POPULAR_DESTINATIONS.items():
            keyboard.append([InlineKeyboardButton(name, callback_data=f"dest_{code}")])
        keyboard.append([InlineKeyboardButton("✏️ Другой город", callback_data="dest_manual")])
        query.edit_message_text(
            f"Вылет из {ISRAEL_AIRPORTS.get(origin, origin)} ✅\n\nВыберите направление:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("dest_"):
        dest = query.data.replace("dest_", "")
        if dest == "manual":
            query.edit_message_text("Введите IATA-код города назначения (например: IST, BCN, LHR):")
            return DESTINATION
        context.user_data["destination"] = dest
        context.user_data["dest_city"] = CITY_NAMES.get(dest, dest.lower())
        # Предложить даты
        dates = next_months_dates()
        keyboard = [
            [InlineKeyboardButton(f"📅 {dates[0]}", callback_data=f"date_{dates[0]}")],
            [InlineKeyboardButton(f"📅 {dates[1]}", callback_data=f"date_{dates[1]}")],
            [InlineKeyboardButton(f"📅 {dates[2]}", callback_data=f"date_{dates[2]}")],
            [InlineKeyboardButton("✏️ Ввести дату вручную", callback_data="date_manual")],
            [InlineKeyboardButton("🔍 Найти без даты (все варианты)", callback_data="date_any")],
        ]
        dest_name = POPULAR_DESTINATIONS.get(dest, (dest, ""))[0]
        query.edit_message_text(
            f"Направление: {dest_name} ✅\n\nВыберите дату вылета:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("date_"):
        date_val = query.data.replace("date_", "")
        origin = context.user_data.get("origin", "TLV")
        destination = context.user_data.get("destination", "")
        dest_city = context.user_data.get("dest_city", destination.lower())
        mode = context.user_data.get("mode", "flights")

        if date_val == "manual":
            query.edit_message_text("Введите дату вылета в формате ГГГГ-ММ-ДД\nНапример: 2025-07-15")
            return CHECKIN
        elif date_val == "any":
            date_val = None

        _send_flight_results(query, origin, destination, dest_city, date_val, mode)

    elif query.data.startswith("hcity_"):
        city_code = query.data.replace("hcity_", "")
        if city_code == "manual":
            query.edit_message_text(
                "Введите название города на английском\n"
                "Например: london, paris, dubai, rome"
            )
            return HOTEL_CITY
        context.user_data["hotel_city"] = CITY_NAMES.get(city_code, city_code.lower())
        context.user_data["hotel_city_name"] = POPULAR_DESTINATIONS.get(city_code, (city_code, ""))[0]
        # Даты заезда
        dates = next_months_dates()
        keyboard = [
            [InlineKeyboardButton(f"📅 Заезд {dates[0]}", callback_data=f"hcheckin_{dates[0]}")],
            [InlineKeyboardButton(f"📅 Заезд {dates[1]}", callback_data=f"hcheckin_{dates[1]}")],
            [InlineKeyboardButton(f"📅 Заезд {dates[2]}", callback_data=f"hcheckin_{dates[2]}")],
            [InlineKeyboardButton("✏️ Ввести дату вручную", callback_data="hcheckin_manual")],
        ]
        city_name = context.user_data["hotel_city_name"]
        query.edit_message_text(
            f"Отель в {city_name} ✅\n\nВыберите дату заезда:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("hcheckin_"):
        val = query.data.replace("hcheckin_", "")
        if val == "manual":
            query.edit_message_text("Введите дату заезда в формате ГГГГ-ММ-ДД\nНапример: 2025-07-10")
            return HOTEL_CHECKIN
        context.user_data["hotel_checkin"] = val
        # Дата выезда — предлагаем +3, +5, +7 дней
        try:
            d = datetime.strptime(val, "%Y-%m-%d")
            co3 = (d + timedelta(days=3)).strftime("%Y-%m-%d")
            co5 = (d + timedelta(days=5)).strftime("%Y-%m-%d")
            co7 = (d + timedelta(days=7)).strftime("%Y-%m-%d")
        except Exception:
            co3 = co5 = co7 = ""
        keyboard = [
            [InlineKeyboardButton(f"3 ночи → {co3}", callback_data=f"hcheckout_{co3}")],
            [InlineKeyboardButton(f"5 ночей → {co5}", callback_data=f"hcheckout_{co5}")],
            [InlineKeyboardButton(f"7 ночей → {co7}", callback_data=f"hcheckout_{co7}")],
            [InlineKeyboardButton("✏️ Ввести дату выезда вручную", callback_data="hcheckout_manual")],
        ]
        query.edit_message_text(
            f"Заезд: {val} ✅\n\nСколько ночей?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("hcheckout_"):
        val = query.data.replace("hcheckout_", "")
        if val == "manual":
            query.edit_message_text("Введите дату выезда в формате ГГГГ-ММ-ДД\nНапример: 2025-07-17")
            return HOTEL_CHECKOUT
        context.user_data["hotel_checkout"] = val
        _send_hotel_results_from_context(query, context)


def _send_flight_results(query, origin, destination, dest_city, date_val, mode):
    dest_name = POPULAR_DESTINATIONS.get(destination, (destination, ""))[0] or destination

    aviasales = make_aviasales_link(origin, destination)

    if date_val:
        gflights = (
            f"https://www.google.com/travel/flights/search"
            f"?q=flights+from+{origin}+to+{destination}+on+{date_val}"
        )
        date_text = f"Дата: {date_val}\n"
    else:
        gflights = f"https://www.google.com/travel/flights/search?q=flights+from+{origin}+to+{destination}"
        date_text = "Дата: любая (выберите на сайте)\n"

    text = (
        f"✈️ *Билеты {origin} → {dest_name}*\n"
        f"{date_text}\n"
        f"Нажмите на ссылку — откроется поиск с реальными ценами в ₪:\n\n"
        f"🔵 [Google Flights — сравнить все авиакомпании]({gflights})\n\n"
        f"🟠 [Aviasales — часто дешевле]({aviasales})\n\n"
        f"💡 *Совет:* на Google Flights включите фильтр «Цена» и выберите валюту ILS (шекель)"
    )

    if mode == "both":
        query.edit_message_text(text, parse_mode="Markdown", disable_web_page_preview=True)
        # Сразу предложить отели
        keyboard = []
        if destination in POPULAR_DESTINATIONS:
            keyboard.append([InlineKeyboardButton(
                f"🏨 Теперь найти отели в {dest_name}",
                callback_data=f"hcity_{destination}"
            )])
        keyboard.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="back_to_menu")])
        query.message.reply_text("Хотите также найти отели?", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        query.edit_message_text(text, parse_mode="Markdown", disable_web_page_preview=True)
        query.message.reply_text("Что ещё хотите найти?", reply_markup=main_menu_keyboard())


def _send_hotel_results_from_context(query, context):
    city = context.user_data.get("hotel_city", "")
    city_name = context.user_data.get("hotel_city_name", city)
    checkin = context.user_data.get("hotel_checkin", "")
    checkout = context.user_data.get("hotel_checkout", "")

    booking = make_booking_link(city, checkin, checkout)
    hotels_com = make_hotels_com_link(city, checkin, checkout)

    text = (
        f"🏨 *Отели в {city_name}*\n"
        f"Заезд: {checkin} → Выезд: {checkout}\n\n"
        f"Нажмите — откроется поиск с реальными ценами в ₪:\n\n"
        f"🔵 [Booking.com — огромный выбор]({booking})\n\n"
        f"🟢 [Hotels.com — часто есть скидки]({hotels_com})\n\n"
        f"💡 *Совет:* на Booking.com в фильтрах выберите валюту ILS и сортировку «По цене»"
    )

    query.edit_message_text(text, parse_mode="Markdown", disable_web_page_preview=True)
    query.message.reply_text("Что ещё хотите найти?", reply_markup=main_menu_keyboard())


# --- Обработчики ручного ввода ---

def get_origin_manual(update: Update, context: CallbackContext):
    context.user_data["origin"] = update.message.text.upper().strip()
    keyboard = []
    for code, (name, _) in POPULAR_DESTINATIONS.items():
        keyboard.append([InlineKeyboardButton(name, callback_data=f"dest_{code}")])
    keyboard.append([InlineKeyboardButton("✏️ Другой город", callback_data="dest_manual")])
    update.message.reply_text("Выберите направление:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END


def get_destination_manual(update: Update, context: CallbackContext):
    dest = update.message.text.upper().strip()
    context.user_data["destination"] = dest
    context.user_data["dest_city"] = dest.lower()
    dates = next_months_dates()
    keyboard = [
        [InlineKeyboardButton(f"📅 {dates[0]}", callback_data=f"date_{dates[0]}")],
        [InlineKeyboardButton(f"📅 {dates[1]}", callback_data=f"date_{dates[1]}")],
        [InlineKeyboardButton(f"📅 {dates[2]}", callback_data=f"date_{dates[2]}")],
        [InlineKeyboardButton("🔍 Найти без даты", callback_data="date_any")],
    ]
    update.message.reply_text("Выберите дату вылета:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END


def get_checkin_manual(update: Update, context: CallbackContext):
    context.user_data["checkin"] = update.message.text.strip()
    origin = context.user_data.get("origin", "TLV")
    destination = context.user_data.get("destination", "")
    dest_city = context.user_data.get("dest_city", destination.lower())
    mode = context.user_data.get("mode", "flights")
    # Отправляем результаты
    _send_flight_results_message(update, origin, destination, dest_city, context.user_data["checkin"], mode)
    return ConversationHandler.END


def _send_flight_results_message(update, origin, destination, dest_city, date_val, mode):
    dest_name = POPULAR_DESTINATIONS.get(destination, (destination, ""))[0] or destination
    aviasales = make_aviasales_link(origin, destination)

    if date_val:
        gflights = f"https://www.google.com/travel/flights/search?q=flights+from+{origin}+to+{destination}+on+{date_val}"
        date_text = f"Дата: {date_val}\n"
    else:
        gflights = f"https://www.google.com/travel/flights/search?q=flights+from+{origin}+to+{destination}"
        date_text = "Дата: любая\n"

    text = (
        f"✈️ *Билеты {origin} → {dest_name}*\n"
        f"{date_text}\n"
        f"🔵 [Google Flights]({gflights})\n\n"
        f"🟠 [Aviasales]({aviasales})\n\n"
        f"💡 На Google Flights выберите валюту ILS"
    )
    update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)
    show_main_menu(update)


def get_hotel_city_manual(update: Update, context: CallbackContext):
    city = update.message.text.lower().strip()
    context.user_data["hotel_city"] = city
    context.user_data["hotel_city_name"] = city.capitalize()
    dates = next_months_dates()
    keyboard = [
        [InlineKeyboardButton(f"📅 Заезд {dates[0]}", callback_data=f"hcheckin_{dates[0]}")],
        [InlineKeyboardButton(f"📅 Заезд {dates[1]}", callback_data=f"hcheckin_{dates[1]}")],
        [InlineKeyboardButton(f"📅 Заезд {dates[2]}", callback_data=f"hcheckin_{dates[2]}")],
        [InlineKeyboardButton("✏️ Ввести дату вручную", callback_data="hcheckin_manual")],
    ]
    update.message.reply_text(
        f"Отель в {city.capitalize()} ✅\n\nВыберите дату заезда:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END


def get_hotel_checkin_manual(update: Update, context: CallbackContext):
    context.user_data["hotel_checkin"] = update.message.text.strip()
    update.message.reply_text("Введите дату выезда в формате ГГГГ-ММ-ДД\nНапример: 2025-07-17")
    return HOTEL_CHECKOUT


def get_hotel_checkout_manual(update: Update, context: CallbackContext):
    context.user_data["hotel_checkout"] = update.message.text.strip()
    city = context.user_data.get("hotel_city", "")
    city_name = context.user_data.get("hotel_city_name", city)
    checkin = context.user_data.get("hotel_checkin", "")
    checkout = context.user_data.get("hotel_checkout", "")

    booking = make_booking_link(city, checkin, checkout)
    hotels_com = make_hotels_com_link(city, checkin, checkout)

    text = (
        f"🏨 *Отели в {city_name}*\n"
        f"Заезд: {checkin} → Выезд: {checkout}\n\n"
        f"🔵 [Booking.com]({booking})\n\n"
        f"🟢 [Hotels.com]({hotels_com})\n\n"
        f"💡 На Booking.com выберите валюту ILS"
    )
    update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)
    show_main_menu(update)
    return ConversationHandler.END


def cancel(update: Update, context: CallbackContext):
    show_main_menu(update, "Отменено. Что хотите найти?")
    return ConversationHandler.END


def popular_cmd(update: Update, context: CallbackContext):
    text = "📍 *Популярные направления из Израиля:*\n\n"
    for code, (name, _) in POPULAR_DESTINATIONS.items():
        text += f"• `{code}` — {name}\n"
    text += "\n*Аэропорты Израиля:*\n"
    for code, name in ISRAEL_AIRPORTS.items():
        text += f"• `{code}` — {name}\n"
    update.message.reply_text(text, parse_mode="Markdown")
    show_main_menu(update)


def help_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(
        "📖 *Как пользоваться ботом:*\n\n"
        "1. Нажмите «✈️ Найти авиабилеты» или «🏨 Найти отели»\n"
        "2. Выберите аэропорт и направление\n"
        "3. Бот даст ссылки на Google Flights и Booking.com\n"
        "4. Откройте ссылку — там реальные цены в ₪\n\n"
        "Команды:\n"
        "/start — главное меню\n"
        "/cancel — отменить\n"
        "/help — справка",
        parse_mode="Markdown"
    )
    show_main_menu(update)


def main():
    updater = Updater(TOKEN)
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button)],
        states={
            ORIGIN: [MessageHandler(Filters.text & ~Filters.command, get_origin_manual)],
            DESTINATION: [MessageHandler(Filters.text & ~Filters.command, get_destination_manual)],
            CHECKIN: [MessageHandler(Filters.text & ~Filters.command, get_checkin_manual)],
            HOTEL_CITY: [MessageHandler(Filters.text & ~Filters.command, get_hotel_city_manual)],
            HOTEL_CHECKIN: [MessageHandler(Filters.text & ~Filters.command, get_hotel_checkin_manual)],
            HOTEL_CHECKOUT: [MessageHandler(Filters.text & ~Filters.command, get_hotel_checkout_manual)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("popular", popular_cmd))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(conv_handler)

    print("🤖 Бот запущен!")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
