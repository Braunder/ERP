FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p data logs backups && chmod +x run.py
EXPOSE 8000

# Ошибка миграции должна остановить контейнер, а не запускать приложение на неправильной схеме.
CMD ["sh", "-c", "python init_db.py && python run.py"]
