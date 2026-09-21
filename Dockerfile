# Dockerfile for chip-resonance pipeline
# 適用於 Synology NAS / Linux server 長期運行
# Build: docker build -t chip-resonance .
# Run (manual): docker run --rm -v $(pwd)/data:/app/data -v $(pwd)/backend/.sessions:/app/backend/.sessions chip-resonance
# Run (cron):   docker compose up -d chip-resonance-cron

FROM mcr.microsoft.com/playwright:v1.40.0-jammy AS base

# Install Python + Node.js
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    nodejs npm \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Node helper deps
RUN npm init -y && npm install --no-audit --no-fund

WORKDIR /app

# 安裝 Python 依賴（分層 cache）
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip3 install --no-cache-dir -r /app/backend/requirements.txt

# 複製專案（會被 bind mount 覆蓋，所以這層只是 fallback）
COPY . /app

# 安裝 backend 套件
ENV PYTHONPATH=/app
ENV RL_JITTER=1.0

# 健康檢查
HEALTHCHECK NONE

# 預設入口：跑完整 pipeline
CMD ["python3", "-m", "backend.scripts.run_local", "--source", "all"]