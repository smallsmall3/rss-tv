# rss-tv
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY config/ config/

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    RMH_DATA_DIR=/data

VOLUME ["/data", "/app/config"]

EXPOSE 18080

CMD ["python", "-m", "app"]
