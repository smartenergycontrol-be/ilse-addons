ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20
FROM ${BUILD_FROM}

RUN pip3 install --no-cache-dir "s2-python[ws]>=0.11,<0.12"

COPY app /app
WORKDIR /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1

CMD ["python3", "-m", "ilse_s2.main", "--options", "/data/options.json"]
