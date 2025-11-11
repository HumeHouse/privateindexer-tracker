FROM python:3.13.9-slim

WORKDIR /app

ENV TZ=America/Chicago \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WORKER_THREADS=5

COPY requirements.txt logging.yml ./

RUN pip install -r requirements.txt

COPY src ./src

EXPOSE 80

WORKDIR /app/src

ENTRYPOINT exec uvicorn privateindexer_tracker.main:app --proxy-headers --workers ${WORKER_THREADS} --host 0.0.0.0 --port 80 --log-config /app/logging.yml