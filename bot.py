import os
import requests
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
TP_TOKEN = os.environ.get("TP_TOKEN")

ISRAEL_AIRPORTS = {
    "TLV": "Тель-Авив (Бен-Гурион)",
    "ETH": "Эйлат",
}

# key: (display name, API code, booking city)
POPULAR_DESTINATIONS = {
    "IST": ("Стамбул 🇹🇷",  "IST", "istanbul"),
    "ATH": ("Афины 🇬🇷",    "ATH", "athens"),
    "FCO": ("Рим 🇮🇹",      "ROM", "rome"),
    "BCN": ("Барселона 🇪🇸", "BCN", "barcelona"),
    "AMS": ("Амстердам 🇳🇱", "AMS", "amsterdam"),
    "LHR": ("Лондон 🇬🇧",   "LON", "london"),
    "CDG": ("Париж 🇫🇷",    "PAR", "paris"),
    "DXB": ("Дубай 🇦🇪",    "DXB", "dubai"),
    "PRG": ("Прага 🇨🇿",    "PRG", "prague"),
    "BUD": ("Будапешт 🇭🇺", "BUD", "budapest"),
    "MXP": ("Милан 🇮🇹",    "MIL", "milan"),
    "MAD": ("Мадрид 🇪🇸",   "MAD", "madrid"),
}

ORIGIN, DESTINATION, HOTEL_CITY, HOTEL_CHECKIN, HOTEL_CHECKOUT = range(5)
user_searches = {}


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✈️ Найти авиабилеты", callback_data="flights")],
        [InlineKeyboardButton("🏨 Найти отели", callback_data="hotels")],
        [InlineKeyboardButton("✈️+🏨 Билеты и отели вместе", callback_data="both")],
        [InlineKeyboardButton("📍 Популярные направления", callback_data="popular")],
    ])


def show_main_menu(update, text="Что ещё хотите найти?"):
    update.message.reply_text(text, reply_markup=main_menu_keyboard())


def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🇮🇱 Шалом! Я ищу дешёвые билеты и отели из Израиля.\n\n"
        "Показываю реальные цены в шекелях ₪ прямо в чате.\n\n"
        "Что хотите найти?",
        reply_markup=main_menu_keyboard()
    )


def button(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    if query.data in ("flights", "both"):
        context.user_data["mode"] = query.data
        query.edit_message_text(
            "Выберите аэропорт вылета:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✈️ TLV — Тель-Авив", callback_data="origin_TLV")],
                [InlineKeyboardButton("✈️ ETH — Эйлат",     callback_data="origin_ETH")],
                [InlineKeyboardButton("✏️ Другой",          callback_data="origin_manual")],
            ])
        )

    elif query.data == "hotels":
        context.user_data["mode"] = "hotels"
        keyboard = [[InlineKeyboardButton(v[0], callback_data=f"hcity_{k}")]
                    for k, v in list(POPULAR_DESTINATIONS.items())[:6]]
        keyboard.append([InlineKeyboardButton("✏️ Другой город", callback_data="hcity_manual")])
        query.edit_message_text("Выберите город:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "popular":
        text = "📍 *Популярные направления из Израиля:*\n\n"
        for _, (name, _, _) in POPULAR_DESTINATIONS.items():
            text += f"• {name}\n"
        query.edit_message_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_menu")]
            ]))

    elif query.data == "back_to_menu":
        query.edit_message_text("Что хотите найти?", reply_markup=main_menu_keyboard())

    elif query.data.startswith("origin_"):
        origin = query.data[7:]
        if origin == "manual":
            query.edit_message_text("Введите IATA-код аэропорта вылета (например: TLV):")
            return ORIGIN
        context.user_data["origin"] = origin
        keyboard = [[InlineKeyboardButton(v[0], callback_data=f"dest_{k}")]
                    for k, v in POPULAR_DESTINATIONS.items()]
        keyboard.append([InlineKeyboardButton("✏️ Другой город", callback_data="dest_manual")])
        query.edit_message_text(
            f"Вылет из {ISRAEL_AIRPORTS.get(origin, origin)} ✅\n\nВыберите направление:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("dest_"):
        dest_key = query.data[5:]
        if dest_key == "manual":
            query.edit_message_text("Введите IATA-код города (например: IST, LON, BCN):")
            return DESTINATION
        info = POPULAR_DESTINATIONS[dest_key]
        context.user_data.update({
            "dest_key": dest_key, "dest_api": info[1],
            "dest_name": info[0], "dest_city": info[2]
        })
        query.edit_message_text(f"🔍 Ищу лучшие билеты → {info[0]}...\nПроверяю несколько месяцев, подождите!")
        _do_flight_search(query, context)

    elif query.data.startswith("hcity_"):
        code = query.data[6:]
        if code == "manual":
            query.edit_message_text("Введите название города на английском (например: london):")
            return HOTEL_CITY
        info = POPULAR_DESTINATIONS[code]
        context.user_data.update({"hotel_city": info[2], "hotel_city_name": info[0]})
        _ask_checkin(query)

    elif query.data.startswith("hcheckin_"):
        val = query.data[9:]
        if val == "manual":
            query.edit_message_text("Введите дату заезда (ГГГГ-ММ-ДД):")
            return HOTEL_CHECKIN
        context.user_data["hotel_checkin"] = val
        _ask_checkout(query, val)

    elif query.data.startswith("hcheckout_"):
        val = query.data[10:]
        if val == "manual":
            query.edit_message_text("Введите дату выезда (ГГГГ-ММ-ДД):")
            return HOTEL_CHECKOUT
        context.user_data["hotel_checkout"] = val
        _send_hotel_links(query, context)

    elif query.data.startswith("also_hotel_"):
        key = query.data[11:]
        info = POPULAR_DESTINATIONS.get(key)
        if info:
            context.user_data.update({"hotel_city": info[2], "hotel_city_name": info[0]})
            _ask_checkin(query)


def _next_months():
    t = datetime.today()
    return [(t + timedelta(days=30 * i)).strftime("%Y-%m-%d") for i in range(1, 4)]


def _ask_checkin(query):
    dates = _next_months()
    keyboard = [[InlineKeyboardButton(f"📅 {d}", callback_data=f"hcheckin_{d}")] for d in dates]
    keyboard.append([InlineKeyboardButton("✏️ Ввести вручную", callback_data="hcheckin_manual")])
    query.edit_message_text("Выберите дату заезда:", reply_markup=InlineKeyboardMarkup(keyboard))


def _ask_checkout(query, checkin):
    try:
        d = datetime.strptime(checkin, "%Y-%m-%d")
        options = [(3, "ночи"), (5, "ночей"), (7, "ночей"), (10, "ночей")]
        keyboard = []
        for n, label in options:
            co = (d + timedelta(days=n)).strftime("%Y-%m-%d")
            keyboard.append([InlineKeyboardButton(f"{n} {label} → {co}", callback_data=f"hcheckout_{co}")])
        keyboard.append([InlineKeyboardButton("✏️ Ввести вручную", callback_data="hcheckout_manual")])
    except Exception:
        keyboard = [[InlineKeyboardButton("✏️ Ввести вручную", callback_data="hcheckout_manual")]]
    query.edit_message_text(
        f"Заезд: {checkin} ✅\n\nСколько ночей?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def _send_hotel_links(query, context):
    city = context.user_data.get("hotel_city", "")
    city_name = context.user_data.get("hotel_city_name", city)
    checkin = context.user_data.get("hotel_checkin", "")
    checkout = context.user_data.get("hotel_checkout", "")
    booking = (f"https://www.booking.com/search.html?ss={city}"
               f"&checkin={checkin}&checkout={checkout}&lang=ru&selected_currency=ILS&order=price")
    text = (f"🏨 *Отели в {city_name}*\n"
            f"Заезд: {checkin} → Выезд: {checkout}\n\n"
            f"🔵 [Booking.com — по цене ↑]({booking})\n\n"
            f"💡 Ссылка уже с вашими датами и ценами в ₪")
    query.edit_message_text(text, parse_mode="Markdown", disable_web_page_preview=True)
    query.message.reply_text("Что ещё хотите найти?", reply_markup=main_menu_keyboard())


def _search_api_multi(origin, destination):
    """
    Запрашиваем API за несколько месяцев вперёд чтобы получить больше вариантов.
    Возвращаем до 8 самых дешёвых уникальных результатов.
    """
    all_results = []
    today = datetime.today()

    # Запрашиваем 4 разных периода
    periods = []
    for i in range(4):
        d = today + timedelta(days=30 * i)
        periods.append(d.strftime("%Y-%m"))

    seen_dates = set()

    for period in periods:
        try:
            r = requests.get(
                "https://api.travelpayouts.com/v2/prices/latest",
                params={
                    "origin": origin,
                    "destination": destination,
                    "currency": "ils",
                    "period_type": "month",
                    "beginning_of_period": period + "-01",
                    "one_way": "false",
                    "token": TP_TOKEN,
                    "limit": 30,
                },
                timeout=10
            )
            data = r.json().get("data", [])
            for item in data:
                date_key = item.get("depart_date", "")
                if date_key and date_key not in seen_dates:
                    seen_dates.add(date_key)
                    all_results.append(item)
        except Exception as e:
            print(f"API error period {period}: {e}")

    # Также запросим cheapest (без периода) для максимального охвата
    try:
        r = requests.get(
            "https://api.travelpayouts.com/v2/prices/cheap",
            params={
                "origin": origin,
                "destination": destination,
                "currency": "ils",
                "token": TP_TOKEN,
            },
            timeout=10
        )
        data = r.json().get("data", {})
        if isinstance(data, dict):
            for dest_key, months in data.items():
                if isinstance(months, dict):
                    for month_key, flight in months.items():
                        if isinstance(flight, dict):
                            date_key = flight.get("depart_date", "")
                            if date_key and date_key not in seen_dates:
                                seen_dates.add(date_key)
                                flight["origin"] = origin
                                flight["destination"] = destination
                                all_results.append(flight)
    except Exception as e:
        print(f"Cheap API error: {e}")

    # Сортируем по цене и возвращаем топ-8
    all_results.sort(key=lambda x: x.get("value", 9999999))
    return all_results[:8]


def _do_flight_search(query, context):
    origin   = context.user_data.get("origin", "TLV")
    dest_api = context.user_data.get("dest_api", "")
    dest_name= context.user_data.get("dest_name", dest_api)
    dest_key = context.user_data.get("dest_key", "")
    mode     = context.user_data.get("mode", "flights")

    results  = _search_api_multi(origin, dest_api)
    aviasales= f"https://www.aviasales.com/search/{origin}1{dest_api}1"
    gflights = f"https://www.google.com/travel/flights/search?q=flights+from+{origin}+to+{dest_api}"

    if results:
        user_searches[query.message.chat_id] = {
            "origin": origin, "dest_api": dest_api,
            "dest_name": dest_name, "max_price": results[0]["value"] * 2
        }

        text = f"✈️ *{origin} → {dest_name}*\nТоп предложений по цене:\n\n"
        for i, r in enumerate(results, 1):
            price   = r.get("value", "?")
            depart  = r.get("depart_date", "?")
            ret     = r.get("return_date", "")
            airline = r.get("gate", r.get("airline", ""))
            changes = r.get("number_of_changes", r.get("transfers", 1))
            stops   = "✅ прямой" if changes == 0 else f"🔄 {changes} пересадка"
            ret_txt = f" ↩️{ret}" if ret else ""
            text += f"{i}. 📅 {depart}{ret_txt}  💰 *{price}₪*\n   {airline} · {stops}\n\n"

        text += f"🛒 [Купить на Aviasales]({aviasales}) · [Google Flights]({gflights})"
    else:
        text = (f"✈️ *{origin} → {dest_name}*\n\n"
                f"Кешированных цен пока нет.\n\n"
                f"🔵 [Aviasales]({aviasales})\n"
                f"🟠 [Google Flights]({gflights})")

    query.edit_message_text(text, parse_mode="Markdown", disable_web_page_preview=True)

    if mode == "both" and dest_key in POPULAR_DESTINATIONS:
        query.message.reply_text(
            f"Найти отели в {dest_name}?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏨 Да, найти отели", callback_data=f"also_hotel_{dest_key}")],
                [InlineKeyboardButton("⬅️ Главное меню",    callback_data="back_to_menu")],
            ])
        )
    else:
        query.message.reply_text("Что ещё хотите найти?", reply_markup=main_menu_keyboard())


# ---- Manual text handlers ----

def get_origin_manual(update: Update, context: CallbackContext):
    context.user_data["origin"] = update.message.text.upper().strip()
    keyboard = [[InlineKeyboardButton(v[0], callback_data=f"dest_{k}")]
                for k, v in POPULAR_DESTINATIONS.items()]
    update.message.reply_text("Выберите направление:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END


def get_destination_manual(update: Update, context: CallbackContext):
    dest = update.message.text.upper().strip()
    context.user_data.update({"dest_api": dest, "dest_name": dest, "dest_city": dest.lower(), "dest_key": ""})
    origin = context.user_data.get("origin", "TLV")
    update.message.reply_text(f"🔍 Ищу лучшие билеты {origin} → {dest}...\nПроверяю несколько месяцев!")
    results  = _search_api_multi(origin, dest)
    aviasales= f"https://www.aviasales.com/search/{origin}1{dest}1"
    gflights = f"https://www.google.com/travel/flights/search?q=flights+from+{origin}+to+{dest}"
    if results:
        text = f"✈️ *{origin} → {dest}*\nТоп предложений:\n\n"
        for i, r in enumerate(results, 1):
            price = r.get("value","?"); depart = r.get("depart_date","?")
            ret = r.get("return_date",""); airline = r.get("gate", r.get("airline",""))
            changes = r.get("number_of_changes", r.get("transfers",1))
            stops = "✅ прямой" if changes == 0 else f"🔄 {changes} пересадка"
            ret_txt = f" ↩️{ret}" if ret else ""
            text += f"{i}. 📅 {depart}{ret_txt}  💰 *{price}₪*\n   {airline} · {stops}\n\n"
        text += f"🛒 [Aviasales]({aviasales}) · [Google Flights]({gflights})"
    else:
        text = f"Цен нет в кеше.\n\n[Aviasales]({aviasales})\n[Google Flights]({gflights})"
    update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)
    show_main_menu(update)
    return ConversationHandler.END


def get_hotel_city_manual(update: Update, context: CallbackContext):
    city = update.message.text.lower().strip()
    context.user_data.update({"hotel_city": city, "hotel_city_name": city.capitalize()})
    dates = _next_months()
    keyboard = [[InlineKeyboardButton(f"📅 {d}", callback_data=f"hcheckin_{d}")] for d in dates]
    keyboard.append([InlineKeyboardButton("✏️ Ввести вручную", callback_data="hcheckin_manual")])
    update.message.reply_text("Выберите дату заезда:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END


def get_hotel_checkin_manual(update: Update, context: CallbackContext):
    context.user_data["hotel_checkin"] = update.message.text.strip()
    update.message.reply_text("Введите дату выезда (ГГГГ-ММ-ДД):")
    return HOTEL_CHECKOUT


def get_hotel_checkout_manual(update: Update, context: CallbackContext):
    context.user_data["hotel_checkout"] = update.message.text.strip()
    city = context.user_data.get("hotel_city","")
    city_name = context.user_data.get("hotel_city_name", city)
    checkin = context.user_data.get("hotel_checkin","")
    checkout = context.user_data.get("hotel_checkout","")
    booking = (f"https://www.booking.com/search.html?ss={city}"
               f"&checkin={checkin}&checkout={checkout}&lang=ru&selected_currency=ILS&order=price")
    text = (f"🏨 *Отели в {city_name}*\nЗаезд: {checkin} → Выезд: {checkout}\n\n"
            f"🔵 [Booking.com (по цене ↑)]({booking})")
    update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)
    show_main_menu(update)
    return ConversationHandler.END


def auto_check():
    from telegram import Bot
    bot = Bot(token=TOKEN)
    for chat_id, s in user_searches.items():
        try:
            results = _search_api_multi(s["origin"], s["dest_api"])
            if results and results[0]["value"] < s.get("max_price", 9999):
                r = results[0]
                aviasales = f"https://www.aviasales.com/search/{s['origin']}1{s['dest_api']}1"
                bot.send_message(
                    chat_id=chat_id, parse_mode="Markdown",
                    text=(f"🔔 *Авто-поиск: новая цена!*\n"
                          f"✈️ {s['origin']} → {s['dest_name']}\n"
                          f"💰 *{r['value']}₪* · {r.get('gate','')} · {r.get('depart_date','')}\n\n"
                          f"[Купить на Aviasales]({aviasales})")
                )
        except Exception as e:
            print(f"auto_check error: {e}")


def run_schedule():
    schedule.every(6).hours.do(auto_check)
    while True:
        schedule.run_pending()
        time.sleep(60)


def cancel(update: Update, context: CallbackContext):
    show_main_menu(update, "Отменено.")
    return ConversationHandler.END


def popular_cmd(update: Update, context: CallbackContext):
    text = "📍 *Популярные направления:*\n\n"
    for _, (name, _, _) in POPULAR_DESTINATIONS.items():
        text += f"• {name}\n"
    update.message.reply_text(text, parse_mode="Markdown")
    show_main_menu(update)


def help_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(
        "📖 *Как пользоваться:*\n\n"
        "1. Нажмите «✈️ Найти авиабилеты»\n"
        "2. Выберите аэропорт и направление\n"
        "3. Бот покажет до 8 вариантов с реальными ценами в ₪\n"
        "4. Нажмите ссылку для покупки\n\n"
        "/start — меню  |  /cancel — отмена",
        parse_mode="Markdown"
    )
    show_main_menu(update)


def main():
    updater = Updater(TOKEN)
    dp = updater.dispatcher

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button)],
        states={
            ORIGIN:        [MessageHandler(Filters.text & ~Filters.command, get_origin_manual)],
            DESTINATION:   [MessageHandler(Filters.text & ~Filters.command, get_destination_manual)],
            HOTEL_CITY:    [MessageHandler(Filters.text & ~Filters.command, get_hotel_city_manual)],
            HOTEL_CHECKIN: [MessageHandler(Filters.text & ~Filters.command, get_hotel_checkin_manual)],
            HOTEL_CHECKOUT:[MessageHandler(Filters.text & ~Filters.command, get_hotel_checkout_manual)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("popular", popular_cmd))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(conv)

    threading.Thread(target=run_schedule, daemon=True).start()
    print("🤖 Бот запущен!")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
