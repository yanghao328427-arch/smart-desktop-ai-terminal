FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860 \
    RFID_REGISTRY_PATH=/tmp/smart-desktop-rfid-users.json

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/yanghao328427-arch/smart-desktop-ai-terminal.git /app/source

WORKDIR /app/source
RUN pip install --no-cache-dir -r backend/requirements.txt

WORKDIR /app/source/backend

EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]