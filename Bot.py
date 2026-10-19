# -*- coding: utf-8 -*-
"""
Telegram-бот «Голубой кит» (aiogram 3.x)
"""

import asyncio
import html
import json
import logging
import os
import time
import re

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

# ---------------------------------------------------------------------------
# Конфиг
# ---------------------------------------------------------------------------
BOT_TOKEN = "8583008583:AAEJAyJA1rICvWrd5Zfmi6wk2EfV-g4yN4Q"
ADMIN_ID = 8788765197

DB_FILE = "users_db.json"
LINE = "━━━━━━━━━━━━━━━━━━━━"

# {curator_id: user_id} — в каком чате сейчас сидит куратор
ACTIVE_CHATS = {} 
# {user_id: last_msg_time} — для антиспама
LAST_MSG_TIME = {}

router = Router()

# ---------------------------------------------------------------------------
# База данных
# ---------------------------------------------------------------------------
def load_db():
    default_db = {"users": {}, "curators": [], "chats": {}}
    if not os.path.exists(DB_FILE):
        return default_db
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "chats" not in data: data["chats"] = {}
            return data
    except Exception:
        return default_db

def save_db():
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(DB, f, ensure_ascii=False, indent=2)

DB = load_db()

def get_status(user_id: int) -> str | None:
    return DB["users"].get(str(user_id))

def set_status(user_id: int, status: str):
    DB["users"][str(user_id)] = status
    save_db()

def is_staff(user_id: int) -> bool:
    return user_id == ADMIN_ID or user_id in DB["curators"]

# ---------------------------------------------------------------------------
# FSM
# ---------------------------------------------------------------------------
class Form(StatesGroup):
    waiting_form = State()

async def try_send(bot: Bot, user_id: int, text: str, parse_mode="HTML") -> tuple[bool, str]:
    try:
        await bot.send_message(user_id, text, parse_mode=parse_mode)
        return True, ""
    except Exception as e:
        return False, str(e)

# ===========================================================================
# АДМИН-КОМАНДЫ
# ===========================================================================
@router.message(Command("list"), F.from_user.id == ADMIN_ID)
async def cmd_admin_list(message: Message):
    text = (
        f"👑 <b>АДМИН-ПАНЕЛЬ</b>\n{LINE}\n"
        "<code>/ban &lt;id&gt; &lt;причина&gt;</code> — забанить\n"
        "<code>/unban &lt;id&gt;</code> — разбанить\n"
        "<code>/old &lt;id&gt; &lt;сообщение&gt;</code> — снять куратора\n"
        "<code>/end &lt;id&gt; &lt;причина&gt;</code> — завершить диалог\n"
        "<code>/new &lt;id&gt; &lt;сообщение&gt;</code> — назначить куратора\n"
        "<code>/chats</code> — меню активных чатов\n"
        f"{LINE}\n"
        "💡 <i>Чтобы ответить в чате, просто напишите текст или используйте Reply.</i>"
    )
    await message.answer(text, parse_mode="HTML")

@router.message(Command("ban"), F.from_user.id == ADMIN_ID)
async def cmd_admin_ban(message: Message, command: CommandObject):
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        return await message.answer("Формат: <code>/ban &lt;id&gt; &lt;причина&gt;</code>", parse_mode="HTML")
    uid, reason = int(parts[0]), parts[1]
    set_status(uid, "banned")
    await try_send(message.bot, uid, f"🚫 <b>Вы были забанены.</b>\n<b>Причина:</b> {html.escape(reason)}")
    await message.answer(f"✅ Пользователь <code>{uid}</code> забанен.", parse_mode="HTML")

@router.message(Command("unban"), F.from_user.id == ADMIN_ID)
async def cmd_admin_unban(message: Message, command: CommandObject):
    uid_str = (command.args or "").strip()
    if not uid_str.isdigit():
        return await message.answer("Формат: <code>/unban &lt;id&gt;</code>", parse_mode="HTML")
    uid = int(uid_str)
    if get_status(uid) == "banned":
        set_status(uid, "rejected")
        await try_send(message.bot, uid, "🔓 <b>Вы были разбанены.</b>\nВы можете отправить новую анкету через /start")
        await message.answer(f"✅ Пользователь <code>{uid}</code> разбанен.", parse_mode="HTML")
    else:
        await message.answer(f"⚠️ Пользователь <code>{uid}</code> не находится в бане.", parse_mode="HTML")

@router.message(Command("end"), F.from_user.id == ADMIN_ID)
async def cmd_admin_end(message: Message, command: CommandObject):
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        return await message.answer("Формат: <code>/end &lt;id&gt; &lt;причина&gt;</code>", parse_mode="HTML")
    uid, reason = int(parts[0]), parts[1]
    set_status(uid, "rejected")
    if str(uid) in DB["chats"]:
        del DB["chats"][str(uid)]
        save_db()
    await try_send(message.bot, uid, f"🛑 <b>Диалог завершен куратором.</b>\n<b>Причина:</b> {html.escape(reason)}\n\nДля новой попытки отправьте /start")
    await message.answer(f"✅ Диалог с <code>{uid}</code> завершен.", parse_mode="HTML")

@router.message(Command("new"), F.from_user.id == ADMIN_ID)
async def cmd_admin_new(message: Message, command: CommandObject):
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        return await message.answer("Формат: <code>/new &lt;id&gt; &lt;сообщение&gt;</code>", parse_mode="HTML")
    uid, msg = int(parts[0]), parts[1]
    if uid not in DB["curators"]:
        DB["curators"].append(uid)
        save_db()
    instructions = (
        f"👋 <b>Вы назначены куратором!</b>\n{LINE}\n"
        f"<b>Сообщение от админа:</b> {html.escape(msg)}\n\n"
        "💡 <b>Ваши доступные команды:</b>\n"
        "  • <code>/chats</code> — открыть меню со списком ваших чатов\n"
        "  • <code>/s &lt;id&gt; &lt;текст&gt;</code> — написать игроку напрямую\n\n"
        "🔹 <i>Вы также можете зайти в чат через /chats и общаться с игроком как в обычном мессенджере.</i>"
    )
    await try_send(message.bot, uid, instructions)
    await message.answer(f"✅ Пользователь <code>{uid}</code> назначен куратором.", parse_mode="HTML")

@router.message(Command("old"), F.from_user.id == ADMIN_ID)
async def cmd_admin_old(message: Message, command: CommandObject):
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        return await message.answer("Формат: <code>/old &lt;id&gt; &lt;сообщение&gt;</code>", parse_mode="HTML")
    uid, msg = int(parts[0]), parts[1]
    if uid in DB["curators"]:
        DB["curators"].remove(uid)
        save_db()
    await try_send(message.bot, uid, f"❌ <b>Вы больше не куратор.</b>\n<b>Сообщение:</b> {html.escape(msg)}")
    await message.answer(f"✅ Пользователь <code>{uid}</code> снят с должности.", parse_mode="HTML")


# ===========================================================================
# КОМАНДЫ ДЛЯ ПЕРСОНАЛА (ЧАТЫ)
# ===========================================================================
@router.message(Command("chats"), F.from_user.id.in_({ADMIN_ID, *DB["curators"]}))
async def cmd_staff_chats(message: Message):
    staff_id = message.from_user.id
    kb = InlineKeyboardBuilder()
    found = False
    for uid_str, chat_data in DB["chats"].items():
        cid = chat_data.get("curator_id")
        if staff_id == ADMIN_ID or cid == staff_id:
            uname = chat_data.get("username", "игрок")
            kb.button(text=f"📁 @{uname} (id: {uid_str})", callback_data=f"chat_open:{uid_str}")
            found = True
            
    if not found:
        return await message.answer("У вас пока нет активных чатов.", parse_mode="HTML")
        
    kb.adjust(1)
    kb.row(InlineKeyboardBuilder().button(text="❌ Закрыть меню", callback_data="chat_close_menu").as_markup().inline_keyboard[0][0])
    await message.answer("🗂 <b>Выберите чат для общения:</b>", reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("chat_open:"))
async def cb_chat_open(call: CallbackQuery):
    staff_id = call.from_user.id
    uid = int(call.data.split(":")[1])
    
    chat_data = DB["chats"].get(str(uid))
    if not chat_data:
        return await call.answer("Чат не найден.", show_alert=True)
        
    if staff_id != ADMIN_ID and chat_data.get("curator_id") != staff_id:
        return await call.answer("У вас нет доступа к этому чату.", show_alert=True)

    ACTIVE_CHATS[staff_id] = uid
    await call.message.delete() # Удаляем меню
    
    uname = chat_data.get("username", "нет")
    text = (
        f"💬 <b>Вы вошли в чат</b>\n"
        f"Игрок: @{uname} (ID: <code>{uid}</code>)\n"
        f"{LINE}\n"
        f"<i>Все ваши сообщения теперь летят напрямую игроку.</i>"
    )
    kb = InlineKeyboardBuilder().button(text="🚪 Выйти из чата", callback_data="chat_leave")
    await call.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await call.answer()

    # Отправляем историю сообщений как отдельные "пузыри"
    history = chat_data.get("history", [])
    for msg in history[-5:]: # Последние 5 сообщений
        role = "👤 Игрок:" if msg["role"] == "user" else "👨‍💼 Вы:"
        count = f" (x{msg['count']})" if msg.get("count", 1) > 1 else ""
        try:
            await call.message.answer(f"{role}\n{html.escape(msg['text'])}{count}", parse_mode="HTML")
        except:
            await call.message.answer(f"{role} [Ошибка формата]")

@router.callback_query(F.data == "chat_leave")
async def cb_chat_leave(call: CallbackQuery):
    ACTIVE_CHATS.pop(call.from_user.id, None)
    await call.message.edit_text("🚪 <b>Вы вышли из чата.</b>\nИспользуйте /chats для выбора другого.", parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "chat_close_menu")
async def cb_chat_close_menu(call: CallbackQuery):
    await call.message.delete()
    await call.answer()

@router.message(Command("s"), F.from_user.id.in_({ADMIN_ID, *DB["curators"]}))
async def cmd_staff_s(message: Message, command: CommandObject):
    raw = (command.args or "").strip()
    parts = raw.split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        return await message.answer("Формат: <code>/s &lt;user_id&gt; &lt;текст&gt;</code>", parse_mode="HTML")
    uid, text = int(parts[0]), parts[1].strip()
    
    ok, err = await try_send(message.bot, uid, text)
    if ok:
        if str(uid) not in DB["chats"]: DB["chats"][str(uid)] = {"curator_id": message.from_user.id, "history": []}
        DB["chats"][str(uid)]["history"].append({"role": "staff", "text": text, "count": 1})
        save_db()
        await message.answer("✅ Доставлено.")
    else:
        await message.answer(f"❌ Ошибка: {err}")

@router.message(F.from_user.id.in_({ADMIN_ID, *DB["curators"]}), F.reply_to_message)
async def staff_reply(message: Message):
    replied = message.reply_to_message
    uid = None
    if replied.text:
        m = re.search(r"user_id:\s*(\d+)", replied.text) or re.search(r"ID:\s*<code>(\d+)</code>", replied.text) or re.search(r"ID:\s*(\d+)", replied.text)
        if m: uid = int(m.group(1))
        
    if not uid:
        return await message.answer("⚠️ Не удалось определить ID. Используйте <code>/s &lt;id&gt; &lt;текст&gt;</code>", parse_mode="HTML")
    
    try:
        await message.copy_to(uid)
        if str(uid) not in DB["chats"]: DB["chats"][str(uid)] = {"curator_id": message.from_user.id, "history": []}
        log_text = message.text or "[Медиафайл]"
        DB["chats"][str(uid)]["history"].append({"role": "staff", "text": log_text, "count": 1})
        save_db()
        await message.answer("✅ Доставлено игроку.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


# ===========================================================================
# ЛОГИКА ИГРОКОВ
# ===========================================================================
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    if is_staff(uid): return await message.answer("Вы персонал. Используйте /chats или /list.")
    
    status = get_status(uid)
    if status == "pending": return await message.answer("⏳ Анкета на рассмотрении.")
    if status == "approved": return await message.answer("✅ Ваша анкета одобрена. Напишите сообщение.")
    if status == "banned": return await message.answer("🚫 Вы забанены.")

    await state.set_state(Form.waiting_form)
    
    text = (
        f"<b>🐋 Добро пожаловать в игру «Голубой кит»!</b>\n"
        f"{LINE}\n"
        f"Для начала игры вам необходимо заполнить анкету. Отправьте данные одним сообщением:\n"
        f"<b>1.</b> Имя\n"
        f"<b>2.</b> Возраст\n"
        f"<b>3.</b> Город\n"
        f"<b>4.</b> Время на игру\n\n"
        f"<b>📜 Правила игры:</b>\n"
        f"<blockquote>• Запрещено грубить, хамить и отказываться выполнять задания.\n"
        f"• Запрещено материть куратора.\n"
        f"• На выполнение задания даётся ровно 24 часа.\n"
        f"• Выйти из игры можно только пройдя её до конца.</blockquote>\n"
        f"<b>📝 Пример анкеты:</b>\n"
        f"<pre>1. Матвей\n2. 13\n3. Новгород\n4. 1 час</pre>\n"
        f"<i>Удачной игры!</i>\n"
        f"{LINE}"
    )
    await message.answer(text, parse_mode="HTML")

@router.message(Form.waiting_form, F.text, ~F.text.startswith("/"))
async def process_form(message: Message, state: FSMContext):
    uid = message.from_user.id
    if get_status(uid) in ("pending", "approved", "banned"): return
    
    await state.clear()
    set_status(uid, "pending")
    await message.answer("✅ Анкета отправлена! Ожидайте куратора.")

    uname = message.from_user.username or "нет"
    staff_msg = (
        f"📥 <b>НОВАЯ АНКЕТА</b>\n{LINE}\n"
        f"👤 <b>user_id:</b> <code>{uid}</code>\n"
        f"🔗 <b>username:</b> @{uname}\n"
        f"{LINE}\n<blockquote>{html.escape(message.text)}</blockquote>"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Взять чат", callback_data=f"appr:{uid}")
    kb.button(text="❌ Отклонить", callback_data=f"rej:{uid}")

    for rid in set([ADMIN_ID] + DB["curators"]):
        try: await message.bot.send_message(rid, staff_msg, parse_mode="HTML", reply_markup=kb.as_markup())
        except: pass

@router.callback_query(F.data.startswith("appr:") | F.data.startswith("rej:"))
async def cb_decision(call: CallbackQuery):
    if not is_staff(call.from_user.id): return await call.answer("Нет доступа", show_alert=True)
    
    action, uid_str = call.data.split(":")
    uid = int(uid_str)
    staff_id = call.from_user.id

    if action == "appr":
        if str(uid) in DB["chats"] and DB["chats"][str(uid)].get("curator_id"):
            return await call.answer("❌ Этот чат уже занят другим куратором!", show_alert=True)
            
        DB["chats"][str(uid)] = {
            "curator_id": staff_id, 
            "history": [{"role": "user", "text": "Анкета принята", "count": 1}]
        }
        set_status(uid, "approved")
        await try_send(call.bot, uid, "🎉 <b>Анкета одобрена!</b>\nКуратор уже принял ваш чат и готов общаться.")
        await call.message.edit_text(f"✅ Вы забрали чат <code>{uid}</code>. Используйте /chats для входа.", parse_mode="HTML")
    else:
        set_status(uid, "rejected")
        await try_send(call.bot, uid, "❌ <b>Анкета отклонена.</b>\nОтправьте /start для новой попытки.")
        await call.message.edit_text(f"❌ Анкета <code>{uid}</code> отклонена.", parse_mode="HTML")
    await call.answer()


# ===========================================================================
# ОБРАБОТЧИК СООБЩЕНИЙ (ТЕКСТ И МЕДИА)
# ===========================================================================
@router.message()
async def handle_messages(message: Message):
    uid = message.from_user.id
    staff_mode = is_staff(uid)

    has_media = bool(message.photo or message.video or message.video_note or message.voice or message.document or message.sticker or message.animation)
    text = message.text or message.caption or ""
    
    # 1. ПЕРСОНАЛ ПИШЕТ В ОТКРЫТОМ ЧАТЕ
    if staff_mode and uid in ACTIVE_CHATS:
        target_uid = ACTIVE_CHATS[uid]
        if not text.strip() and not has_media: return
        
        try:
            await message.copy_to(target_uid)
            
            if str(target_uid) in DB["chats"]:
                log_text = text if text else "[Медиафайл]"
                DB["chats"][str(target_uid)]["history"].append({"role": "staff", "text": log_text, "count": 1})
                save_db()
                
            msg = await message.answer(f"✅ Отправлено игроку {target_uid}")
            await asyncio.sleep(2)
            await msg.delete()
        except Exception as e:
            await message.answer(f"❌ Ошибка отправки: {e}")
        return

    # 2. ПЕРСОНАЛ ВНЕ ЧАТА (Игнорируем)
    if staff_mode: return

    # 3. ЛОГИКА ДЛЯ ИГРОКОВ
    status = get_status(uid)
    if status == "pending": return await message.answer("⏳ Ожидайте куратора.")
    if status == "banned": return 
    if status != "approved": return await message.answer("🤔 Отправьте /start")

    chat_data = DB["chats"].get(str(uid))
    if not chat_data or not chat_data.get("curator_id"): return
    
    curator_id = chat_data["curator_id"]
    history = chat_data["history"]

    # --- ОТПРАВКА МЕДИА ---
    if has_media:
        history.append({"role": "user", "text": "[Медиафайл]", "count": 1})
        save_db()
        
        try:
            if ACTIVE_CHATS.get(curator_id) == uid:
                await message.copy_to(curator_id)
            else:
                await message.copy_to(curator_id)
                uname = message.from_user.username or "нет"
                await message.bot.send_message(curator_id, 
                    f"🔔 <b>У вас новое сообщение (медиа) от @{uname}</b>\n"
                    f"ID: <code>{uid}</code>\n\n<i>Откройте /chats для ответа.</i>", 
                    parse_mode="HTML"
                )
        except Exception as e:
            logging.error(f"Ошибка пересылки медиа: {e}")
        return

    # --- ТЕКСТОВЫЙ АНТИСПАМ ---
    now = time.time()
    last_time = LAST_MSG_TIME.get(uid, 0)
    LAST_MSG_TIME[uid] = now
    
    if history and history[-1]["role"] == "user" and history[-1]["text"] != "[Медиафайл]" and (now - last_time < 30):
        history[-1]["text"] += f"\n{text}"
        history[-1]["count"] += 1
        save_db()
        
        if ACTIVE_CHATS.get(curator_id) == uid and history[-1].get("staff_msg_id"):
            try:
                await message.bot.edit_message_text(
                    chat_id=curator_id, 
                    message_id=history[-1]["staff_msg_id"],
                    text=f"👤 {html.escape(history[-1]['text'])} (x{history[-1]['count']})"
                )
            except: pass
        return
        
    # Новое текстовое сообщение
    history.append({"role": "user", "text": text, "count": 1})
    save_db()
    
    if ACTIVE_CHATS.get(curator_id) == uid:
        sent = await message.bot.send_message(curator_id, f"👤 {html.escape(text)}", parse_mode="HTML")
        history[-1]["staff_msg_id"] = sent.message_id
        save_db()
    else:
        uname = message.from_user.username or "нет"
        note = (
            f"🔔 <b>У вас новое сообщение!</b>\n{LINE}\n"
            f"👤 <b>username:</b> @{uname}\n"
            f"🆔 <b>ID:</b> <code>{uid}</code>\n"
            f"💬 <i>{html.escape(text[:50])}...</i>\n\n"
            f"Откройте /chats для ответа."
        )
        await message.bot.send_message(curator_id, note, parse_mode="HTML")

# ===========================================================================
# ЗАПУСК
# ===========================================================================
async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): logging.info("Бот остановлен")
