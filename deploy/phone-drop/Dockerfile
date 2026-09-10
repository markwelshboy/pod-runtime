FROM python:3.12-slim

RUN python -m pip install --no-cache-dir \
      'huggingface-hub>=1.29,<2' \
      'requests>=2.32,<3'

WORKDIR /app
COPY bin/phone_drop.py /app/phone_drop.py

ENV PYTHONUNBUFFERED=1 \
    HF_XET_HIGH_PERFORMANCE=1 \
    PHONE_DROP_SPOOL=/spool \
    PHONE_DROP_POLL_SECONDS=20 \
    TELEGRAM_API_BASE=http://telegram-bot:8081 \
    TELEGRAM_LOCAL_FILE_ROOT=/phone-drop

ENTRYPOINT ["python", "/app/phone_drop.py", "worker"]
