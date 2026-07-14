FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock .python-version README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY config ./config
COPY prompts ./prompts

RUN uv sync --locked --no-dev

ENV PYTHONUNBUFFERED=1 \
    NEWS_LOG_FILE=/tmp/news-ingestion.log \
    NEWS_OUTPUT_DIR=/tmp/news-output

ENTRYPOINT ["uv", "run", "--no-sync", "news-ingestion"]
CMD ["run", "--json"]
