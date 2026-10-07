import httpx
from config import HELIUS_API_KEY, tolerance, target_amount

async def is_new_wallet(address: str) -> bool:
    """
    Проверяем, новый ли кошелёк.
    Считаем новым, если у него очень мало транзакций (0-2).
    """
    url = f"https://api.helius.xyz/v0/addresses/{address}/transactions?api-key={HELIUS_API_KEY}&limit=5"
    
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                return False
            data = resp.json()
            # Если транзакций 0, 1 или 2 — считаем новым
            return len(data) <= 2
        except Exception:
            return False

def is_amount_match(amount_sol: float) -> bool:
    """Проверяем, попадает ли сумма в нужный диапазон ± tolerance"""
    if target_amount is None:
        return False
    return abs(amount_sol - target_amount) <= tolerance
