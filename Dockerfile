FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CLAR_LOAD_DOTENV=0 \
    CLAR_RUNTIME_DIR=/data \
    CLAR_INVITES_FILE=/data/invites.json \
    HOST=0.0.0.0 \
    PORT=8765 \
    PUBLIC_MODE=1
WORKDIR /app
COPY requirements.txt requirements-server.txt ./
COPY LICENSE NOTICE ./
RUN pip install --no-cache-dir -r requirements-server.txt \
    && groupadd --gid 10001 clar \
    && useradd --uid 10001 --gid clar --no-create-home --shell /usr/sbin/nologin clar \
    && mkdir /data && chown clar:clar /data
COPY *.py ./
COPY config/ ./config/
COPY fixtures/ ./fixtures/
COPY benchmarks/ ./benchmarks/
COPY public/ ./public/
COPY shared/ ./shared/
COPY extension/ ./extension/
COPY tools/build_extension.py ./tools/build_extension.py
ARG CLAR_BACKEND=http://localhost:8765
ARG CLAR_EXTENSION_PROVIDER=local
RUN python tools/build_extension.py --backend "$CLAR_BACKEND" --default-provider "$CLAR_EXTENSION_PROVIDER"
USER 10001:10001
VOLUME ["/data"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=3)"
CMD ["python", "-m", "app"]
