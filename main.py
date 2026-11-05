import os
import sqlite3
import json
import telebot
from datetime import datetime

TOKEN = os.environ["TOKEN"]
bot = telebot.TeleBot(TOKEN)

db = sqlite3.connect("loads.db", check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS loads(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT, date TEXT,
    driver TEXT, phone TEXT, company TEXT, car TEXT, trailer TEXT,
    clients TEXT,
    incomes_expr TEXT, income REAL,
    transport REAL, loaders_expr TEXT, loaders REAL, unload REAL, staff REAL,
    expenses REAL, profit REAL, people INTEGER, per_person REAL,
    payouts TEXT, bank REAL)""")
db.commit()

st = {}  # состояние опроса по chat_id

SEP = "➖➖➖➖➖"

# ---------- утилиты ----------

def fnum(s):
    # '7,7+0,7' -> 8.4 ; '200.000' -> 200.0 (всё в тыс. руб.)
    total = 0.0
    for part in str(s).replace(" ", "").split("+"):
        if part:
            total += float(part.replace(",", "."))
    return total

def fmt(v):
    # 300 -> '300', 69.1 -> '69,1', 200000 -> '200.000'
    v = round(float(v), 2)
    if abs(v - round(v)) < 0.005:
        return f"{int(round(v)):,}".replace(",", ".")
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    ip, dec = s.split(".")
    return f"{int(ip):,}".replace(",", ".") + "," + dec

def today():
    return datetime.now().strftime("%d.%m.%Y")

def next_number():
    row = db.execute("SELECT number FROM loads ORDER BY id DESC LIMIT 1").fetchone()
    if row and "/" in row[0]:
        try:
            n, y = row[0].split("/", 1)
            return f"{int(n) + 1}/{y}"
        except ValueError:
            pass
    return f"1/{datetime.now().year % 100:02d}"

def ask(chat_id, text, handler):
    msg = bot.send_message(chat_id, text)
    bot.register_next_step_handler(msg, handler, chat_id)

def cancelled(m, chat_id):
    if (m.text or "").strip() == "/cancel":
        st.pop(chat_id, None)
        bot.reply_to(m, "Отменено. /new — начнём заново.")
        return True
    return False

# ---------- сборка записи ----------

def build_report(d):
    L = [f"Погрузка #{d['number']}", d["date"], SEP,
         f"Водитель: {d['driver']}", f"Телефон: {d['phone']}",
         f"Компания: {d['company']}", f"Машина: {d['car']}",
         f"Прицеп: {d['trailer']}", SEP]
    for c in d["clients"]:
        L += [f"Заказчик: {c['name']}", f"Груз: {c['cargo']}",
              f"Пункт назначения: {c['dest']}⬜"]
    L.append(SEP)
    L += [f"Мы взяли {d['incomes_expr']}={fmt(d['income'])}",
          f"Перевозка {fmt(d['transport'])}",
          f"Грузчики {d['loaders_expr']}",
          f"Выгрузка {fmt(d['unload'])}",
          f"Сотрудники {fmt(d['staff'])}", SEP]
    exp = "-".join(fmt(x) for x in [d["transport"], d["loaders"], d["unload"], d["staff"]])
    L += [f"{fmt(d['income'])}-{exp}={fmt(d['profit'])}",
          f"{fmt(d['profit'])}/{d['people']}={fmt(d['per_person'])} на человека",
          SEP, "Расчёт выплат"]
    for p in d["payouts"]:
        desc = f" ({p['desc']})" if p["desc"] else ""
        L += [p["name"], f"{fmt(p['amount'])}{desc}"]
    L += [SEP, f"В банк: {fmt(d['bank'])}"]
    return "\n".join(L)

def finish(chat_id):
    d = st[chat_id]
    d["incomes_expr"] = "+".join(c["sum"] for c in d["clients"])
    d["income"] = sum(fnum(c["sum"]) for c in d["clients"])
    d["expenses"] = d["transport"] + d["loaders"] + d["unload"] + d["staff"]
    d["profit"] = d["income"] - d["expenses"]
    d["per_person"] = d["profit"] / d["people"] if d["people"] else 0
    report = build_report(d)
    db.execute("""INSERT INTO loads(number, date, driver, phone, company, car, trailer,
        clients, incomes_expr, income, transport, loaders_expr, loaders, unload, staff,
        expenses, profit, people, per_person, payouts, bank)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (d["number"], d["date"], d["driver"], d["phone"], d["company"], d["car"],
         d["trailer"], json.dumps(d["clients"], ensure_ascii=False),
         d["incomes_expr"], d["income"], d["transport"], d["loaders_expr"],
         d["loaders"], d["unload"], d["staff"], d["expenses"], d["profit"],
         d["people"], d["per_person"], json.dumps(d["payouts"], ensure_ascii=False),
         d["bank"]))
    db.commit()
    st.pop(chat_id, None)
    bot.send_message(chat_id, report + "\n\nЗаписано ✅")

# ---------- шаги опроса ----------

@bot.message_handler(commands=["new"])
def cmd_new(m):
    st[m.chat.id] = {"clients": [], "payouts": []}
    ask(m.chat.id, f"Номер погрузки (Enter — {next_number()}):", step_number)

def step_number(m, chat_id):
    if not st.get(chat_id) or cancelled(m, chat_id):
        return
    st[chat_id]["number"] = (m.text or "").strip() or next_number()
    ask(chat_id, f"Дата (Enter — {today()}):", step_date)

def step_date(m, chat_id):
    if cancelled(m, chat_id): return
    st[chat_id]["date"] = (m.text or "").strip() or today()
    ask(chat_id, "Водитель (имя и фамилия):", step_driver)

def step_driver(m, chat_id):
    if cancelled(m, chat_id): return
    st[chat_id]["driver"] = (m.text or "").strip()
    ask(chat_id, "Телефон водителя:", step_phone)

def step_phone(m, chat_id):
    if cancelled(m, chat_id): return
    st[chat_id]["phone"] = (m.text or "").strip()
    ask(chat_id, "Компания:", step_company)

def step_company(m, chat_id):
    if cancelled(m, chat_id): return
    st[chat_id]["company"] = (m.text or "").strip()
    ask(chat_id, "Машина (например: О523ХЗ | 43):", step_car)

def step_car(m, chat_id):
    if cancelled(m, chat_id): return
    st[chat_id]["car"] = (m.text or "").strip()
    ask(chat_id, "Прицеп (если нет — «—»):", step_trailer)

def step_trailer(m, chat_id):
    if cancelled(m, chat_id): return
    st[chat_id]["trailer"] = (m.text or "").strip() or "—"
    ask(chat_id,
        "Заказчики. Одна строка на каждого:\n"
        "Имя | Груз | Пункт назначения | Сумма\n"
        "Перечислили всех — отправьте «готово».",
        step_clients)

def step_clients(m, chat_id):
    if cancelled(m, chat_id): return
    d = st[chat_id]
    text = (m.text or "").strip()
    if not text.lower().startswith("готово"):
        ok = True
        for line in text.splitlines():
            parts = [p.strip() for p in line.split("|")]
            try:
                fnum(parts[3])
            except (ValueError, IndexError):
                ok = False
                break
            d["clients"].append({"name": parts[0], "cargo": parts[1],
                                 "dest": parts[2], "sum": parts[3].replace(" ", "")})
        if not ok:
            ask(chat_id, "Не понял строку. Формат: Имя | Груз | Куда | Сумма. Повторите:",
                step_clients)
            return
    if not d["clients"]:
        ask(chat_id, "Нужен хотя бы один заказчик. Введите строку:", step_clients)
        return
    ask(chat_id, "Перевозка (сумма):", step_transport)

def step_transport(m, chat_id):
    if cancelled(m, chat_id): return
    st[chat_id]["transport"] = fnum(m.text)
    ask(chat_id, "Грузчики (можно так: 7,7+0,7):", step_loaders)

def step_loaders(m, chat_id):
    if cancelled(m, chat_id): return
    d = st[chat_id]
    d["loaders_expr"] = (m.text or "").strip()
    d["loaders"] = fnum(m.text)
    ask(chat_id, "Выгрузка:", step_unload)

def step_unload(m, chat_id):
    if cancelled(m, chat_id): return
    st[chat_id]["unload"] = fnum(m.text)
    ask(chat_id, "Сотрудники:", step_staff)

def step_staff(m, chat_id):
    if cancelled(m, chat_id): return
    st[chat_id]["staff"] = fnum(m.text)
    ask(chat_id, "На сколько человек делим прибыль:", step_people)

def step_people(m, chat_id):
    if cancelled(m, chat_id): return
    st[chat_id]["people"] = int((m.text or "3").strip())
    ask(chat_id,
        "Выплаты. Одна строка: Имя | Сумма | Описание (описание можно опустить).\n"
        "Закончили — «готово».",
        step_payouts)

def step_payouts(m, chat_id):
    if cancelled(m, chat_id): return
    d = st[chat_id]
    text = (m.text or "").strip()
    if not text.lower().startswith("готово"):
        for line in text.splitlines():
            parts = [p.strip() for p in line.split("|")]
            try:
                amount = fnum(parts[1])
            except (ValueError, IndexError):
                ask(chat_id, "Формат: Имя | Сумма | Описание. Повторите:", step_payouts)
                return
            d["payouts"].append({"name": parts[0], "amount": amount,
                                 "desc": parts[2] if len(parts) > 2 else ""})
    ask(chat_id, "Сумма «В банк» (Enter — просуммирую выплаты):", step_bank)

def step_bank(m, chat_id):
    if cancelled(m, chat_id): return
    d = st[chat_id]
    text = (m.text or "").strip()
    d["bank"] = fnum(text) if text else sum(p["amount"] for p in d["payouts"])
    finish(chat_id)

# ---------- просмотр ----------

@bot.message_handler(commands=["last"])
def cmd_last(m):
    row = db.execute("SELECT * FROM loads ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        bot.reply_to(m, "Записей пока нет. Создайте первую: /new")
        return
    d = dict(zip(["id", "number", "date", "driver", "phone", "company", "car",
                  "trailer", "clients", "incomes_expr", "income", "transport",
                  "loaders_expr", "loaders", "unload", "staff", "expenses",
                  "profit", "people", "per_person", "payouts", "bank"], row))
    d["clients"] = json.loads(d["clients"])
    d["payouts"] = json.loads(d["payouts"])
    bot.send_message(m.chat.id, build_report(d))

@bot.message_handler(commands=["list"])
def cmd_list(m):
    rows = db.execute("SELECT id, number, date, driver, profit FROM loads "
                      "ORDER BY id DESC LIMIT 5").fetchall()
    if not rows:
        bot.reply_to(m, "Записей пока нет.")
        return
    lines = [f"{r[0]}. #{r[1]} | {r[2]} | {r[3]} | прибыль {fmt(r[4])}" for r in rows]
    bot.send_message(m.chat.id, "Последние записи:\n" + "\n".join(lines))

@bot.message_handler(commands=["stat"])
def cmd_stat(m):
    month = datetime.now().strftime("%m.%Y")
    rows = db.execute("SELECT date, income, expenses, profit FROM loads").fetchall()
    rows = [r for r in rows if r[0].endswith(month)]
    if not rows:
        bot.reply_to(m, f"За {month} записей нет.")
        return
    inc = sum(r[1] for r in rows)
    exp = sum(r[2] for r in rows)
    prof = sum(r[3] for r in rows)
    bot.send_message(m.chat.id,
                     f"Сводка за {month}\n{SEP}\n"
                     f"Погрузок: {len(rows)}\n"
                     f"Взято: {fmt(inc)}\n"
                     f"Расходы: {fmt(exp)}\n"
                     f"Прибыль: {fmt(prof)}")

@bot.message_handler(commands=["cancel"])
def cmd_cancel(m):
    st.pop(m.chat.id, None)
    bot.reply_to(m, "Отменено. /new — начнём заново.")

@bot.message_handler(commands=["help", "start"])
def cmd_help(m):
    bot.reply_to(m, "Команды:\n"
                    "/new — новая запись о погрузке\n"
                    "/last — последняя запись\n"
                    "/list — последние 5 записей\n"
                    "/stat — сводка за месяц\n"
                    "/cancel — отменить ввод")

@bot.message_handler(func=lambda m: True)
def fallback(m):
    bot.reply_to(m, "Чтобы начать запись — /new. Справка: /help")

print("Бот запущен...")
bot.polling(non_stop=True)
