import asyncio
from typing import Optional

import aiomysql

from privateindexer_tracker.core import logger
from privateindexer_tracker.core.config import MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB, MYSQL_MAX_RETY, MYSQL_RETRY_BACKOFF

background_updates = asyncio.Queue()
_db_pool: Optional[aiomysql.Pool] = None


async def connect_database():
    """
    Creates a connection pool to MySQL database
    """
    global _db_pool
    _db_pool = await aiomysql.create_pool(host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD, db=MYSQL_DB, autocommit=True)
    logger.channel("mysql").debug("Connected to database")

    # create the task for background execution
    asyncio.create_task(background_worker())
    logger.channel("mysql").debug("Started background worker task")


async def disconnect_database():
    """
    Closes MySQL connection pool if active
    """
    if _db_pool is not None:
        _db_pool.close()
        await _db_pool.wait_closed()
        logger.channel("mysql").debug("Connection pool closed")


async def background_worker():
    """
    Executes MySQL queries asynchronously to prevent request congestion
    """
    while True:
        query, params = await background_updates.get()
        try:
            await execute(query, params)
        except Exception as e:
            log.error(f"Background query failed: {e}")
        finally:
            background_updates.task_done()


async def _with_retry(fn, *args, **kwargs):
    """
    Retries failed MySQL queries up to MYSQL_MAX_RETY times
    """
    for attempt in range(1, MYSQL_MAX_RETY + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            if attempt < MYSQL_MAX_RETY:
                wait_time = MYSQL_RETRY_BACKOFF * attempt
                if attempt > MYSQL_MAX_RETY * .5:
                    logger.channel("mysql").warning(f"Query failed with {e}, retrying in {wait_time:.2f}s (attempt {attempt})")
                await asyncio.sleep(wait_time)
                continue
            logger.channel("mysql").error(f"Query failed after {MYSQL_MAX_RETY} attempts: {e}")
            raise
    return None


async def fetch_all(query: str, params: tuple = ()):
    """
    Execute a query to MySQL and fetch all rows
    """

    async def _do():
        async with _db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, params)
                return await cur.fetchall()

    return await _with_retry(_do)


async def fetch_one(query: str, params: tuple = ()):
    """
    Execute a query to MySQL and fetch a single row
    """

    async def _do():
        async with _db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, params)
                return await cur.fetchone()

    return await _with_retry(_do)


async def execute(query: str, params: tuple = (), include_row_id: bool = False, include_row_count: bool = False):
    """
    Execute a query to MySQL and optionally fetch the row ID and modified row count
    """

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
