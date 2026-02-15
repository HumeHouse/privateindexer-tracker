import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from privateindexer_tracker.core import logger
from privateindexer_tracker.core import mysql, api, redis, utils, config
from privateindexer_tracker.core.config import HIGH_LATECY_THRESHOLD, APP_VERSION


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.channel("app").info(f"Starting PrivateIndexer tracker v{APP_VERSION}")

    # test Redis connection
    try:
        await redis.get_connection()
        logger.channel("app").info("Connected to Redis")
    except Exception as e:
        logger.channel("app").error(f"Exception while connecting Redis: {e}")
        exit(1)

    # test MySQL connection
    try:
        await mysql.connect_database()
        logger.channel("app").info("Connected to MySQL")
    except Exception as e:
        logger.channel("app").error(f"Exception while connecting MySQL: {e}")
        exit(1)

    logger.channel("app").info("API server started on 0.0.0.0:8082")

    yield

    logger.channel("app").info("Shutting down PrivateIndexer tracker")

    await mysql.disconnect_database()

    await redis.close_connection()


# validate Python environment
config.validate_environment()

app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None,
              title=f"PrivateIndexer Tracker", version=APP_VERSION)

app.include_router(api.router)


@app.middleware("http")
async def track_stats(request: Request, call_next):
    client_ip = utils.get_client_ip(request)

    # start a redis transaction
    redis_connection = redis.get_connection()
    pipe = redis_connection.pipeline()

    # append client IP to known IP list and increment request counter
    await pipe.incr("stats:requests")
    await pipe.sadd("stats:unique_ips", client_ip)

    # add the requester-side content length to the counter
    if request.headers.get("content-length"):
        await pipe.incrby("stats:bytes_received", int(request.headers["content-length"]))

    # time the endpoint execution
    start_time = time.perf_counter()
    response: Response = await call_next(request)
    duration = (time.perf_counter() - start_time) * 1000

    # parse the request parts and the query parameters
    request_method = request.scope.get("method")
    request_string = request.scope.get("path")
    query_string = request.scope.get("query_string")
    if query_string:
        request_string = f"{request_string}?{query_string.decode()}"

    # check the endpoint execution time for high latency
    if duration > HIGH_LATECY_THRESHOLD:
        logger.channel("app").warning(f"High response time ({duration} ms) - [{request_method}] {request_string}")
    else:
        logger.channel("app").debug(f"Request ({duration} ms) - [{request_method}] {request_string}")

    # add the server-side content length to the counter
    if response.headers.get("content-length"):
        await pipe.incrby("stats:bytes_sent", int(response.headers["content-length"]))

    # insert request duration and normalize values
    await pipe.rpush("stats:request_times", duration)
    await pipe.ltrim("stats:request_times", -10000, -1)
    await pipe.execute()

    return response
