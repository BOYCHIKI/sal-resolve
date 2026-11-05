# The API, the worker and the one-off migration all run from this image; only the command differs.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SAL_STORAGE_DIR=/data/storage
COPY apps/api/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY apps/api/ ./
RUN useradd --create-home --uid 10001 sal && mkdir -p /data/storage && chown -R sal /data
USER sal
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
