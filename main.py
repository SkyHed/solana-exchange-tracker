import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import BOT_TOKEN, tracked_wallets, target_amount, tolerance
import config
from utils import is_new_wallet, is_amount_match

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ========== КОМАНДЫ БОТА ==========

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
        config.target_amount = amount
        await message.answer(f"✅ Сумма установлена: {amount} SOL (±{config.tolerance})")
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
        config.tolerance = tol
        await message.answer(f"✅ Допуск установлен: ±{tol} SOL")
    except ValueError:
        await message.answer("Нужно указать число, например: /set_tolerance 0.05")

@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    wallets = "\n".join([f"`{w}`" for w in tracked_wallets]) or "пусто"
    text = (
        f"📋 Текущие настройки:\n\n"
        f"Сумма: {config.target_amount or 'не задана'}\n"
        f"Допуск: ±{config.tolerance}\n\n"
        f"Кошельки бирж ({len(tracked_wallets)}):\n{wallets}"
    )
    await message.answer(text, parse_mode="Markdown")

# ========== HELIUS WEBHOOK ==========

async def helius_webhook(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        return web.Response(text="ok")

    # Helius может присылать список транзакций
    transactions = data if isinstance(data, list) else [data]

    for tx in transactions:
        if tx.get("type") != "TRANSFER":
            continue

        native_transfers = tx.get("nativeTransfers", [])
        for transfer in native_transfers:
            from_wallet = transfer.get("fromUserAccount")
            to_wallet = transfer.get("toUserAccount")
            amount_lamports = transfer.get("amount", 0)
            amount_sol = amount_lamports / 1_000_000_000

            # Проверяем, что перевод с нашего отслеживаемого кошелька
            if from_wallet not in tracked_wallets:
                continue

            # Проверяем сумму
            if not is_amount_match(amount_sol):
                continue

            # Проверяем, новый ли кошелёк
            if not await is_new_wallet(to_wallet):
                continue

            # Всё подошло — отправляем алерт
            signature = tx.get("signature", "")
            solscan_tx = f"https://solscan.io/tx/{signature}"
            solscan_wallet = f"https://solscan.io/account/{to_wallet}"
            photon = f"https://photon-sol.tinyastro.io/en/lp/{to_wallet}"
            gmgn = f"https://gmgn.ai/sol/address/{to_wallet}"

            text = (
                f"🔔 <b>Новое пополнение</b>\n\n"
                f"С биржи: <code>{from_wallet}</code>\n"
                f"На новый кошелёк: <code>{to_wallet}</code>\n"
                f"Сумма: <b>{amount_sol:.4f} SOL</b>\n\n"
                f"<a href='{solscan_tx}'>Transaction</a> | "
                f"<a href='{solscan_wallet}'>Wallet</a>"
            )

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="Solscan", url=solscan_wallet),
                    InlineKeyboardButton(text="Photon", url=photon),
                    InlineKeyboardButton(text="GMGN", url=gmgn),
                ]
            ])

            # Отправляем всем, кто писал боту (пока просто в чат, откуда пришла команда)
            # Для простоты — отправляем в последний известный чат. 
            # Позже можно сохранять chat_id.
            try:
                # Временно: нужно будет сохранять chat_id пользователя
                pass
            except Exception as e:
                logging.error(f"Ошибка отправки: {e}")

    return web.Response(text="ok")

# ========== ЗАПУСК ==========

async def main():
    # Создаём веб-сервер
    app = web.Application()
    app.router.add_post("/helius-webhook", helius_webhook)

    # Railway даёт порт через переменную PORT
    import os
    port = int(os.getenv("PORT", 8000))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Webhook server started on port {port}")

    # Запускаем бота (polling)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
