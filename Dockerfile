FROM python:3.14.2-slim

WORKDIR /app

ENV TZ=America/Chicago \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WORKER_THREADS=5

COPY requirements.txt logging.yml ./

RUN pip install -r requirements.txt

COPY src ./src

EXPOSE 80

HEALTHCHECK --start-period=30s --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request, sys; \
    sys.exit(0) if urllib.request.urlopen('http://localhost:80/health').getcode() == 200 else sys.exit(1)"

WORKDIR /app/src

ENTRYPOINT exec uvicorn privateindexer_tracker.main:app --proxy-headers --workers ${WORKER_THREADS} --host 0.0.0.0 --port 80 --log-config /app/logging.yml