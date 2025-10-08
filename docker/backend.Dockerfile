FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY vendor ./vendor

ENV DATABASE_URL=postgresql+asyncpg://amadeus:amadeus@db:5432/amadeus \
    REDIS_URL=redis://redis:6379/0 \
    AMAD_USE_MOCK=true

EXPOSE 8000

CMD ["sh", "-c", "python backend/gateway/scripts/apply_migrations.py --database-url ${DATABASE_URL} && uvicorn backend.gateway.app.main:app --host 0.0.0.0 --port 8000 --reload"]
