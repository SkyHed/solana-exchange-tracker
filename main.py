import asyncio
import logging
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import httpx

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")

wallets = {}
profiles = {}
chat_ids = set()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

async def is_new_wallet(address: str) -> bool:
    """Считаем новым, если 0 или 1 транзакция (текущая)"""
    url = f"https://api.helius.xyz/v0/addresses/{address}/transactions?api-key={HELIUS_API_KEY}&limit=5"
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                return False
            data = resp.json()
            count = len(data)
            logging.info(f"Wallet {address[:8]}... has {count} txs")
            return count <= 1
        except Exception as e:
            logging.error(f"Error checking wallet: {e}")
            return False

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    chat_ids.add(message.chat.id)
    text = (
        "👋 Бот с профилями для трекинга пополнений\n\n"
        "<b>Основные команды:</b>\n"
        "/add_wallet &lt;адрес&gt; [название]\n"
        "/remove_wallet &lt;адрес&gt;\n"
        "/create_profile &lt;название&gt;\n"
        "/delete_profile &lt;название&gt;\n"
        "/add_to_profile &lt;профиль&gt; &lt;адрес&gt;\n"
        "/remove_from_profile &lt;профиль&gt; &lt;адрес&gt;\n"
        "/set_min &lt;профиль&gt; &lt;сумма&gt;\n"
        "/set_max &lt;профиль&gt; &lt;сумма&gt;\n"
        "/list — показать всё"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("add_wallet"))
async def cmd_add_wallet(message: types.Message):
    chat_ids.add(message.chat.id)
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.answer("Использование:\n/add_wallet <адрес>\nили\n/add_wallet <адрес> <название>")
        return
    address = args[1].strip()
    label = args[2].strip() if len(args) > 2 else address[:8] + "..."
    if len(address) < 32:
        await message.answer("Некорректный адрес")
        return
    wallets[address] = label
    await message.answer(f"✅ Кошелёк добавлен:\n<code>{address}</code>\nНазвание: <b>{label}</b>", parse_mode="HTML")

@dp.message(Command("remove_wallet"))
async def cmd_remove_wallet(message: types.Message):
    chat_ids.add(message.chat.id)
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /remove_wallet <адрес>")
        return
    address = args[1].strip()
    if address in wallets:
        del wallets[address]
        for p in profiles.values():
            p["wallets"].discard(address)
        await message.answer("🗑 Кошелёк удалён")
    else:
        await message.answer("Такого кошелька нет")

@dp.message(Command("create_profile"))
async def cmd_create_profile(message: types.Message):
    chat_ids.add(message.chat.id)
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /create_profile <название>")
        return
    name = args[1].strip()
    if name in profiles:
        await message.answer("Такой профиль уже существует")
        return
    profiles[name] = {"wallets": set(), "min": None, "max": None}
    await message.answer(f"✅ Профиль <b>{name}</b> создан", parse_mode="HTML")

@dp.message(Command("delete_profile"))
async def cmd_delete_profile(message: types.Message):
    chat_ids.add(message.chat.id)
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /delete_profile <название>")
        return
    name = args[1].strip()
    if name in profiles:
        del profiles[name]
        await message.answer(f"🗑 Профиль <b>{name}</b> удалён", parse_mode="HTML")
    else:
        await message.answer("Такого профиля нет")

@dp.message(Command("add_to_profile"))
async def cmd_add_to_profile(message: types.Message):
    chat_ids.add(message.chat.id)
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Использование: /add_to_profile <профиль> <адрес>")
        return
    name = args[1].strip()
    address = args[2].strip()
    if name not in profiles:
        await message.answer("Профиль не найден")
        return
    if address not in wallets:
        await message.answer("Сначала добавь кошелёк через /add_wallet")
        return
    profiles[name]["wallets"].add(address)
    label = wallets.get(address, address[:8])
    await message.answer(f"✅ Кошелёк <b>{label}</b> добавлен в профиль <b>{name}</b>", parse_mode="HTML")

@dp.message(Command("remove_from_profile"))
async def cmd_remove_from_profile(message: types.Message):
    chat_ids.add(message.chat.id)
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Использование: /remove_from_profile <профиль> <адрес>")
        return
    name = args[1].strip()
    address = args[2].strip()
    if name not in profiles:
        await message.answer("Профиль не найден")
        return
    profiles[name]["wallets"].discard(address)
    await message.answer(f"✅ Кошелёк убран из профиля <b>{name}</b>", parse_mode="HTML")

@dp.message(Command("set_min"))
async def cmd_set_min(message: types.Message):
    chat_ids.add(message.chat.id)
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Использование: /set_min <профиль> <сумма>")
        return
    name = args[1].strip()
    try:
        amount = float(args[2].replace(",", "."))
    except ValueError:
        await message.answer("Сумма должна быть числом")
        return
    if name not in profiles:
        await message.answer("Профиль не найден")
        return
    profiles[name]["min"] = amount
    await message.answer(f"✅ В профиле <b>{name}</b> min = {amount} SOL", parse_mode="HTML")

@dp.message(Command("set_max"))
async def cmd_set_max(message: types.Message):
    chat_ids.add(message.chat.id)
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Использование: /set_max <профиль> <сумма>")
        return
    name = args[1].strip()
    try:
        amount = float(args[2].replace(",", "."))
    except ValueError:
        await message.answer("Сумма должна быть числом")
        return
    if name not in profiles:
        await message.answer("Профиль не найден")
        return
    profiles[name]["max"] = amount
    await message.answer(f"✅ В профиле <b>{name}</b> max = {amount} SOL", parse_mode="HTML")

@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    chat_ids.add(message.chat.id)
    text = "📋 <b>Полный список</b>\n\n"
    text += "<b>Кошельки:</b>\n"
    if wallets:
        for addr, label in wallets.items():
            text += f"• {label} — <code>{addr[:12]}...</code>\n"
    else:
        text += "пусто\n"
    text += "\n<b>Профили:</b>\n"
    if profiles:
        for name, data in profiles.items():
            min_v = data["min"] if data["min"] is not None else "—"
            max_v = data["max"] if data["max"] is not None else "—"
            text += f"\n📁 <b>{name}</b> (min: {min_v} | max: {max_v})\n"
            if data["wallets"]:
                for addr in data["wallets"]:
                    label = wallets.get(addr, addr[:8])
                    text += f"   • {label}\n"
            else:
                text += "   (кошельков нет)\n"
    else:
        text += "пусто"
    await message.answer(text, parse_mode="HTML")

async def helius_webhook(request: web.Request):
    logging.info("Webhook received from Helius")
    try:
        data = await request.json()
    except Exception:
        return web.Response(text="ok")

    transactions = data if isinstance(data, list) else [data]

    for tx in transactions:
        if tx.get("type") != "TRANSFER":
            continue

        for transfer in tx.get("nativeTransfers", []):
            from_wallet = transfer.get("fromUserAccount")
            to_wallet = transfer.get("toUserAccount")
            amount_lamports = transfer.get("amount", 0)
            amount_sol = amount_lamports / 1_000_000_000

            if from_wallet not in wallets:
                continue

            for profile_name, profile in profiles.items():
                if from_wallet not in profile["wallets"]:
                    continue
                if profile["min"] is None or profile["max"] is None:
                    continue
                if not (profile["min"] <= amount_sol <= profile["max"]):
                    continue

                # Проверяем новый кошелёк
                if not await is_new_wallet(to_wallet):
                    continue

                # Всё подошло — отправляем
                label = wallets.get(from_wallet, from_wallet[:8])
                signature = tx.get("signature", "")
                solscan_wallet = f"https://solscan.io/account/{to_wallet}"
                photon = f"https://photon-sol.tinyastro.io/en/lp/{to_wallet}"
                gmgn = f"https://gmgn.ai/sol/address/{to_wallet}"

                text = (
                    f"🔔 <b>Новое пополнение</b>\n\n"
                    f"Профиль: <b>{profile_name}</b>\n"
                    f"С кошелька: <b>{label}</b>\n"
                    f"<code>{from_wallet}</code>\n\n"
                    f"На новый: <code>{to_wallet}</code>\n"
                    f"Сумма: <b>{amount_sol:.6f} SOL</b>\n\n"
                    f"<a href='https://solscan.io/tx/{signature}'>Transaction</a> | "
                    f"<a href='{solscan_wallet}'>Wallet</a>"
                )

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Solscan", url=solscan_wallet),
                        InlineKeyboardButton(text="Photon", url=photon),
                        InlineKeyboardButton(text="GMGN", url=gmgn),
                    ]
                ])

                for chat_id in chat_ids:
                    try:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=text,
                            parse_mode="HTML",
                            reply_markup=keyboard,
                            disable_web_page_preview=True
                        )
                        logging.info(f"Alert sent to {chat_id}")
                    except Exception as e:
                        logging.error(f"Ошибка отправки: {e}")

    return web.Response(text="ok")

async def main():
    app = web.Application()
    app.router.add_post("/helius-webhook", helius_webhook)

    port = int(os.getenv("PORT", 8000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Webhook server started on port {port}")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
