FROM python:3.11-slim

# Thiết lập thư mục làm việc
WORKDIR /app

# Thiết lập các biến môi trường để Python chạy tối ưu trong Docker
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Cài đặt các gói hệ thống cần thiết để build các thư viện Python (như gcc cho tiktoken, asyncpg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Sao chép file requirements.txt vào container
COPY requirements.txt /app/requirements.txt

# Cài đặt các thư viện Python
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple -r /app/requirements.txt

# Sao chép toàn bộ mã nguồn của AI Service vào thư mục /app/ai
# Lưu ý: Khi build, cần đứng ở thư mục 'ai' làm build context
COPY . /app/ai

# Expose cổng chạy FastAPI (8001)
EXPOSE 8001

# Lệnh khởi chạy FastAPI app bằng uvicorn
CMD ["uvicorn", "ai.main:app", "--host", "0.0.0.0", "--port", "8001"]
