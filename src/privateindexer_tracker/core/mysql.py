import asyncio
from typing import Optional

import aiomysql

from privateindexer_tracker.core.config import MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB, MYSQL_MAX_RETY, MYSQL_RETRY_BACKOFF
from privateindexer_tracker.core.logger import log

background_updates = asyncio.Queue()
_db_pool: Optional[aiomysql.Pool] = None


async def connect_database():
    global _db_pool
    _db_pool = await aiomysql.create_pool(host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD, db=MYSQL_DB, autocommit=True)
    log.debug("[MYSQL] Connected to database")
    asyncio.create_task(background_worker())
    log.debug("[MYSQL] Started background worker task")


async def disconnect_database():
    if _db_pool is not None:
        _db_pool.close()
        await _db_pool.wait_closed()
        log.debug("[MYSQL] Connection pool closed")


async def background_worker():
    while True:
        query, params = await background_updates.get()
        try:
            await execute(query, params)
        except Exception as e:
            log.error(f"Background query failed: {e}")
        finally:
            background_updates.task_done()


async def _with_retry(fn, *args, **kwargs):
    for attempt in range(1, MYSQL_MAX_RETY + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            if attempt < MYSQL_MAX_RETY:
                wait_time = MYSQL_RETRY_BACKOFF * attempt
                if attempt > MYSQL_MAX_RETY * .5:
                    log.warning(f"[MYSQL] Query failed with {e}, retrying in {wait_time:.2f}s (attempt {attempt})")
                await asyncio.sleep(wait_time)
                continue
            log.error(f"[MYSQL] Query failed after {MYSQL_MAX_RETY} attempts: {e}")
            raise
    return None


async def fetch_all(query: str, params: tuple = ()):
    async def _do():
        async with _db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, params)
                return await cur.fetchall()

    return await _with_retry(_do)


async def fetch_one(query: str, params: tuple = ()):
    async def _do():
        async with _db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, params)
                return await cur.fetchone()

    return await _with_retry(_do)


async def execute(query: str, params: tuple = (), include_row_id: bool = False, include_row_count: bool = False):
    async def _do():
        async with _db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                result = {}
                if include_row_id:
                    result["lastrowid"] = cur.lastrowid
                if include_row_count:
                    result["rowcount"] = cur.rowcount

                if len(result) == 1:
                    return next(iter(result.values()))

                return result

    return await _with_retry(_do)
