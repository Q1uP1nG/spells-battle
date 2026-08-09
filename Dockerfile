FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt \
    && addgroup --system spells \
    && adduser --system --ingroup spells --home /app spells

COPY config.py ./
COPY game ./game
COPY models ./models
COPY network ./network
COPY server ./server

USER spells

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=3).read()"

CMD ["python", "-m", "server.app"]
