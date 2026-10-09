FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY backend/requirements.txt backend/constraints.txt /app/backend/
RUN python -m pip install --requirement backend/requirements.txt
COPY scripts/prepare_report_font.py /app/scripts/prepare_report_font.py
RUN python /app/scripts/prepare_report_font.py --output /app/report-font/DejaVuSans.ttf
ENV REPORT_FONT_PATH=/app/report-font/DejaVuSans.ttf
COPY backend /app/backend
COPY migrations /app/migrations
COPY alembic.ini /app/alembic.ini
COPY deployment/entrypoint.sh /app/entrypoint.sh
RUN groupadd --system ayursage && useradd --system --gid ayursage --home-dir /app ayursage \
    && chmod 755 /app/entrypoint.sh /app/report-font \
    && chmod 644 /app/report-font/DejaVuSans.ttf
USER ayursage
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=3).read()" || exit 1
ENTRYPOINT ["/app/entrypoint.sh"]
