FROM python:3.10-slim

WORKDIR /app

ENV PYTHONPATH=/app

# Cài đặt các thư viện hệ thống cần thiết cho psycopg2/asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy và cài đặt python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ mã nguồn backend
COPY . .

# Expose cổng của Web Backend
EXPOSE 8000

# Chạy uvicorn server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
