FROM node:22-bookworm-slim AS web
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 REAI_ENV=online-demo REAI_CHAT_PROVIDER=mock REAI_DATA_DIR=/app/data
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --system --create-home --user-group reai \
    && mkdir -p /app/data \
    && chown reai:reai /app/data
COPY backend/app ./app
COPY --from=web /build/dist /app/frontend/dist
USER reai
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
