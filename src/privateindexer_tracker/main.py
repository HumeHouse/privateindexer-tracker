import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from privateindexer_tracker.core import mysql, api, redis, utils
from privateindexer_tracker.core.config import HIGH_LATECY_THRESHOLD, APP_VERSION
from privateindexer_tracker.core.logger import log


@asynccontextmanager
async def lifespan(_: FastAPI):
    log.info(f"[APP] Starting PrivateIndexer tracker v{APP_VERSION}")

    log.info("[APP] Connecting Redis")

    await redis.get_connection()

    log.info("[APP] Connecting MySQL")

    await mysql.connect_database()

    log.info("[APP] API server started on 0.0.0.0:80")

    yield

    log.info("[APP] Shutting down PrivateIndexer tracker")

    await mysql.disconnect_database()

    await redis.close_connection()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None,
              title=f"PrivateIndexer Tracker", version=APP_VERSION)

app.include_router(api.router)


@app.middleware("http")
async def track_stats(request: Request, call_next):
    client_ip = utils.get_client_ip(request)

    redis_connection = redis.get_connection()
    pipe = redis_connection.pipeline()

    await pipe.incr("stats:requests")
    await pipe.sadd("stats:unique_ips", client_ip)

    if request.headers.get("content-length"):
        await pipe.incrby("stats:bytes_received", int(request.headers["content-length"]))

    start_time = time.perf_counter()
    response: Response = await call_next(request)
    duration = (time.perf_counter() - start_time) * 1000
    if duration > HIGH_LATECY_THRESHOLD:
        endpoint = request.scope.get("path")
        route = request.scope.get("route")
        route_path = getattr(route, "path", endpoint)
        log.warning(f"[APP] High response time ({route_path}): {duration} ms")

    if response.headers.get("content-length"):
        await pipe.incrby("stats:bytes_sent", int(response.headers["content-length"]))

    await pipe.rpush("stats:request_times", duration)
    await pipe.ltrim("stats:request_times", -10000, -1)
    await pipe.execute()

    return response
