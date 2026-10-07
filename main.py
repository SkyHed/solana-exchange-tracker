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

# Настройки
tracked_wallets = set()
min_amount = None
max_amount = None
chat_ids = set()  # сюда сохраняем чаты, куда слать алерты

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

async def is_new_wallet(address: str) -> bool:
    """Считаем кошелёк новым, если у него ≤ 2 транзакций"""
    url = f"https://api.helius.xyz/v0/addresses/{address}/transactions?api-key={HELIUS_API_KEY}&limit=5"
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                return False
            data = resp.json()
            return len(data) <= 2
        except Exception:
            return False

def is_amount_match(amount_sol: float) -> bool:
    """Проверяем, попадает ли сумма в диапазон min-max"""
    if min_amount is None or max_amount is None:
        return False
    return min_amount <= amount_sol <= max_amount

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    chat_ids.add(message.chat.id)
    text = (
        "👋 Бот для трекинга пополнений с бирж на новые кошельки Solana\n\n"
        "Команды:\n"
        "/add_wallet <адрес> — добавить кошелёк биржи\n"
        "/remove_wallet <адрес> — удалить кошелёк\n"
        "/set_min <сумма> — минимальная сумма (например 2.10)\n"
        "/set_max <сумма> — максимальная сумма (например 2.12)\n"
        "/list — показать текущие настройки"
    )
    await message.answer(text)

@dp.message(Command("add_wallet"))
async def cmd_add_wallet(message: types.Message):
    chat_ids.add(message.chat.id)
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /add_wallet <адрес_кошелька>")
        return
    wallet = args[1].strip()
    if len(wallet) < 32:
        await message.answer("Некорректный адрес кошелька")
        return
    tracked_wallets.add(wallet)
    await message.answer(f"✅ Кошелёк добавлен:\n`{wallet}`", parse_mode="Markdown")

@dp.message(Command("remove_wallet"))
async def cmd_remove_wallet(message: types.Message):
    chat_ids.add(message.chat.id)
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /remove_wallet <адрес>")
        return
    wallet = args[1].strip()
    if wallet in tracked_wallets:
        tracked_wallets.remove(wallet)
        await message.answer(f"🗑 Кошелёк удалён:\n`{wallet}`", parse_mode="Markdown")
    else:
        await message.answer("Такого кошелька нет в списке")

@dp.message(Command("set_min"))
async def cmd_set_min(message: types.Message):
    chat_ids.add(message.chat.id)
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /set_min 2.10")
        return
    try:
        amount = float(args[1].replace(",", "."))
        global min_amount
        min_amount = amount
        await message.answer(f"✅ Минимальная сумма установлена: {amount} SOL")
    except ValueError:
        await message.answer("Нужно указать число, например: /set_min 2.10")

@dp.message(Command("set_max"))
async def cmd_set_max(message: types.Message):
    chat_ids.add(message.chat.id)
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /set_max 2.12")
        return
    try:
        amount = float(args[1].replace(",", "."))
        global max_amount
        max_amount = amount
        await message.answer(f"✅ Максимальная сумма установлена: {amount} SOL")
    except ValueError:
        await message.answer("Нужно указать число, например: /set_max 2.12")

@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    chat_ids.add(message.chat.id)
    wallets = "\n".join([f"`{w}`" for w in tracked_wallets]) or "пусто"
    text = (
        f"📋 Текущие настройки:\n\n"
        f"Мин. сумма: {min_amount if min_amount is not None else 'не задана'}\n"
        f"Макс. сумма: {max_amount if max_amount is not None else 'не задана'}\n\n"
        f"Кошельки бирж ({len(tracked_wallets)}):\n{wallets}"
    )
    await message.answer(text, parse_mode="Markdown")

async def helius_webhook(request: web.Request):
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

            if from_wallet not in tracked_wallets:
                continue
            if not is_amount_match(amount_sol):
                continue
            if not await is_new_wallet(to_wallet):
                continue

            # Всё подошло — отправляем алерт
            signature = tx.get("signature", "")
            solscan_wallet = f"https://solscan.io/account/{to_wallet}"
            photon = f"https://photon-sol.tinyastro.io/en/lp/{to_wallet}"
            gmgn = f"https://gmgn.ai/sol/address/{to_wallet}"

            text = (
                f"🔔 <b>Новое пополнение</b>\n\n"
                f"С биржи: <code>{from_wallet}</code>\n"
                f"На новый кошелёк: <code>{to_wallet}</code>\n"
                f"Сумма: <b>{amount_sol:.4f} SOL</b>\n\n"
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

            # Отправляем во все сохранённые чаты
            for chat_id in chat_ids:
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="HTML",
                        reply_markup=keyboard,
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    logging.error(f"Ошибка отправки в {chat_id}: {e}")

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
