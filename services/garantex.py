import aiohttp
import asyncio
import logging
import time
import base64
import json
import hmac
import hashlib
import os

logger = logging.getLogger(__name__)

_cached_rate: float | None = None
_cache_ts: float = 0
CACHE_TTL = 30

RAPIRA_UID = "3e3ae4f1-52bd-44ff-bb2c-0299a5de35e9"
RAPIRA_PRIVATE_KEY = "LS0tLS1CRUdJTiBSU0EgUFJJVkFURSBLRVktLS0tLQpNSUlFdlFJQkFEQU5CZ2txaGtpRzl3MEJBUUVGQUFTQ0JLY3dnZ1NqQWdFQUFvSUJBUUNPeitaWTZSYWluRXJpRldpN0lJTzM0V1h5bWkwUDAwclExaytlN0JNVW80OTBVa0wycTZTTjNXS3kzbTdLdERLb2dYdERZRjIwalQraVhtcy8xd2ZhNXZoS1JMSGFndkVUN2NQMTdTdGorblNJVzFrZFFuWDMydld1UkhreURJTjJvL0NMQXJaaU53NFlZSVgwblRVQmpVMHhJWDFQZ3JiSGcrbEZXaE56QmJlandmSTA5T3BQRHdNVk1xSkR0RjcramhRbHVyVDRMZ0ltbDlnR2pBWUlKMHMxbUIvVHg2dW9OZ3E3a2x0c2FqRjYyT2ZhNFYyaVV6YWR4bFJkL3NBaVZTMkVIcGpJekJwZWkvK3VlNFpxQjJtU1c0ZWg0cElWYnJTSFhWbmdYcXF4QlZrWTQzUXhXc1ZqZ3NLU0NFRWhMMlZndjZ0dEo1Z00raWQ2eitrckFnTUJBQUVDZ2dFQVA5WkE0amQyN2NNdFdmZzE4NGVxT1ZUZ3pGd01qb2xsWlFxWFZyT3lKOFNoQ0Y4SkhkaEYyMEE5c1RUcWsyT1BUWEZybHdlSmUzNjBGakZjZ1pIdUtmU2F3aUFJM0dNeHZqWEhKYlFaZER4dFFOS01lQjdRT3JXK29tSnJSbXIvak5YbFhVNGVGck1EY3ZRYWpPaUUzQ2U4Zkp5NnRnTDVEeUF3OHRZNzRXcmUyTFlDTG0vQm42WVdkRk1OVnZ5WlMzR2k2Zkx1SGU4cnhDQi8vT0RMY1QzS04yVlFqSjlkalB4dDJWcFBwYnU1c0diWlp0WkVqNXJUNWtRbVZ1ZFl5dkY4WU5LSHBaeG0rbW9qZWc0QlRkdW13Wkk1ZUxKcHR0cnRSYTVWTU84ZmV5UkI3c1RnTlFESmcwL1NIZWFXbFJaNVBTcmVzd202bE9rTXlOcTAwUUtCZ1FERDhNRGpJa1E5MnE2M1RCTFQ3QjM3ZjRxanNHSEVFUGZvMmhsakJBbkh4TDJXYVc1WlRmOWVhVlRvY2hNaDhWU1dvTmh2UjAyOENEYmlRZmxKazFSL0tBeGpqSEZ2RlNjWk5pTktyN1lveU52N1B1SEVXU1NwSktRQVE2NHdKNWo3aW1tbFJ6UUZBakFtLzBCa0w2OXAwNGxwUnIzUVo5VVBTbW1KYWVTQll3S0JnUUM2bGpoYnQxaFo1WWszNjBNTEdoZ0VGalBBblFGR0hZZE5KczkydUNLNS9FVHBqMlBCMXRXazZ2aCtjRUtxVnpNM2RPRzRwSDlvRE5Idy9YZGhWSmxzL2U5R2xCdktaN0kyVjlkMEV1SWFxb20xRk5IQzF0TkRnWTBvQy9oRFpNcG1RbElsNy92b0pYTDRlQjZRQVVFR0hFOHB1cnl3b1ZTZUNyazRWdjJubVFLQmdCNW5KL2JXWlZKWHNVNTl2bG9seEEwM0lCTUFGbHR1NnBpMTVzU0hadUVaZFBWMnpJbU00YmdMamdJM1dTS21LS0xxdUVxai9MclZaM2E2RisxRHNCTys2aFUwUUpHazdaa3EzbFVEYUxkeFd6amo2L0lraHR5Nzg3cWF4ZGR3L1hyaVlqd2tEVDFOdHAwR2RENVhhOWQyM0ZaNmhJOW0zUmR2UzJyb0JHM1RBb0dCQUp3TDZsSjZRZi9kQWllc01FUG1yTk11SmxZZWVPUkU2ZFZTY2d2ZDc5MFA2Q3BWYTU2L3A2bm5nYTlzLzdRcWZZRVIxWDF3eGNVbGc2ZEN0RWJJVkJCZFIzSUZpRUI4L1FTSjduejdGZklyVWtRSmgyeWw4Y1h4WVRadTNGQ3d5TDFCRmliNFQvdFU1cFI3RVVScWFCRk9ONzYwbC80NHp1WG1IZ1hLYXhWeEFvR0FmRmJwTnNnOFlUcmlCUDBTb3dhWnhOdTYyWTA4S3JxNG1EaUFhOVA5ZGk0MVRmUmFNTTdjTk1LL3hnYW1RUUVuaE9WckZ0L09kb2pPQjVTakRlSHJ6UDYxWnd1aGtPNXBGRCt4TGZWQzdqMXdIb2pQOGE5bDNtd1l1RmMrK2ZCVkVOWVRxUVQwTlJramg0MmtMNHFIOU51RTRjU01mdEtMOWtPa3ppeDJ2RUk9Ci0tLS0tRU5EIFJTQSBQUklWQVRFIEtFWS0tLS0tCg=="

_access_token: str | None = None
_access_token_ts: float = 0
ACCESS_TOKEN_TTL = 1500  # 25 минут


async def _get_client_jwt() -> str:
    try:
        import jwt as pyjwt
        import secrets
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.backends import default_backend

        private_key_pem = base64.b64decode(RAPIRA_PRIVATE_KEY).decode("utf-8")
        
        # Заменяем заголовок на PKCS8
        private_key_pem = private_key_pem.replace(
            "-----BEGIN RSA PRIVATE KEY-----",
            "-----BEGIN PRIVATE KEY-----"
        ).replace(
            "-----END RSA PRIVATE KEY-----",
            "-----END PRIVATE KEY-----"
        )

        private_key = load_pem_private_key(
            private_key_pem.encode(), 
            password=None,
            backend=default_backend()
        )

        payload = {
            "exp": int(time.time()) + 1800,
            "jti": secrets.token_hex(12)
        }
        token = pyjwt.encode(payload, private_key, algorithm="RS256")
        return token
    except Exception as e:
        raise RuntimeError(f"Ошибка генерации JWT: {e}")


async def _get_access_token() -> str:
    global _access_token, _access_token_ts

    now = time.time()
    if _access_token and (now - _access_token_ts) < ACCESS_TOKEN_TTL:
        return _access_token

    client_jwt = await _get_client_jwt()

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        async with session.post(
            "https://api.rapira.net/open/generate_jwt",
            json={"kid": RAPIRA_UID, "jwt_token": client_jwt},
            headers={"Accept": "application/json", "Content-Type": "application/json"}
        ) as resp:
            data = await resp.json()
            token = data.get("token")
            if not token:
                raise RuntimeError(f"Не получили токен: {data}")
            _access_token = token
            _access_token_ts = now
            return token


async def fetch_garus() -> float:
    global _cached_rate, _cache_ts

    now = asyncio.get_event_loop().time()
    if _cached_rate is not None and (now - _cache_ts) < CACHE_TTL:
        return _cached_rate

    try:
        token = await _get_access_token()

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
            headers={"Authorization": f"Bearer {token}", "accept": "application/json"}
        ) as session:
            async with session.post(
                "https://api.rapira.net/market/exchange-plate-mini",
                data={"symbol": "USDT/RUB"},
                headers={"Authorization": f"Bearer {token}"}
            ) as resp:
                data = await resp.json()
                asks = data.get("ask", {}).get("items", [])
                if not asks:
                    raise ValueError("Пустой стакан")
                # Берём 3-й снизу из стакана продаж
                idx = 1
                rate = float(asks[idx]["price"])
                _cached_rate = rate
                _cache_ts = asyncio.get_event_loop().time()
                return rate

    except Exception as e:
        logger.error(f"Ошибка получения курса EX: {e}")
        if _cached_rate is not None:
            return _cached_rate
        raise RuntimeError(f"Не удалось получить курс EX: {e}")