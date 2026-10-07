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

tracked_wallets = set()
target_amount = None
tolerance = 0.05

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

async def is_new_wallet(address: str) -> bool:
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
    if target_amount is None:
        return False
    return abs(amount_sol - target_amount) <= tolerance

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    text = (
        "👋 Бот для трекинга пополнений с бирж на новые кошельки Solana\n\n"
        "Команды:\n"
        "/add_wallet <адрес> — добавить кошелёк биржи\n"
        "/set_amount <сумма> — установить сумму (например 3.22)\n"
        "/set_tolerance <число> — допуск (по умолчанию 0.05)\n"
        "/list — показать текущие настройки\n"
        "/remove_wallet <адрес> — удалить кошелёк"
    )
    await message.answer(text)

@dp.message(Command("add_wallet"))
async def cmd_add_wallet(message: types.Message):
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

@dp.message(Command("set_amount"))
async def cmd_set_amount(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /set_amount 3.22")
        return
    try:
        amount = float(args[1].replace(",", "."))
        global target_amount
        target_amount = amount
        await message.answer(f"✅ Сумма установлена: {amount} SOL (±{tolerance})")
    except ValueError:
        await message.answer("Нужно указать число, например: /set_amount 3.22")

@dp.message(Command("set_tolerance"))
async def cmd_set_tolerance(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /set_tolerance 0.05")
        return
    try:
        tol = float(args[1].replace(",", "."))
        global tolerance
        tolerance = tol
        await message.answer(f"✅ Допуск установлен: ±{tol} SOL")
    except ValueError:
        await message.answer("Нужно указать число, например: /set_tolerance 0.05")

@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    wallets = "\n".join([f"`{w}`" for w in tracked_wallets]) or "пусто"
    text = (
        f"📋 Текущие настройки:\n\n"
        f"Сумма: {target_amount or 'не задана'}\n"
        f"Допуск: ±{tolerance}\n\n"
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

            # Пока алерты не отправляются (нужно сохранить chat_id)
            # Это поправим следующим шагом

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
