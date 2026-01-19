from fastapi import FastAPI, Form, Request, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile, BufferedInputFile
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List
import sqlite3
import hashlib
import asyncio
import qrcode
import os
import time
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
# === Хэширование пароля ===
def hash_password(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()
# === База данных ===
conn = sqlite3.connect("data.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS accounts (
                username TEXT PRIMARY KEY,
                password TEXT)""")
cur.execute("""CREATE TABLE IF NOT EXISTS bots (
                bot_id INTEGER PRIMARY KEY,
                token TEXT,
                username TEXT,
                owner TEXT,
                about TEXT DEFAULT 'Мы — крутой магазин!')""")
cur.execute("""CREATE TABLE IF NOT EXISTS clients (
                bot_id INTEGER,
                user_id INTEGER,
                code TEXT,
                points INTEGER DEFAULT 0,
                PRIMARY KEY(bot_id, user_id))""")
conn.commit()
cur.execute("""
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER,
    name TEXT NOT NULL,
    FOREIGN KEY (bot_id) REFERENCES bots (bot_id)
)
""")
conn.commit()
cur.execute("""
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER,
    cat_id INTEGER,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    description TEXT,
    photo_path TEXT,
    sort_order INTEGER DEFAULT 0,
    FOREIGN KEY (bot_id) REFERENCES bots (bot_id),
    FOREIGN KEY (cat_id) REFERENCES categories (id)
)
""")
conn.commit()
cur.execute("""
CREATE TABLE IF NOT EXISTS cart (
    bot_id INTEGER,
    user_id TEXT,
    prod_id INTEGER,
    quantity INTEGER DEFAULT 1,
    PRIMARY KEY (bot_id, user_id, prod_id)
)
""")
conn.commit()
cur.execute("""CREATE TABLE IF NOT EXISTS order_items (
    order_id INTEGER,
    prod_id INTEGER,
    name TEXT,
    price INTEGER,
    quantity INTEGER,
    PRIMARY KEY (order_id, prod_id)
)""")
conn.commit()
cur.execute("""CREATE TABLE IF NOT EXISTS menu_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER,
    photo_path TEXT,
    sort_order INTEGER DEFAULT 0,
    FOREIGN KEY (bot_id) REFERENCES bots (bot_id)
)""")
conn.commit()
try:
    cur.execute("ALTER TABLE products ADD COLUMN enabled INTEGER DEFAULT 1")
    conn.commit()
    print("Добавлена колонка enabled в products")
except sqlite3.OperationalError:
    pass
try:
    cur.execute("ALTER TABLE bots ADD COLUMN notify_chat_id TEXT")
    conn.commit()
except sqlite3.OperationalError:
    pass
try:
    cur.execute("ALTER TABLE bots ADD COLUMN allow_in_hall INTEGER DEFAULT 1")
    print("Добавлена колонка allow_in_hall")
except sqlite3.OperationalError:
    pass
try:
    cur.execute("ALTER TABLE bots ADD COLUMN allow_takeaway INTEGER DEFAULT 1")
    print("Добавлена колонка allow_takeaway")
except sqlite3.OperationalError:
    pass
try:
    cur.execute("ALTER TABLE bots ADD COLUMN allow_delivery INTEGER DEFAULT 1")
    print("Добавлена колонка allow_delivery")
except sqlite3.OperationalError:
    pass
conn.commit()
try:
    cur.execute("ALTER TABLE orders ADD COLUMN cafe_message_id INTEGER")
    conn.commit()
    print("Добавлена колонка cafe_message_id")
except sqlite3.OperationalError:
    pass
try:
    cur.execute("ALTER TABLE bots ADD COLUMN timezone TEXT DEFAULT 'Europe/Moscow'")
    conn.commit()
except sqlite3.OperationalError:
    pass
try:
    cur.execute("ALTER TABLE bots ADD COLUMN work_start TEXT") # например "10:00"
    conn.commit()
except sqlite3.OperationalError:
    pass
try:
    cur.execute("ALTER TABLE bots ADD COLUMN work_end TEXT") # например "22:00"
    conn.commit()
except sqlite3.OperationalError:
    pass
try:
    cur.execute("ALTER TABLE bots ADD COLUMN restrict_orders INTEGER DEFAULT 0") # 1 = включено ограничение
    conn.commit()
except sqlite3.OperationalError:
    pass
try:
    cur.execute("ALTER TABLE bots ADD COLUMN auto_cancel_minutes INTEGER DEFAULT 60") # в минутах
    conn.commit()
    print("Добавлена колонка auto_cancel_minutes")
except sqlite3.OperationalError:
    pass
try:
    cur.execute("ALTER TABLE bots ADD COLUMN auto_cancel_enabled INTEGER DEFAULT 1") # 1 = включено
    conn.commit()
    print("Добавлена колонка auto_cancel_enabled")
except sqlite3.OperationalError:
    pass
try:
    cur.execute("ALTER TABLE bots ADD COLUMN menu_photo_path TEXT")
    conn.commit()
except sqlite3.OperationalError:
    pass
try:
    cur.execute("ALTER TABLE bots ADD COLUMN bonuses_enabled INTEGER DEFAULT 1") # 1 = включено
    conn.commit()
    print("Добавлена колонка bonuses_enabled")
except sqlite3.OperationalError:
    pass
try:
    cur.execute("ALTER TABLE categories ADD COLUMN photo_path TEXT")
    conn.commit()
    print("Добавлена колонка photo_path в categories")
except sqlite3.OperationalError:
    pass
try:
    cur.execute("ALTER TABLE bots ADD COLUMN bonus_percent INTEGER DEFAULT 10") # 10%
    conn.commit()
except sqlite3.OperationalError:
    pass
try:
    cur.execute("ALTER TABLE bots ADD COLUMN max_bonus_pay_percent INTEGER DEFAULT 30") # макс 30% оплаты бонусами
    conn.commit()
except sqlite3.OperationalError:
    pass
try:
    cur.execute("ALTER TABLE bots ADD COLUMN min_order_for_bonus INTEGER DEFAULT 0") # от 0 ₽
    conn.commit()
except sqlite3.OperationalError:
    pass
try:
    cur.execute("ALTER TABLE bots ADD COLUMN bonus_expire_days INTEGER DEFAULT 0") # 0 = не сгорают
    conn.commit()
except sqlite3.OperationalError:
    pass
try:
    cur.execute("ALTER TABLE bots ADD COLUMN welcome_bonus INTEGER DEFAULT 0")
    conn.commit()
except sqlite3.OperationalError:
    pass
try:
    cur.execute("ALTER TABLE orders ADD COLUMN comment TEXT")
    conn.commit()
    print("Добавлено поле comment в orders")
except sqlite3.OperationalError:
    pass
active_bots: dict[int, dict] = {}
user_states: dict[int, dict] = {}
async def launch_bot(bot_id: int, token: str, username: str):
    if bot_id in active_bots:
        try:
            await active_bots[bot_id]["bot"].session.close()
        except:
            pass
        del active_bots[bot_id]
        await asyncio.sleep(2)
    bot = Bot(token=token)
    dp = Dispatcher()
    if bot_id not in user_states:
        user_states[bot_id] = {}
    user_state = user_states[bot_id]
    # === ГЛАВНОЕ МЕНЮ ===
    async def show_main_menu(message_or_callback: types.Message | types.CallbackQuery):
        # Получаем настройку бонусов
        cur.execute("SELECT bonuses_enabled FROM bots WHERE bot_id=?", (bot_id,))
        row = cur.fetchone()
        bonuses_enabled = row[0] if row else 1
        # Базовая клавиатура
        kb_buttons = [
            [KeyboardButton(text="Меню"), KeyboardButton(text="Корзина")],
            [KeyboardButton(text="Статус заказа")],
            [KeyboardButton(text="О нас")]
        ]
        if bonuses_enabled == 1:
            # С бонусами — три ряда
            kb_buttons[1].append(KeyboardButton(text="Виртуальная карта"))
            kb_buttons[2] = [KeyboardButton(text="Мой баланс"), KeyboardButton(text="О нас")]
        else:
            # Без бонусов — два ряда
            kb_buttons = [
                [KeyboardButton(text="Меню"), KeyboardButton(text="Корзина")],
                [KeyboardButton(text="Статус заказа"), KeyboardButton(text="О нас")]
            ]
        kb = ReplyKeyboardMarkup(keyboard=kb_buttons, resize_keyboard=True)
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.answer("Вы в главном меню", reply_markup=kb)
            await message_or_callback.answer()
        else:
            await message_or_callback.answer("Вы в главном меню", reply_markup=kb)
    @dp.message(lambda m: user_state.get(m.from_user.id, {}).get("type") == "category_products" and m.text == "Корзина")
    async def go_to_cart_from_category(message: types.Message):
        uid = message.from_user.id
        # Сохраняем состояние категории перед уходом в корзину
        if uid in user_state:
            user_state[uid]["previous_state"] = {
                "type": "category_products",
                "cat_id": user_state[uid].get("cat_id"),
                "prods": user_state[uid].get("prods"),
                "page": user_state[uid].get("page", 0)
            }
        await show_cart(message)
    @dp.message(lambda m: user_state.get(m.from_user.id, {}).get("type") == "category_products" and m.text in ["⬅️", "➡️"])
    async def category_pagination(message: types.Message):
        uid = message.from_user.id
        state = user_state[uid]
        page = state["page"]
        if message.text == "⬅️":
            page = max(0, page - 1)
        elif message.text == "➡️":
            page += 1
        state["page"] = page
        await show_category_products_keyboard(message, page)
    @dp.message(lambda m: user_state.get(m.from_user.id, {}).get("type") == "category_products" and m.text == "Назад")
    async def back_to_categories_from_products(message: types.Message):
        user_state.pop(message.from_user.id, None)
        cur.execute("SELECT name FROM categories WHERE bot_id=?", (bot_id,))
        cats = cur.fetchall()
        if not cats:
            await message.answer("Категории ещё не добавлены.")
            return
        keyboard_rows = [[KeyboardButton(text=cat[0])] for cat in cats]
        keyboard_rows.append([KeyboardButton(text="Назад")])
        kb = ReplyKeyboardMarkup(keyboard=keyboard_rows, resize_keyboard=True)
        await message.answer("Выберите категорию:", reply_markup=kb)
    #"НА ГЛАВНУЮ"
    @dp.message(lambda m: m.text == "На главную")
    async def go_main_menu(message: types.Message):
        uid = message.from_user.id
        if uid in user_state:
            user_state.pop(uid, None)
        await show_main_menu(message)
# Новая функция для генерации kb (вставь перед process_order_status)
    def generate_order_kb(current_status: str, is_delivery: bool, order_id: int):
        if is_delivery:
            allowed = {"new": ["accept"], "accepted": ["cooking"], "cooking": ["ontheway"], "ontheway": ["complete"]}
            button_texts = {"accept": "Принять", "cooking": "Готовится", "ontheway": "Курьер в пути", "complete": "Заказ выполнен"}
        else:
            allowed = {"new": ["accept"], "accepted": ["cooking"], "cooking": ["ready"], "ready": ["complete"]}
            button_texts = {"accept": "Принять", "cooking": "Готовится", "ready": "Готов к выдаче", "complete": "Заказ выполнен"}
        next_actions = allowed.get(current_status, [])
        rows = []
        for act in next_actions:
            rows.append([InlineKeyboardButton(text=button_texts[act], callback_data=f"order_{act}*{order_id}")])
        if current_status != "completed":
            rows.append([InlineKeyboardButton(text="Отменить", callback_data=f"order_cancel*{order_id}")])
        return InlineKeyboardMarkup(inline_keyboard=rows)
    @dp.message(lambda m: user_state.get(m.from_user.id, {}).get("type") == "category_products")
    async def add_product_from_keyboard(message: types.Message):
        uid = message.from_user.id
        state = user_state[uid]
        prods = state["prods"]
        prod_name = message.text
    
        # Проверяем, не является ли это системной кнопкой
        if prod_name in ["⬅️", "➡️", "Назад", "Корзина", "На главную"]:
            return # игнорируем системные кнопки
    
        # Находим prod_id по имени
        prod_id = next((p[0] for p in prods if p[1] == prod_name), None)
        if prod_id:
            cur.execute("""INSERT INTO cart (bot_id, user_id, prod_id, quantity)
                        VALUES (?, ?, ?, 1)
                        ON CONFLICT(bot_id, user_id, prod_id) DO UPDATE SET quantity = quantity + 1""",
                        (bot_id, uid, prod_id))
            conn.commit()
            await message.answer(f"✅ {prod_name} добавлен в корзину!")
            # Остаёмся в категории — обновляем клавиатуру
            await show_category_products_keyboard(message, state["page"])
    @dp.message(CommandStart())
    async def cmd_start(message: types.Message):
        uid = message.from_user.id
    
        # Проверяем, есть ли клиент в базе
        cur.execute("SELECT points FROM clients WHERE bot_id=? AND user_id=?", (bot_id, uid))
        if not cur.fetchone():
            # Новый клиент — начисляем приветственный бонус
            cur.execute("SELECT welcome_bonus, bonuses_enabled FROM bots WHERE bot_id=?", (bot_id,))
            bot_settings = cur.fetchone()
            if bot_settings and bot_settings[1] == 1 and bot_settings[0] > 0:
                welcome = bot_settings[0]
                cur.execute("INSERT INTO clients (bot_id, user_id, points, code) VALUES (?, ?, ?, ?)",
                            (bot_id, uid, welcome, f"client_{uid}"))
                conn.commit()
                await message.answer(f"🎁 Добро пожаловать! Вам начислено {welcome} приветственных бонусов!")
    
        await show_main_menu(message)
    # Доставка
    @dp.message(lambda m: m.text == "Статус заказа")
    async def show_orders_list(message: types.Message):
        uid = message.from_user.id
        cur.execute("""SELECT id, created_at, total, status, delivery_type
                    FROM orders
                    WHERE bot_id = ? AND user_id = ?
                    ORDER BY created_at DESC""", (bot_id, uid))
        orders = cur.fetchall()
        if not orders:
            await message.answer("У вас пока нет заказов.",
                            reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="На главную")]], resize_keyboard=True))
            return
        user_state[uid] = {"type": "orders", "orders_list": orders, "index": 0}
        await show_order_detail(message, orders, 0)
    async def show_order_detail(message: types.Message, orders: list, index: int):
        uid = message.from_user.id
        order_id, created_at, total, status, delivery_type = orders[index]
        date = time.strftime("%d.%m.%Y %H:%M", time.localtime(created_at))
        cur.execute("""SELECT name, quantity, price FROM order_items WHERE order_id = ?""", (order_id,))
        items = cur.fetchall()
        status_emojis = {
            "new": "Новый",
            "accepted": "Принят",
            "cooking": "Готовится",
            "ready": "Готов к выдаче",
            "ontheway": "Курьер в пути",
            "completed": "Выполнен",
            "cancelled": "Отменён"
        }
        status_text = status_emojis.get(status, "Неизвестно")
        items_text = "\n".join([f"• {name} ×{qty} — {price*qty} ₽" for name, qty, price in items]) if items else "Товары не найдены"
        text = f"""
<b>Заказ №{order_id}</b>
{date} | {delivery_type}
Сумма: <b>{total} ₽</b>
Статус: <b>{status_text}</b>
{items_text}
        """.strip()
        # ← ВОТ ГЛАВНОЕ ИСПРАВЛЕНИЕ: все кнопки через KeyboardButton!
        keyboard = []
        # Навигация
        row = []
        if index > 0:
            row.append(KeyboardButton(text="Предыдущий"))
        if index < len(orders)-1:
            row.append(KeyboardButton(text="Следующий"))
        if row:
            keyboard.append(row)
        # Кнопка отмены для клиента
        if status in ["new", "accepted"]:
            keyboard.append([KeyboardButton(text="Отменить заказ")])
        # Всегда кнопка домой
        keyboard.append([KeyboardButton(text="На главную")])
        kb = ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
        await message.answer(text, parse_mode="HTML", reply_markup=kb)
    # === ЛИСТАНИЕ ЗАКАЗОВ + ОТМЕНА СО СТОРОНЫ КЛИЕНТА ===
    @dp.message(lambda m: user_state.get(m.from_user.id, {}).get("type") == "orders" and m.text in ["Предыдущий", "Следующий", "На главную", "Отменить заказ"])
    async def navigate_orders(message: types.Message):
        uid = message.from_user.id
        state = user_state[uid]
        orders = state["orders_list"]
        index = state["index"]
        if message.text == "Предыдущий":
            index -= 1
        elif message.text == "Следующий":
            index += 1
        elif message.text == "На главную":
            user_state.pop(uid, None)
            await show_main_menu(message)
            return
        elif message.text == "Отменить заказ":
            order_id = orders[index][0]
            # Запоминаем, что ждём подтверждения отмены
            user_state[uid]["awaiting_cancel_confirm"] = order_id
            kb = ReplyKeyboardMarkup(keyboard=[
                [KeyboardButton(text="Да, отменить заказ")],
                [KeyboardButton(text="Нет, оставить")],
                [KeyboardButton(text="На главную")]
            ], resize_keyboard=True)
            await message.answer("Вы уверены, что хотите отменить заказ?", reply_markup=kb)
            return
        state["index"] = index
        await show_order_detail(message, orders, index)
    # === ФИНАЛЬНАЯ ОТМЕНА ПОСЛЕ ВЫБОРА ПРИЧИНЫ (ПЕРВЫЙ ОБРАБОТЧИК!) ===
    @dp.message(lambda m: user_state.get(m.from_user.id, {}).get("awaiting_cancel_reason") is not None)
    async def client_cancel_with_reason(message: types.Message):
        uid = message.from_user.id
        order_id = user_state[uid]["awaiting_cancel_reason"]
        reason = message.text.strip()
        user_state.pop(uid, None) # Чистим состояние
        if reason == "Назад":
            user_state[uid] = {"awaiting_cancel_confirm": order_id}
            kb = ReplyKeyboardMarkup(keyboard=[
                [KeyboardButton(text="Да, отменить заказ")],
                [KeyboardButton(text="Нет, оставить")],
                [KeyboardButton(text="На главную")]
            ], resize_keyboard=True)
            await message.answer("Вы уверены, что хотите отменить заказ?", reply_markup=kb)
            return
        # Отмена заказа
        cur.execute("UPDATE orders SET status = 'cancelled' WHERE id = ? AND user_id = ? AND status IN ('new', 'accepted')", (order_id, uid))
        if cur.rowcount > 0:
            conn.commit()
            # Уведомление сотрудникам с причиной
            cur.execute("""SELECT o.cafe_message_id, b.notify_chat_id, o.total, o.delivery_type
                        FROM orders o JOIN bots b ON o.bot_id = b.bot_id WHERE o.id = ?""", (order_id,))
            row = cur.fetchone()
            if row and row[0] and row[1]:
                try:
                    items_text = ""
                    cur.execute("SELECT name, quantity, price FROM order_items WHERE order_id = ?", (order_id,))
                    for n, q, p in cur.fetchall():
                        items_text += f"• {n} ×{q} — {p*q} ₽\n"
                    await bot.edit_message_text(
                        chat_id=int(row[1]),
                        message_id=row[0],
                        text=f"Заказ №{order_id} — ОТМЕНЁН КЛИЕНТОМ\nПричина: {reason}\nТип: {row[3]} | Сумма: {row[2]} ₽\n\n{items_text}Клиент отменил заказ❌",
                        reply_markup=None
                    )
                except: pass
                try:
                    await bot.send_message(int(row[1]), f"ОТМЕНА №{order_id}\nПричина: {reason}❌")
                except: pass
            await message.answer(
                f"Заказ №{order_id} отменён❌\nПричина: {reason}\nСпасибо за обратную связь!",
                reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="На главную")]], resize_keyboard=True)
            )
        else:
            await message.answer("Заказ уже нельзя отменить.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="На главную")]], resize_keyboard=True))
    # === ПОДТВЕРЖДЕНИЕ ОТМЕНЫ (ВТОРОЙ ОБРАБОТЧИК) ===
    @dp.message(lambda m: user_state.get(m.from_user.id, {}).get("awaiting_cancel_confirm") is not None)
    async def client_cancel_confirm(message: types.Message):
        uid = message.from_user.id
        order_id = user_state[uid]["awaiting_cancel_confirm"]
        if message.text == "Да, отменить заказ":
            user_state[uid]["awaiting_cancel_reason"] = order_id
            kb = ReplyKeyboardMarkup(keyboard=[
                [KeyboardButton(text="Назад")],
                [KeyboardButton(text="Передумал")],
                [KeyboardButton(text="Ошибка в заказе")],
                [KeyboardButton(text="Другая причина")]
            ], resize_keyboard=True)
            await message.answer("Укажите причину отмены:", reply_markup=kb)
            return
        if message.text in ["Нет, оставить", "На главную"]:
            user_state.pop(uid, None)
            await show_main_menu(message)
            return
        # Просто игнорируем другие сообщения
        return
    # === КОРЗИНА (с пролистыванием, +1/-1, удалить) ===
    @dp.message(lambda m: m.text == "Корзина")
    async def show_cart(message: types.Message):
        uid = message.from_user.id
    
        # ИНИЦИАЛИЗИРУЕМ СЛОВАРЬ ДЛЯ ПОЛЬЗОВАТЕЛЯ, ЕСЛИ ЕГО НЕТ
        if uid not in user_state:
            user_state[uid] = {}
    
        # 1. Сохраняем текущее состояние как предыдущее
        current_state = user_state[uid].copy() # теперь безопасно, словарь существует
        if current_state:
            user_state[uid]["previous_state"] = current_state
        else:
            user_state[uid]["previous_state"] = {"from_main_menu": True}
    
        # 2. Загружаем товары из корзины
        cur.execute("""SELECT c.prod_id, c.quantity, p.name, p.price
                    FROM cart c JOIN products p ON c.prod_id = p.id
                    WHERE c.bot_id = ? AND c.user_id = ? ORDER BY c.prod_id""", (bot_id, uid))
        items = cur.fetchall()
    
        if not items:
            await message.answer("Ваша корзина пуста!", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Назад")]], resize_keyboard=True))
            return
    
        # 3. УСТАНАВЛИВАЕМ СОСТОЯНИЕ КОРЗИНЫ
        user_state[uid] = {
            "type": "cart_view",
            "items": [(row[0], row[1], row[2], row[3]) for row in items],
            "page": 0,
            "previous_state": user_state[uid].get("previous_state")
        }
    
        # 4. Показываем корзину
        await show_cart_full_list_and_keyboard(message, 0)
    async def show_cart_full_list_and_keyboard(message: types.Message, page: int):
        uid = message.from_user.id
        state = user_state.get(uid, {})
        if state.get("type") != "cart_view":
            return
    
        items = state["items"] # (prod_id, quantity, name, price)
        total_sum = sum(qty * price for _, qty, _, price in items)
    
        # Формируем полный список для сообщения
        list_text = ""
        for _, qty, name, price in items:
            list_text += f"• {name} × {qty} — {price * qty} ₽\n"
        full_text = f"<b>Ваша корзина:</b>\n\n{list_text}\n<b>Итого: {total_sum} ₽</b>"
    
        # Клавиатура с товарами (по 2 в ряд, до 6)
        per_page = 6
        start = page * per_page
        end = start + per_page
        current_items = items[start:end]
    
        keyboard = []
        for i in range(0, len(current_items), 2):
            row = [KeyboardButton(text=current_items[i][2])] # имя товара
            if i + 1 < len(current_items):
                row.append(KeyboardButton(text=current_items[i+1][2]))
            keyboard.append(row)
    
        # Нижняя строка: пагинация + "Назад" + "Заказать"
        nav_row = []
        if page > 0:
            nav_row.append(KeyboardButton(text="⬅️"))
        nav_row.append(KeyboardButton(text="Назад"))
        nav_row.append(KeyboardButton(text="Заказать"))
        if end < len(items):
            nav_row.append(KeyboardButton(text="➡️"))
        keyboard.append(nav_row)
    
        kb = ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    
        await message.answer(full_text, parse_mode="HTML", reply_markup=kb)
        # Состояние для карточки товара в корзине
    async def show_cart_product_card(message: types.Message, items: list, index: int):
        uid = message.from_user.id
        prod_id, qty, name, price = items[index]
    
        # Получаем полную инфу о товаре (фото, описание)
        cur.execute("""SELECT p.photo_path, p.description
                    FROM products p WHERE p.id = ?""", (prod_id,))
        row = cur.fetchone()
        photo_path = row[0] if row else None
        description = row[1] if row and row[1] else ""
    
        total_price = price * qty
        total_sum = sum(quantity * price for prod_id, quantity, name, price in items)
    
        text = f"<b>{name}</b>\n"
        if description:
            text += f"{description}\n\n"
        text += f"Цена: {price} ₽ × {qty} = <b>{total_price} ₽</b>\n\n"
        text += f"Товар {index + 1} из {len(items)}\nОбщая сумма: <b>{total_sum} ₽</b>"
    
        nav = []
        if index > 0:
            nav.append(KeyboardButton(text="Предыдущий"))
        if index < len(items) - 1:
            nav.append(KeyboardButton(text="Следующий"))
    
        kb = ReplyKeyboardMarkup(keyboard=[
            nav if nav else [],
            [KeyboardButton(text="-1"), KeyboardButton(text=f"{qty} шт"), KeyboardButton(text="+1")],
            [KeyboardButton(text="Удалить")],
            [KeyboardButton(text="Назад в корзину")]
        ], resize_keyboard=True)
    
        if photo_path:
            await message.answer_photo(FSInputFile(photo_path), caption=text, parse_mode="HTML", reply_markup=kb)
        else:
            await message.answer(text, parse_mode="HTML", reply_markup=kb)
    
        # Сохраняем индекс для навигации
        user_state[uid]["cart_item_index"] = index
    # Навигация и действия в карточке товара
    @dp.message(lambda m: user_state.get(m.from_user.id, {}).get("cart_item_index", None) is not None)
    async def cart_item_navigation(message: types.Message):
        uid = message.from_user.id
        state = user_state[uid]
        items = state["items"]
        index = state["cart_item_index"]
    
        prod_id = items[index][0]
    
        if message.text == "+1":
            items[index] = (prod_id, items[index][1] + 1, items[index][2], items[index][3])
            cur.execute("UPDATE cart SET quantity = quantity + 1 WHERE bot_id=? AND user_id=? AND prod_id=?", (bot_id, uid, prod_id))
        elif message.text == "-1":
            new_qty = max(1, items[index][1] - 1)
            items[index] = (prod_id, new_qty, items[index][2], items[index][3])
            cur.execute("UPDATE cart SET quantity = ? WHERE bot_id=? AND user_id=? AND prod_id=?", (new_qty, bot_id, uid, prod_id))
        elif message.text == "Удалить":
            cur.execute("DELETE FROM cart WHERE bot_id=? AND user_id=? AND prod_id=?", (bot_id, uid, prod_id))
            del items[index]
            conn.commit()
        
            if not items:
                # Корзина стала пустой
                user_state.pop(uid, None)
                await message.answer("Корзина очищена!", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Назад")]], resize_keyboard=True))
                return
        
            # УДАЛЕНИЕ: сразу возвращаемся в список корзины
            user_state[uid].pop("cart_item_index", None) # выходим из режима карточки
            await show_cart_full_list_and_keyboard(message, state["page"])
            return
    @dp.message(lambda m: user_state.get(m.from_user.id, {}).get("type") == "cart_view" and m.text in ["⬅️", "➡️"])
    async def cart_pagination(message: types.Message):
        uid = message.from_user.id
        state = user_state[uid]
        page = state["page"]
        if message.text == "⬅️":
            page = max(0, page - 1)
        elif message.text == "➡️":
            page += 1
        state["page"] = page
        await show_cart_full_list_and_keyboard(message, page)
    @dp.message(lambda m: user_state.get(m.from_user.id, {}).get("type") == "cart_view" and m.text == "Назад")
    async def back_from_cart(message: types.Message):
        uid = message.from_user.id
        state = user_state.get(uid, {})
    
        previous = state.get("previous_state")
        if previous:
            # Восстанавливаем предыдущее состояние
            if previous.get("type") == "category_products":
                user_state[uid] = previous # полностью восстанавливаем
                await show_category_products_keyboard(message, previous.get("page", 0))
                return
            # Можно добавить другие состояния, если будут (например, статус заказа и т.д.)
    
        # Если предыдущего состояния нет или оно главное меню — идём в главное
        user_state.pop(uid, None)
        await show_main_menu(message)
    async def ask_delivery_type(message: types.Message):
        uid = message.from_user.id
    
        # === ПРОВЕРКА ВРЕМЕНИ РАБОТЫ ===
        cur.execute("""SELECT restrict_orders, timezone, work_start, work_end
                    FROM bots WHERE bot_id = ?""", (bot_id,))
        bot_settings = cur.fetchone()
        if bot_settings and bot_settings[0] == 1: # если ограничение включено
            restrict, tz_name, start_str, end_str = bot_settings
            if start_str and end_str:
                blocked = False
                try:
                    from zoneinfo import ZoneInfo
                    import datetime
                
                    tz = ZoneInfo(tz_name)
                    now = datetime.datetime.now(tz)
                    current_time = now.time()
                
                    start_time = datetime.datetime.strptime(start_str, "%H:%M").time()
                    end_time = datetime.datetime.strptime(end_str, "%H:%M").time()
                
                    if not (start_time <= current_time <= end_time):
                        blocked = True
                except Exception as e:
                    print("Ошибка проверки времени (игнорируем):", e)
                    blocked = False
            
                if blocked:
                    tz_display = tz_name.split("/")[-1].replace("*", " ")
                    await message.answer(
                        f"Извините, мы сейчас не принимаем заказы 😔\n"
                        f"Работаем с {start_str} по {end_str} ({tz_display})\n"
                        f"Ждём вас в рабочее время!"
                    )
                    return
    
        # === ДОСТУПНЫЕ СПОСОБЫ ПОЛУЧЕНИЯ ===
        cur.execute("""SELECT allow_in_hall, allow_takeaway, allow_delivery
                    FROM bots WHERE bot_id = ?""", (bot_id,))
        row = cur.fetchone()
        if not row:
            await message.answer("Ошибка настроек бота")
            return
        allow_hall, allow_takeaway, allow_delivery = row
    
        # Берём товары из корзины
        cur.execute("""SELECT c.prod_id, c.quantity, p.name, p.price
                       FROM cart c JOIN products p ON c.prod_id = p.id
                       WHERE c.bot_id=? AND c.user_id=?""", (bot_id, uid))
        items = cur.fetchall()
        if not items:
            await message.answer("Корзина пуста!")
            user_state.pop(uid, None)
            await show_main_menu(message)
            return

        # Считаем сумму здесь
        total = sum(qty * price for _, qty, _, price in items)  # ← добавь эту строку!

        # Сохраняем в состояние
        if uid not in user_state:
            user_state[uid] = {}
        user_state[uid]["temp_order_items"] = items
        user_state[uid]["awaiting_delivery_type"] = True

        # Клавиатура со способами
        buttons = []
        if allow_hall:
            buttons.append([KeyboardButton(text="В зале")])
        if allow_takeaway:
            buttons.append([KeyboardButton(text="Самовывоз")])
        if allow_delivery:
            buttons.append([KeyboardButton(text="Доставка курьером")])
        if not buttons:
            await message.answer("Извините, заказы временно недоступны.")
            return

        buttons.append([KeyboardButton(text="Отмена")])
        kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

        await message.answer(
            f"Общая сумма: {total} ₽\n\nВыберите способ получения:",
            reply_markup=kb
        )
    @dp.message(lambda m: user_state.get(m.from_user.id, {}).get("type") == "cart_view" and m.text == "Заказать")
    async def order_from_cart(message: types.Message):
        await ask_delivery_type(message)

    @dp.message(lambda m: user_state.get(m.from_user.id, {}).get("awaiting_delivery_type"))
    async def process_delivery_type(message: types.Message):
        uid = message.from_user.id
        choice = message.text.strip()

        if choice == "Отмена":
            user_state.pop(uid, None)
            await show_main_menu(message)
            return

        if choice == "Доставка курьером":
            choice = "Доставка"

        if choice not in ["В зале", "Самовывоз", "Доставка"]:
            await message.answer("Пожалуйста, выберите один из вариантов ниже.")
            return

        # Сохраняем тип доставки и переходим к комментарию
        temp_items = user_state.pop(uid, {}).get("temp_order_items", [])
        if not temp_items:
            await message.answer("Корзина пуста!")
            await show_main_menu(message)
            return

        user_state[uid] = {
            "delivery_type": choice,
            "temp_order_items": temp_items,
            "awaiting_comment": True  # ждём комментарий
        }

        # Клавиатура для комментария
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="Без комментария")],
            [KeyboardButton(text="Отмена")]
        ], resize_keyboard=True)

        await message.answer(
            "Добавьте комментарий к заказу (если есть):\n"
            "Например: без лука, позвонить заранее, оставить у двери и т.п.\n"
            "Можно также указать желаемое время получения.\n\n"
            "Если комментария нет — нажмите «Без комментария»",
            reply_markup=kb
        )


    @dp.message(lambda m: user_state.get(m.from_user.id, {}).get("awaiting_comment"))
    async def process_order_comment(message: types.Message):
        uid = message.from_user.id
        comment = message.text.strip()

        if comment == "Отмена":
            user_state.pop(uid, None)
            await show_main_menu(message)
            return

        state = user_state[uid]
        delivery_type = state["delivery_type"]
        temp_items = state["temp_order_items"]

        # Если "Без комментария" — пустая строка
        if comment == "Без комментария":
            comment = ""

        # Сохраняем комментарий
        state["comment"] = comment

        # Сразу оформляем заказ (без времени)
        total = sum(qty * price for _, qty, _, price in temp_items)
        order_id = int(time.time())  # или другой способ генерации ID

        cur.execute("""
            INSERT INTO orders (id, bot_id, user_id, total, created_at, delivery_type, comment)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (order_id, bot_id, uid, total, order_id, delivery_type, comment))
        conn.commit()

        # Сохраняем товары в order_items
        for prod_id, qty, name, price in temp_items:
            cur.execute("INSERT INTO order_items (order_id, prod_id, name, price, quantity) VALUES (?, ?, ?, ?, ?)",
                        (order_id, prod_id, name, price, qty))
        conn.commit()

        # Очищаем корзину
        cur.execute("DELETE FROM cart WHERE bot_id=? AND user_id=?", (bot_id, uid))
        conn.commit()

        # Формируем текст для сотрудников
        items_text = "\n".join([f"• {name} ×{qty} — {price*qty} ₽" for _, qty, name, price in temp_items])
        full_text = f"""
    НОВЫЙ ЗАКАЗ №{order_id}
    Тип: {delivery_type}
    Сумма: {total} ₽
    Комментарий клиента: {comment if comment else "нет"}
    Товары:
    {items_text}
    Клиент: {message.from_user.full_name}
    @{message.from_user.username or 'нет'}
    ID: {uid}
        """.strip()

        # Отправляем в чат сотрудников
        cur.execute("SELECT notify_chat_id FROM bots WHERE bot_id=?", (bot_id,))
        row = cur.fetchone()
        chat_id = row[0] if row and row[0] else None

        if chat_id:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Принять", callback_data=f"order_accept*{order_id}")],
                [InlineKeyboardButton(text="Отменить", callback_data=f"order_cancel*{order_id}")]
            ])
            try:
                sent = await bot.send_message(
                    chat_id=int(chat_id),
                    text=full_text,
                    reply_markup=keyboard
                )
                cur.execute("UPDATE orders SET cafe_message_id = ? WHERE id = ?", (sent.message_id, order_id))
                conn.commit()
            except Exception as e:
                print(f"Ошибка отправки в кафе: {e}")

        # Ответ клиенту
        await message.answer(f"Заказ №{order_id} успешно оформлен! ✅\nОжидайте подтверждения от кафе.")
        await show_main_menu(message)

        # Чистим состояние
        user_state.pop(uid, None)

    # === ВСЕ ОСТАЛЬНЫЕ КНОПКИ (ОБЯЗАТЕЛЬНО!) ===
    @dp.message(lambda m: m.text == "Виртуальная карта")
    async def virtual_card(message: types.Message):
        uid = message.from_user.id
        cur.execute("SELECT code FROM clients WHERE bot_id=? AND user_id=?", (bot_id, uid))
        row = cur.fetchone()
        code = row[0] if row else f"client*{uid}"
        if not row:
            cur.execute("INSERT INTO clients (bot_id, user_id, code) VALUES (?,?,?)", (bot_id, uid, code))
            conn.commit()
        link = f"https://t.me/{username}?start={code}"
        qr_path = f"qr*{bot_id}*{uid}.png"
        qrcode.make(link).save(qr_path)
        await message.answer_photo(FSInputFile(qr_path), caption=f"Твоя карта\nКод: <code>{code}</code>", parse_mode="HTML")
        os.remove(qr_path)
    @dp.message(lambda m: m.text == "Мой баланс")
    async def balance(message: types.Message):
        cur.execute("SELECT points FROM clients WHERE bot_id=? AND user_id=?", (bot_id, message.from_user.id))
        row = cur.fetchone()
        await message.answer(f"У тебя {row[0] if row else 0} бонусов")
    @dp.message(lambda m: m.text == "О нас")
    async def about(message: types.Message):
        cur.execute("SELECT about FROM bots WHERE bot_id=?", (bot_id,))
        row = cur.fetchone()
        text = row[0] if row and row[0] else "Мы — крутой магазин!"
        await message.answer(text)
    @dp.message(lambda m: m.text == "Меню")
    async def show_full_menu(message: types.Message):
        cur.execute("SELECT photo_path FROM menu_photos WHERE bot_id=? ORDER BY sort_order, id", (bot_id,))
        photos = cur.fetchall()
    
        if photos:
            media = []
            for i, (photo_path,) in enumerate(photos[:10]): # максимум 10 фото в альбоме
                caption = "Полное меню кафе" if i == 0 else None
                # Используем FSInputFile — он быстрее загружает файлы
                media.append(types.InputMediaPhoto(media=FSInputFile(photo_path), caption=caption))
        
            # Отправляем одним альбомом
            await message.answer_media_group(media=media)
        else:
            await message.answer("Меню ещё не загружено владельцем кафе 😔")
    
        # Сразу показываем категории
        cur.execute("SELECT name FROM categories WHERE bot_id=?", (bot_id,))
        cats = cur.fetchall()
        if not cats:
            await message.answer("Категории ещё не добавлены.")
            return
    
        keyboard_rows = [[KeyboardButton(text=cat[0])] for cat in cats]
        keyboard_rows.append([KeyboardButton(text="Назад")])
        kb = ReplyKeyboardMarkup(keyboard=keyboard_rows, resize_keyboard=True)
        await message.answer("Выберите категорию:", reply_markup=kb)
    @dp.message(lambda m: m.text and m.text in [c[0] for c in cur.execute("SELECT name FROM categories WHERE bot_id=?", (bot_id,)).fetchall()])
    async def category_selected(message: types.Message):
        cat_name = message.text
        cur.execute("SELECT id, photo_path FROM categories WHERE bot_id=? AND name=?", (bot_id, cat_name))
        row = cur.fetchone()
        if not row:
            return
        cat_id, photo_path = row # уже получили photo_path здесь!
    
        cur.execute("SELECT id, name FROM products WHERE cat_id=? AND enabled = 1 ORDER BY id", (cat_id,))
        prods = cur.fetchall()
        if not prods:
            await message.answer("В этой категории пока нет товаров.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Назад")]], resize_keyboard=True))
            return

        user_state[message.from_user.id] = {
            "type": "category_products",
            "cat_id": cat_id,
            "prods": [(p[0], p[1]) for p in prods],
            "page": 0,
            "cat_name": cat_name,
            "cat_photo_path": photo_path # используем из первого запроса
        }
    
        await show_category_products_keyboard(message, 0)
    async def show_category_products_keyboard(message: types.Message, page: int):
        uid = message.from_user.id
        state = user_state.get(uid, {})
        if state.get("type") != "category_products":
            return
    
        prods = state["prods"]
        per_page = 6
        start = page * per_page
        end = start + per_page
        current_prods = prods[start:end]
    
        keyboard = []
        for i in range(0, len(current_prods), 2):
            row = [KeyboardButton(text=current_prods[i][1])]
            if i + 1 < len(current_prods):
                row.append(KeyboardButton(text=current_prods[i+1][1]))
            keyboard.append(row)
    
        # Первая строка: стрелки + Назад + Корзина
        nav_row = []
        if page > 0:
            nav_row.append(KeyboardButton(text="⬅️"))
        nav_row.append(KeyboardButton(text="Назад"))
        nav_row.append(KeyboardButton(text="Корзина"))
        if end < len(state["prods"]):
            nav_row.append(KeyboardButton(text="➡️"))
        if nav_row:
            keyboard.append(nav_row)
    
        # Вторая строка: "На главную" по центру
        keyboard.append([KeyboardButton(text="На главную")])
    
        kb = ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    
        # Если это первое открытие категории — отправляем фото + название
        if "category_photo_message_id" not in state:
            cat_name = state.get("cat_name", "Категория")
            caption = f"<b>{cat_name}</b>"
            photo_path = state.get("cat_photo_path")
        
            if photo_path:
                sent = await message.answer_photo(FSInputFile(photo_path), caption=caption, parse_mode="HTML", reply_markup=kb)
            else:
                sent = await message.answer(caption, parse_mode="HTML", reply_markup=kb)
        
            state["category_photo_message_id"] = sent.message_id
        else:
            # При листании — редактируем только клавиатуру (фото и текст остаются)
            try:
                await bot.edit_message_reply_markup(
                    chat_id=uid,
                    message_id=state["category_photo_message_id"],
                    reply_markup=kb
                )
            except:
                # Если сообщение удалено — отправляем новое
                cat_name = state.get("cat_name", "Категория")
                caption = f"<b>{cat_name}</b>"
                photo_path = state.get("cat_photo_path")
            
                if photo_path:
                    sent = await message.answer_photo(FSInputFile(photo_path), caption=caption, parse_mode="HTML", reply_markup=kb)
                else:
                    sent = await message.answer(caption, parse_mode="HTML", reply_markup=kb)
            
                state["category_photo_message_id"] = sent.message_id
    
        state["page"] = page
    @dp.message(lambda m: m.text == "Купить" and user_state.get(m.from_user.id, {}).get("type") == "product")
    async def buy_product(message: types.Message):
        uid = message.from_user.id
        state = user_state[uid]
        cat_id = state["cat_id"]
        index = state["index"]
        cur.execute("SELECT id FROM products WHERE cat_id=? ORDER BY id LIMIT 1 OFFSET ?", (cat_id, index))
        prod_id = cur.fetchone()[0]
        cur.execute("""INSERT INTO cart (bot_id, user_id, prod_id, quantity)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(bot_id, user_id, prod_id) DO UPDATE SET quantity = quantity + 1""",
                    (bot_id, uid, prod_id))
        conn.commit()
        await message.answer("Товар добавлен в корзину!")
    @dp.message(lambda m: m.text in ["Предыдущий", "Следующий", "Назад", "На главную"]
                and user_state.get(m.from_user.id, {}).get("type") == "product")
    async def navigate_product(message: types.Message):
        uid = message.from_user.id
        state = user_state[uid]
        cat_id = state["cat_id"]
        index = state["index"]
        if message.text == "Предыдущий":
            index -= 1
        elif message.text == "Следующий":
            index += 1
        elif message.text == "Назад":
            # Возврат к списку категорий
            user_state.pop(uid, None)
            cur.execute("SELECT name FROM categories WHERE bot_id=?", (bot_id,))
            cats = cur.fetchall()
            if not cats:
                await message.answer("Категории ещё не добавлены.")
                return
            keyboard_rows = [[KeyboardButton(text=cat[0])] for cat in cats]
            keyboard_rows.append([KeyboardButton(text="Назад")]) # здесь "Назад" уже будет вести в главное меню
            kb = ReplyKeyboardMarkup(keyboard=keyboard_rows, resize_keyboard=True)
            await message.answer("Выберите категорию:", reply_markup=kb)
            return
        user_state[uid]["index"] = index
        cur.execute("SELECT id, name, price, description, photo_path FROM products WHERE cat_id=? ORDER BY id", (cat_id,))
        prods = cur.fetchall()
        await show_product(message, prods, index)
    @dp.message(lambda m: m.text == "Назад" and user_state.get(m.from_user.id) is None)
    async def back_to_main_from_categories(message: types.Message):
        await show_main_menu(message)
# @dp.message(lambda m: m.text == "Назад")
# async def back_from_anywhere(message: types.Message):
# uid = message.from_user.id
# if uid in user_state:
# user_state.pop(uid, None)
# await show_main_menu(message)
    @dp.callback_query(lambda c: c.data and c.data.startswith("order_"))
    async def process_order_status(callback: types.CallbackQuery):
        if not callback.message:
            return

        data = callback.data

        try:
            # Убираем префикс
            payload = data[6:]  # order_

            # ---- ПРАВИЛЬНЫЙ РАЗБОР CALLBACK_DATA ----
            if "*" not in payload:
                await callback.answer("Неверный формат кнопки")
                return

            action, order_id_str = payload.split("*", 1)

            try:
                order_id = int(order_id_str)
            except ValueError:
                await callback.answer("Неверный ID заказа")
                return
            # ----------------------------------------

            # Загружаем данные заказа
            cur.execute(
                "SELECT delivery_type, status FROM orders WHERE id = ? AND bot_id = ?",
                (order_id, bot_id)
            )
            row = cur.fetchone()
            if not row:
                await callback.answer("Заказ не найден")
                return

            delivery_type, current_status = row
            is_delivery = delivery_type == "Доставка"

            # === 1. Кнопка «Отменить» ===
            if action == "cancel":
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Да, отменить",
                            callback_data=f"order_cancel_confirm*{order_id}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="Нет, оставить",
                            callback_data=f"order_cancel_deny*{order_id}"
                        )
                    ]
                ])
                await callback.message.edit_reply_markup(reply_markup=kb)
                await callback.answer()
                return


            # === 2. Подтверждение отмены → причины ===
            if action == "cancel_confirm":
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Товар закончился",
                            callback_data=f"order_reason_0*{order_id}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="Проблема с доставкой",
                            callback_data=f"order_reason_1*{order_id}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="Заведение перегружено",
                            callback_data=f"order_reason_2*{order_id}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="Другое",
                            callback_data=f"order_reason_3*{order_id}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="◀ Назад",
                            callback_data=f"order_back*{order_id}"
                        )
                    ]
                ])
                await callback.message.edit_reply_markup(reply_markup=kb)
                await callback.answer()
                return


            # === 3. Отмена отклонена ===
            if action == "cancel_deny":
                kb = generate_order_kb(current_status, is_delivery, order_id)
                await callback.message.edit_reply_markup(reply_markup=kb)
                await callback.answer()
                return

            # === 4. Причина отмены ===
            if action.startswith("reason_"):
                try:
                    reason_index = int(action.split("_")[1])
                except:
                    reason_index = 0

                reasons = [
                    "Товар закончился",
                    "Проблема с доставкой",
                    "Заведение перегружено",
                    "Другое"
                ]
                reason = reasons[reason_index % len(reasons)]

                cur.execute(
                    "UPDATE orders SET status = 'cancelled' WHERE id = ? AND bot_id = ?",
                    (order_id, bot_id)
                )
                conn.commit()

                # Уведомление клиенту
                cur.execute("SELECT user_id FROM orders WHERE id = ?", (order_id,))
                row = cur.fetchone()
                if row:
                    try:
                        await bot.send_message(
                            row[0],
                            f"Извините, заказ №{order_id} отменён.\nПричина: {reason}"
                        )
                    except:
                        pass

                new_text = callback.message.text + f"\n\n❌ Заказ отменён\nПричина: {reason}"
                await callback.message.edit_text(new_text, reply_markup=None)
                await callback.answer("Заказ отменён")
                return

            # === 5. Назад ===
            if action == "back":
                kb = generate_order_kb(current_status, is_delivery, order_id)
                await callback.message.edit_reply_markup(reply_markup=kb)
                await callback.answer()
                return

            # === 6. Выполнение заказа ===
            if action == "complete":
                cur.execute(
                    "UPDATE orders SET status = 'completed' WHERE id = ? AND bot_id = ?",
                    (order_id, bot_id)
                )
                conn.commit()

                new_text = callback.message.text + "\n\n✅ Заказ выполнен"
                await callback.message.edit_text(new_text, reply_markup=None)
                await callback.answer()
                return

            # === 7. Стандартные статусы ===
            if is_delivery:
                allowed = {
                    "new": ["accept"],
                    "accepted": ["cooking"],
                    "cooking": ["ontheway"],
                    "ontheway": ["complete"]
                }
                status_map = {
                    "accept": ("accepted", "Принят"),
                    "cooking": ("cooking", "Готовится"),
                    "ontheway": ("ontheway", "Курьер в пути"),
                    "complete": ("completed", "Выполнен")
                }
            else:
                allowed = {
                    "new": ["accept"],
                    "accepted": ["cooking"],
                    "cooking": ["ready"],
                    "ready": ["complete"]
                }
                status_map = {
                    "accept": ("accepted", "Принят"),
                    "cooking": ("cooking", "Готовится"),
                    "ready": ("ready", "Готов к выдаче"),
                    "complete": ("completed", "Выполнен")
                }

            if action not in allowed.get(current_status, []):
                await callback.answer("Действие недоступно")
                return

            new_status, text = status_map[action]
            cur.execute(
                "UPDATE orders SET status = ? WHERE id = ? AND bot_id = ?",
                (new_status, order_id, bot_id)
            )
            conn.commit()

            new_text = callback.message.text.split("\n\nСтатус:")[0] + f"\n\nСтатус: {text}"
            kb = generate_order_kb(new_status, is_delivery, order_id)
            await callback.message.edit_text(new_text, reply_markup=kb)
            await callback.answer("Обновлено!")

        except Exception as e:
            print("Ошибка в process_order_status:", e)
            await callback.answer("Ошибка обработки", show_alert=True)

    # === ЗАПУСК ===
    active_bots[bot_id] = {"bot": bot, "dp": dp}
    asyncio.create_task(dp.start_polling(bot))
    print(f"Бот @{username} (ID: {bot_id}) — полностью готов!")
# === АВТООТМЕНА ЗАКАЗОВ ===
    async def auto_cancel_task():
        while True:
            await asyncio.sleep(60) # проверяем каждую минуту
            try:
                current_unix = int(time.time())
                cur.execute("""SELECT o.id, o.user_id, o.cafe_message_id, b.notify_chat_id, b.auto_cancel_minutes, o.total, o.delivery_type
                            FROM orders o
                            JOIN bots b ON o.bot_id = b.bot_id
                            WHERE o.status = 'new'
                            AND b.auto_cancel_enabled = 1
                            AND o.created_at + (b.auto_cancel_minutes * 60) < ?""", (current_unix,))
                expired = cur.fetchall()
                for order_id, client_id, cafe_msg_id, notify_chat, minutes, total, delivery_type in expired:
                    cur.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
                    conn.commit()
                
                    # Уведомление клиенту
                    try:
                        await bot.send_message(client_id, f"Заказ №{order_id} автоматически отменён 😔\nНе получили подтверждение от кафе в течение {minutes} минут.")
                    except: pass
                
                    # Если есть чат сотрудников — редактируем старое сообщение + новое
                    if cafe_msg_id and notify_chat:
                        try:
                            # Собираем список товаров
                            items_text = ""
                            cur.execute("SELECT name, quantity, price FROM order_items WHERE order_id = ?", (order_id,))
                            for n, q, p in cur.fetchall():
                                items_text += f"• {n} ×{q} — {p*q} ₽\n"
                        
                            # Редактируем старое сообщение
                            await bot.edit_message_text(
                                chat_id=int(notify_chat),
                                message_id=cafe_msg_id,
                                text=f"Заказ №{order_id} — АВТООТМЕНА\n"
                                    f"Тип: {delivery_type} | Сумма: {total} ₽\n\n"
                                    f"{items_text}"
                                    f"Автоматическая отмена (не подтверждён за {minutes} мин)",
                                reply_markup=None
                            )
                        
                            # Новое сообщение для уведомления
                            await bot.send_message(
                                int(notify_chat),
                                f"АВТООТМЕНА №{order_id}\n(не подтверждён за {minutes} мин)❌"
                            )
                        except Exception as e:
                            print("Ошибка редактирования при автоотмене:", e)
            except Exception as e:
                print("Ошибка автоотмены:", e)
    asyncio.create_task(auto_cancel_task())
# === Автозапуск всех ботов при старте ===
@app.on_event("startup")
async def on_startup():
    cur.execute("SELECT bot_id, token, username FROM bots")
    for bot_id, token, username in cur.fetchall():
        if bot_id not in active_bots:
            await launch_bot(bot_id, token, username)
# === Аутентификация ===
def get_current_user(request: Request):
    user = request.cookies.get("user")
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user
# === Маршруты ===
@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})
@app.get("/register")
async def register_get(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})
@app.post("/save_bonus_settings")
async def save_bonus_settings(
    bot_id: int = Form(),
    bonuses_enabled: str = Form("off"),
    bonus_percent: int = Form(10),
    max_bonus_pay_percent: int = Form(30),
    min_order_for_bonus: int = Form(0),
    bonus_expire_days: int = Form(0),
    welcome_bonus: int = Form(0),
    user: str = Depends(get_current_user)
):
    cur.execute("SELECT 1 FROM bots WHERE bot_id=? AND owner=?", (bot_id, user))
    if cur.fetchone():
        enabled = 1 if bonuses_enabled == "on" else 0
        cur.execute("""UPDATE bots SET
            bonuses_enabled = ?,
            bonus_percent = ?,
            max_bonus_pay_percent = ?,
            min_order_for_bonus = ?,
            bonus_expire_days = ?,
            welcome_bonus = ?
            WHERE bot_id = ?""",
            (enabled, bonus_percent, max_bonus_pay_percent, min_order_for_bonus, bonus_expire_days, welcome_bonus, bot_id))
        conn.commit()
    return RedirectResponse("/dashboard?msg=Настройки бонусной системы сохранены!", status_code=303)
@app.post("/upload_category_photo")
async def upload_category_photo(
    bot_id: int = Form(),
    cat_id: int = Form(),
    photo: UploadFile = File(None),
    user: str = Depends(get_current_user)
):
    # Проверяем права
    cur.execute("SELECT 1 FROM categories c JOIN bots b ON c.bot_id = b.bot_id WHERE c.id=? AND b.owner=?", (cat_id, user))
    if not cur.fetchone():
        return RedirectResponse("/dashboard", status_code=303)

    photo_path = None
    if photo and photo.filename:
        photo_bytes = await photo.read()
        os.makedirs("static/categories", exist_ok=True)
        photo_path = f"static/categories/cat_{cat_id}*{int(time.time())}.jpg"
        with open(photo_path, "wb") as f:
            f.write(photo_bytes)

    # Удаляем старое фото, если было
    cur.execute("SELECT photo_path FROM categories WHERE id=?", (cat_id,))
    old = cur.fetchone()
    if old and old[0] and os.path.exists(old[0]):
        try: os.remove(old[0])
        except: pass

    cur.execute("UPDATE categories SET photo_path = ? WHERE id = ?", (photo_path, cat_id))
    conn.commit()

    return RedirectResponse("/dashboard?msg=Фото категории загружено!", status_code=303)
@app.post("/delete_category_photo")
async def delete_category_photo(
    bot_id: int = Form(),
    cat_id: int = Form(),
    user: str = Depends(get_current_user)
):
    cur.execute("SELECT 1 FROM categories c JOIN bots b ON c.bot_id = b.bot_id WHERE c.id=? AND b.owner=?", (cat_id, user))
    if not cur.fetchone():
        return RedirectResponse("/dashboard", status_code=303)

    cur.execute("SELECT photo_path FROM categories WHERE id=?", (cat_id,))
    row = cur.fetchone()
    if row and row[0]:
        if os.path.exists(row[0]):
            try: os.remove(row[0])
            except: pass
        cur.execute("UPDATE categories SET photo_path = NULL WHERE id = ?", (cat_id,))
        conn.commit()

    return RedirectResponse("/dashboard?msg=Фото категории удалено!", status_code=303)
@app.post("/upload_menu_photo")
async def upload_menu_photo(
    bot_id: int = Form(),
    photo: UploadFile = File(None),
    user: str = Depends(get_current_user)
):
    cur.execute("SELECT bot_id, menu_photo_path FROM bots WHERE bot_id=? AND owner=?", (bot_id, user))
    row = cur.fetchone()
    if row:
        old_path = row[1]
        photo_path = None
        if photo and photo.filename:
            photo_bytes = await photo.read()
            os.makedirs("static/menu", exist_ok=True)
            photo_path = f"static/menu/{bot_id}*{int(time.time())}.jpg"
            with open(photo_path, "wb") as f:
                f.write(photo_bytes)
    
        cur.execute("UPDATE bots SET menu_photo_path = ? WHERE bot_id = ?", (photo_path, bot_id))
        conn.commit()
    
        if old_path and os.path.exists(old_path):
            try: os.remove(old_path)
            except: pass
    return RedirectResponse("/dashboard?msg=Фото меню загружено!", status_code=303)
@app.post("/save_auto_cancel")
async def save_auto_cancel(
    bot_id: int = Form(),
    minutes: int = Form(60),
    auto_cancel_enabled: str = Form("off"),
    user: str = Depends(get_current_user)
):
    cur.execute("SELECT 1 FROM bots WHERE bot_id=? AND owner=?", (bot_id, user))
    if cur.fetchone():
        enabled = 1 if auto_cancel_enabled == "on" else 0
        if 10 <= minutes <= 120:
            cur.execute("""UPDATE bots SET
                auto_cancel_minutes = ?,
                auto_cancel_enabled = ?
                WHERE bot_id = ?""", (minutes, enabled, bot_id))
            conn.commit()
    return RedirectResponse("/dashboard?msg=Автоотмена сохранена!", status_code=303)
@app.post("/save_work_time")
async def save_work_time(
    bot_id: int = Form(),
    timezone: str = Form("Europe/Moscow"),
    work_start: str = Form(None),
    work_end: str = Form(None),
    restrict_orders: str = Form("off"),
    user: str = Depends(get_current_user)
):
    cur.execute("SELECT 1 FROM bots WHERE bot_id=? AND owner=?", (bot_id, user))
    if cur.fetchone():
        cur.execute("""UPDATE bots SET
            timezone = ?,
            work_start = ?,
            work_end = ?,
            restrict_orders = ?
            WHERE bot_id = ?""",
            (timezone, work_start or None, work_end or None, 1 if restrict_orders == "on" else 0, bot_id))
        conn.commit()
    return RedirectResponse("/dashboard?msg=Время работы сохранено!", status_code=303)
@app.post("/toggle_product")
async def toggle_product(
    prod_id: int = Form(),
    enabled: str = Form("off"),
    user: str = Depends(get_current_user)
):
    cur.execute("SELECT 1 FROM products p JOIN bots b ON p.bot_id = b.bot_id WHERE p.id = ? AND b.owner = ?", (prod_id, user))
    if cur.fetchone():
        cur.execute("UPDATE products SET enabled = ? WHERE id = ?", (1 if enabled == "on" else 0, prod_id))
        conn.commit()
    return RedirectResponse("/dashboard?msg=Товар обновлён!", status_code=303)
@app.post("/toggle_order_type")
async def toggle_order_type(
    bot_id: int = Form(),
    in_hall: str = Form("off"),
    takeaway: str = Form("off"),
    delivery: str = Form("off"),
    user: str = Depends(get_current_user)
):
    cur.execute("SELECT 1 FROM bots WHERE bot_id=? AND owner=?", (bot_id, user))
    if not cur.fetchone():
        return RedirectResponse("/dashboard", status_code=303)
    cur.execute("""UPDATE bots SET
        allow_in_hall = ?,
        allow_takeaway = ?,
        allow_delivery = ?
        WHERE bot_id = ?""",
        (1 if in_hall == "on" else 0,
        1 if takeaway == "on" else 0,
        1 if delivery == "on" else 0,
        bot_id))
    conn.commit()
    return RedirectResponse("/dashboard?msg=Настройки сохранены!", status_code=303)
@app.post("/register")
async def register_post(username: str = Form(), password: str = Form()):
    try:
        cur.execute("INSERT INTO accounts (username, password) VALUES (?, ?)",
                    (username, hash_password(password)))
        conn.commit()
        return RedirectResponse("/login", status_code=303)
    except sqlite3.IntegrityError:
        return HTMLResponse("Этот логин уже занят")
@app.get("/login")
async def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})
@app.post("/login")
async def login_post(username: str = Form(), password: str = Form()):
    cur.execute("SELECT password FROM accounts WHERE username=?", (username,))
    row = cur.fetchone()
    if row and row[0] == hash_password(password):
        resp = RedirectResponse("/dashboard", status_code=303)
        resp.set_cookie("user", username, httponly=True, max_age=604800)
        return resp
    return HTMLResponse("Неверный логин или пароль")
# Добавить категорию
@app.post("/add_category")
async def add_category(bot_id: int = Form(), name: str = Form(), user: str = Depends(get_current_user)):
    cur.execute("SELECT bot_id FROM bots WHERE bot_id=? AND owner=?", (bot_id, user))
    if cur.fetchone():
        cur.execute("INSERT INTO categories (bot_id, name) VALUES (?, ?)", (bot_id, name))
        conn.commit()
    return RedirectResponse("/dashboard", status_code=303)
# Удалить категорию
@app.post("/delete_category")
async def delete_category(cat_id: int = Form(), bot_id: int = Form(), user: str = Depends(get_current_user)):
    cur.execute("DELETE FROM categories WHERE id=? AND bot_id IN (SELECT bot_id FROM bots WHERE owner=?)", (cat_id, user))
    conn.commit()
    return RedirectResponse("/dashboard", status_code=303)
@app.get("/create")
async def create_get(request: Request, user: str = Depends(get_current_user)):
    return templates.TemplateResponse("create.html", {"request": request})
@app.post("/create")
async def create_post(token: str = Form(), user: str = Depends(get_current_user)):
    try:
        bot = Bot(token=token)
        me = await bot.get_me()
        cur.execute(
            "INSERT OR REPLACE INTO bots (bot_id, token, username, owner, about) VALUES (?,?,?,?,?)",
            (me.id, token, me.username, user, "Мы — крутой магазин!")
        )
        conn.commit()
        await bot.session.close()
        await launch_bot(me.id, token, me.username)
        return RedirectResponse("/dashboard", status_code=303)
    except Exception as e:
        return HTMLResponse(f"Ошибка: {e}")
#добавить товары в категорию
import os
from fastapi import UploadFile, File
# Создаём папку для фото
os.makedirs("static/products", exist_ok=True)
@app.post("/add_product")
async def add_product(
    bot_id: int = Form(),
    cat_id: int = Form(),
    name: str = Form(),
    price: int = Form(),
    description: str = Form(None),
    photo: UploadFile = File(None),
    user: str = Depends(get_current_user)
):
    cur.execute("SELECT bot_id FROM bots WHERE bot_id=? AND owner=?", (bot_id, user))
    if not cur.fetchone():
        return RedirectResponse("/dashboard", status_code=303)
    photo_path = None
    if photo and photo.filename:
        photo_bytes = await photo.read()
        photo_path = f"static/products/{bot_id}*{cat_id}*{int(time.time())}.jpg"
        with open(photo_path, "wb") as f:
            f.write(photo_bytes)
    cur.execute("""
        INSERT INTO products (bot_id, cat_id, name, price, description, photo_path)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (bot_id, cat_id, name, price, description or "", photo_path))
    conn.commit()
    return RedirectResponse("/dashboard", status_code=303)
@app.post("/delete_product")
async def delete_product(prod_id: int = Form(), user: str = Depends(get_current_user)):
    cur.execute("""SELECT products.photo_path, bots.bot_id
                FROM products
                JOIN bots ON products.bot_id = bots.bot_id
                WHERE products.id = ? AND bots.owner = ?""", (prod_id, user))
    row = cur.fetchone()
    if row:
        photo_path, bot_id_from_db = row
        if photo_path:
            try:
                os.remove(photo_path)
            except:
                pass # если файл уже удалён — пох
        cur.execute("DELETE FROM products WHERE id = ?", (prod_id,))
        conn.commit()
    return RedirectResponse("/dashboard", status_code=303)
# Передаём товары в шаблон
@app.get("/dashboard")
async def dashboard(request: Request, user: str = Depends(get_current_user)):
    cur.execute("""SELECT bot_id, username, about,
                    notify_chat_id,
                    allow_in_hall, allow_takeaway, allow_delivery,
                    timezone, work_start, work_end, restrict_orders,
                    auto_cancel_minutes, auto_cancel_enabled,
                    bonuses_enabled,
                    bonus_percent,
                    max_bonus_pay_percent,
                    min_order_for_bonus,
                    bonus_expire_days,
                    welcome_bonus
            FROM bots WHERE owner=?""", (user,))
    bots = cur.fetchall()
    categories = {}
    products = {}
    # Функция для получения фото меню (доступна в шаблоне)
    def get_menu_photos(bot_id):
        cur.execute("SELECT id, photo_path FROM menu_photos WHERE bot_id=? ORDER BY sort_order, id", (bot_id,))
        return [{"id": r[0], "photo_path": r[1]} for r in cur.fetchall()]
    for bot in bots:
        bot_id = bot[0]
        cur.execute("SELECT id, bot_id, name, photo_path FROM categories WHERE bot_id=?", (bot_id,))
        categories[bot_id] = cur.fetchall()
        # Продукты
        cur.execute("SELECT id, bot_id, cat_id, name, price, description, photo_path, enabled FROM products WHERE bot_id=?", (bot_id,))
        all_prods = cur.fetchall()
        for p in all_prods:
            cat_id = p[2]
            if cat_id not in products:
                products[cat_id] = []
            products[cat_id].append(p)
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "bots": bots,
        "categories": categories,
        "products": products,
        "get_menu_photos": get_menu_photos # ← ЭТО ГЛАВНОЕ! Передаём функцию в шаблон
    })
@app.post("/toggle_bonuses")
async def toggle_bonuses(
    bot_id: int = Form(),
    bonuses_enabled: str = Form("off"),
    user: str = Depends(get_current_user)
):
    cur.execute("SELECT 1 FROM bots WHERE bot_id=? AND owner=?", (bot_id, user))
    if cur.fetchone():
        enabled = 1 if bonuses_enabled == "on" else 0
        cur.execute("UPDATE bots SET bonuses_enabled = ? WHERE bot_id = ?", (enabled, bot_id))
        conn.commit()
    return RedirectResponse("/dashboard?msg=Бонусная система обновлена!", status_code=303)
@app.post("/upload_menu_photos")
async def upload_menu_photos(
    bot_id: int = Form(),
    photos: List[UploadFile] = File([]),
    user: str = Depends(get_current_user)
):
    cur.execute("SELECT 1 FROM bots WHERE bot_id=? AND owner=?", (bot_id, user))
    if cur.fetchone() and photos:
        os.makedirs("static/menu", exist_ok=True)
        for photo in photos:
            if photo.filename:
                photo_bytes = await photo.read()
                # Добавляем уникальное имя, чтобы не перезаписывать
                photo_path = f"static/menu/{bot_id}*{int(time.time())}*{photo.filename}"
                with open(photo_path, "wb") as f:
                    f.write(photo_bytes)
                cur.execute("INSERT INTO menu_photos (bot_id, photo_path) VALUES (?, ?)", (bot_id, photo_path))
        conn.commit()
    return RedirectResponse("/dashboard?msg=Фото меню загружены!", status_code=303)
@app.post("/delete_menu_photo")
async def delete_menu_photo(
    bot_id: int = Form(),
    photo_id: int = Form(),
    user: str = Depends(get_current_user)
):
    cur.execute("SELECT photo_path FROM menu_photos WHERE id=? AND bot_id IN (SELECT bot_id FROM bots WHERE owner=?)", (photo_id, user))
    row = cur.fetchone()
    if row:
        if os.path.exists(row[0]):
            try: os.remove(row[0])
            except: pass
        cur.execute("DELETE FROM menu_photos WHERE id=?", (photo_id,))
        conn.commit()
    return RedirectResponse("/dashboard", status_code=303)
@app.post("/update_about")
async def update_about(bot_id: int = Form(), about: str = Form(), user: str = Depends(get_current_user)):
    cur.execute("UPDATE bots SET about=? WHERE bot_id=? AND owner=?", (about, bot_id, user))
    conn.commit()
    return RedirectResponse("/dashboard", status_code=303)
from fastapi import UploadFile, File
from aiogram.types import InputFile
from io import BytesIO
from aiogram.types import BufferedInputFile # ← ЭТО ГЛАВНОЕ!
@app.post("/send_broadcast")
async def send_broadcast(
    bot_id: int = Form(),
    message: str = Form(""),
    photo: UploadFile | None = File(None),
    user: str = Depends(get_current_user)
):
    # Проверяем владельца
    cur.execute("SELECT token, username FROM bots WHERE bot_id = ? AND owner = ?", (bot_id, user))
    row = cur.fetchone()
    if not row:
        return HTMLResponse("Доступ запрещён", status_code=403)
    token, username = row
    # Запускаем бот если нужно
    if bot_id not in active_bots:
        await launch_bot(bot_id, token, username)
        await asyncio.sleep(2)
    bot = active_bots[bot_id]["bot"]
    # Клиенты
    cur.execute("SELECT user_id FROM clients WHERE bot_id = ?", (bot_id,))
    user_ids = [r[0] for r in cur.fetchall()]
    if not user_ids:
        return RedirectResponse(f"/dashboard?msg=Нет клиентов для рассылки&bot={bot_id}", status_code=303)
    sent = 0
    photo_file = None
    # Если загружено фото — готовим его правильно
    if photo and photo.filename:
        photo_bytes = await photo.read()
        photo_file = BufferedInputFile(photo_bytes, filename=photo.filename)
    # Отправляем всем
    for uid in user_ids:
        try:
            if photo_file:
                await bot.send_photo(
                    chat_id=uid,
                    photo=photo_file,
                    caption=message if message.strip() else " "
                )
            elif message.strip():
                await bot.send_message(chat_id=uid, text=message)
            sent += 1
            await asyncio.sleep(0.04)
        except Exception as e:
            pass # пропускаем заблокировавших бота
    result = f"Рассылка завершена! Отправлено: {sent} из {len(user_ids)}"
    if photo_file:
        result += " (с фото)"
    return RedirectResponse(f"/dashboard?msg={result}&bot={bot_id}", status_code=303)
import time
from fastapi import UploadFile, File
# Первый клик — "Удалить" → перенаправляем с подтверждением
@app.post("/delete_bot")
async def delete_bot_request(bot_id: int = Form(), user: str = Depends(get_current_user)):
    # Проверяем, что бот принадлежит пользователю
    cur.execute("SELECT bot_id FROM bots WHERE bot_id=? AND owner=?", (bot_id, user))
    if cur.fetchone():
        return RedirectResponse(f"/dashboard?confirm_delete=1&bot={bot_id}", status_code=303)
    return RedirectResponse("/dashboard", status_code=303)
# Подтверждение — "ДА, УДАЛИТЬ"
@app.post("/confirm_delete_bot")
async def confirm_delete_bot(bot_id: int = Form(), user: str = Depends(get_current_user)):
    # Удаляем из базы
    cur.execute("DELETE FROM bots WHERE bot_id=? AND owner=?", (bot_id, user))
    cur.execute("DELETE FROM clients WHERE bot_id=?", (bot_id,))
    cur.execute("DELETE FROM categories WHERE bot_id=?", (bot_id,))
    conn.commit()
    # Останавливаем бота в памяти
    if bot_id in active_bots:
        try:
            await active_bots[bot_id]["bot"].session.close()
        except:
            pass
        del active_bots[bot_id]
    return RedirectResponse(f"/dashboard?msg=Бот успешно удалён!", status_code=303)
# === РЕДАКТИРОВАНИЕ ТОВАРА ===
@app.get("/edit_product/{prod_id}")
async def edit_product_get(prod_id: int, request: Request, user: str = Depends(get_current_user)):
    cur.execute("""
        SELECT p.id, p.name, p.price, p.description, p.photo_path, p.cat_id, b.bot_id
        FROM products p
        JOIN bots b ON p.bot_id = b.bot_id
        WHERE p.id = ? AND b.owner = ?
    """, (prod_id, user))
    prod = cur.fetchone()
    if not prod:
        return RedirectResponse("/dashboard", status_code=303)

    # Получаем категории этого бота для выпадающего списка
    cur.execute("SELECT id, name FROM categories WHERE bot_id = ?", (prod[6],))
    categories_list = cur.fetchall()

    return templates.TemplateResponse("edit_product.html", {
        "request": request,
        "prod": prod, # (id, name, price, desc, photo_path, cat_id, bot_id)
        "categories": categories_list
    })
@app.post("/update_product")
async def update_product(
    prod_id: int = Form(),
    name: str = Form(),
    price: int = Form(),
    description: str = Form(None),
    cat_id: int = Form(),
    photo: UploadFile = File(None),
    delete_photo: str = Form(None), # галочка "удалить фото"
    user: str = Depends(get_current_user)
):
    # Проверяем, что товар принадлежит пользователю
    cur.execute("SELECT p.photo_path, p.bot_id, b.owner FROM products p JOIN bots b ON p.bot_id = b.bot_id WHERE p.id = ?", (prod_id,))
    row = cur.fetchone()
    if not row or row[2] != user:
        return RedirectResponse("/dashboard", status_code=303)
    photo_path = row[0] # старое фото
    # Если загружено новое фото — сохраняем
    if photo and photo.filename:
        photo_bytes = await photo.read()
        photo_path = f"static/products/{row[1]}*{cat_id}*{int(time.time())}.jpg"
        with open(photo_path, "wb") as f:
            f.write(photo_bytes)
        # Удаляем старое, если было
        if row[0] and os.path.exists(row[0]):
            try: os.remove(row[0])
            except: pass
    # Если нажата галочка "удалить фото"
    elif delete_photo == "on" and photo_path:
        try: os.remove(photo_path)
        except: pass
        photo_path = None
    # Обновляем товар
    cur.execute("""
        UPDATE products
        SET name = ?, price = ?, description = ?, photo_path = ?, cat_id = ?
        WHERE id = ?
    """, (name, price, description or "", photo_path, cat_id, prod_id))
    conn.commit()
    return RedirectResponse("/dashboard?msg=Товар успешно обновлён!", status_code=303)
# === КОРЗИНА ===
@app.post("/add_to_cart")
async def add_to_cart(
    bot_id: int = Form(),
    prod_id: int = Form(),
    quantity: int = Form(1),
    user: str = Depends(get_current_user)
):
    uid = user # пока используем username как идентификатор (можно потом заменить на telegram_id)
    cur.execute("""
        INSERT INTO clients (bot_id, user_id, code)
        VALUES (?, ?, ?) ON CONFLICT DO NOTHING
    """, (bot_id, uid, f"web_{uid}"))

    cur.execute("""
        INSERT INTO cart (bot_id, user_id, prod_id, quantity)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(bot_id, user_id, prod_id) DO UPDATE SET quantity = quantity + ?
    """, (bot_id, uid, prod_id, quantity, quantity))
    conn.commit()
    return RedirectResponse("/dashboard", status_code=303)
@app.get("/cart")
async def view_cart(request: Request, user: str = Depends(get_current_user)):
    uid = user
    cur.execute("""
        SELECT c.prod_id, p.name, p.price, p.photo_path, p.description, c.quantity, c.bot_id
        FROM cart c
        JOIN products p ON c.prod_id = p.id
        WHERE c.user_id = ?
    """, (uid,))
    items = cur.fetchall()

    total = sum(item[2] * item[5] for item in items) # цена × кол-во

    return templates.TemplateResponse("cart.html", {
        "request": request,
        "items": items,
        "total": total,
        "user": user
    })
@app.post("/update_cart")
async def update_cart(
    prod_id: int = Form(),
    action: str = Form(), # "plus", "minus", "delete"
    user: str = Depends(get_current_user)
):
    uid = user
    if action == "delete":
        cur.execute("DELETE FROM cart WHERE user_id = ? AND prod_id = ?", (uid, prod_id))
    elif action == "plus":
        cur.execute("UPDATE cart SET quantity = quantity + 1 WHERE user_id = ? AND prod_id = ?", (uid, prod_id))
    elif action == "minus":
        cur.execute("""
            UPDATE cart SET quantity = quantity - 1
            WHERE user_id = ? AND prod_id = ? AND quantity > 1
        """, (uid, prod_id))
        cur.execute("DELETE FROM cart WHERE user_id = ? AND prod_id = ? AND quantity <= 0", (uid, prod_id))
    conn.commit()
    return RedirectResponse("/cart", status_code=303)
@app.post("/clear_cart")
async def clear_cart(user: str = Depends(get_current_user)):
    cur.execute("DELETE FROM cart WHERE user_id = ?", (user,))
    conn.commit()
    return RedirectResponse("/cart", status_code=303)
@app.get("/logout")
async def logout():
    resp = RedirectResponse("/")
    resp.delete_cookie("user")
    return resp
@app.post("/save_notify_chat")
async def save_notify_chat(
    bot_id: int = Form(),
    notify_chat_id: str = Form(""),
    user: str = Depends(get_current_user)
):
    # Проверка, что бот принадлежит пользователю
    cur.execute("SELECT 1 FROM bots WHERE bot_id=? AND owner=?", (bot_id, user))
    if cur.fetchone():
        cur.execute("UPDATE bots SET notify_chat_id=? WHERE bot_id=?",
                (notify_chat_id.strip() or None, bot_id))
        conn.commit()
    return RedirectResponse("/dashboard?msg=Чат для заказов сохранён!", status_code=303)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
