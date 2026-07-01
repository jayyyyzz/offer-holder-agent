FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /app/frontend-react
COPY frontend-react/package.json frontend-react/package-lock.json ./
RUN npm ci
COPY frontend-react/ ./
RUN npm run build


FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV OFFER_AGENT_HOST=0.0.0.0
ENV OFFER_AGENT_PORT=8080
ENV PORT=8080
ENV OFFER_AGENT_RUNTIME_DATA_ROOT=/app/data
ENV OFFER_AGENT_SEED_DATA_ROOT=/app-seed-data

WORKDIR /app

COPY requirements.txt pyproject.toml README.md source_list.csv ./
COPY agent ./agent
COPY app ./app
COPY crawler ./crawler
COPY data ./data
COPY docs ./docs
COPY frontend ./frontend
COPY frontend-react ./frontend-react
COPY knowledge_base ./knowledge_base
COPY tests ./tests
RUN cp -R /app/data /app-seed-data

RUN pip install -r requirements.txt

COPY --from=frontend-builder /app/frontend/index.html /app/frontend/index.html
COPY --from=frontend-builder /app/frontend/assets /app/frontend/assets

EXPOSE 8080

CMD ["sh", "-c", "python -m app.start_server --host 0.0.0.0 --port ${PORT:-8080}"]
