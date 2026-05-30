import aiohttp
import asyncio
import logging
import re

logger = logging.getLogger(__name__)

_cached_rate: float | None = None
_cache_ts: float = 0
CACHE_TTL = 30

RAPIRA_PAGE = "https://rapira.net/exchange/USDT_RUB"


async def fetch_garus() -> float:
    global _cached_rate, _cache_ts

    now = asyncio.get_event_loop().time()
    if _cached_rate is not None and (now - _cache_ts) < CACHE_TTL:
        return _cached_rate

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,*/*",
        }
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            headers=headers
        ) as session:
            async with session.get(RAPIRA_PAGE) as resp:
                text = await resp.text()
                logger.info(f"Rapira page status: {resp.status}, length: {len(text)}")
                logger.info(f"Rapira page snippet: {text[:500]}")

                # Ищем любое число похожее на курс USDT/RUB (90-120)
                matches = re.findall(r'\b(9\d\.\d+|1[01]\d\.\d+)\b', text)
                logger.info(f"Найденные числа: {matches}")

                if matches:
                    rate = float(matches[0])
                    _cached_rate = rate
                    _cache_ts = now
                    return rate

        raise ValueError("Курс не найден на странице")

    except Exception as e:
        logger.error(f"Ошибка получения курса EX: {e}")
        if _cached_rate is not None:
            return _cached_rate
        raise RuntimeError(f"Не удалось получить курс EX: {e}")