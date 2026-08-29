FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копирование зависимостей
COPY requirements.txt .

# Установка Python зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копирование остального кода
COPY . .

# Копирование Google сервисного аккаунта (если есть)
RUN if [ -f "gen-lang-client-*.json" ]; then \
        for file in gen-lang-client-*.json; do \
            cp "$file" .; \
        done; \
    fi

# Создание директорий для данных
RUN mkdir -p data logs backups

# Установка прав
RUN chmod +x run.py

# Экспорт переменных окружения
ENV PYTHONUNBUFFERED=1

# Запуск приложения
CMD ["sh", "-c", "python init_db.py || true && python run.py"]
