FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY courtside ./courtside
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir -e ".[postgres]"
ENV PYTHONUNBUFFERED=1
CMD ["sh", "-c", "courtside migrate && courtside serve --port 8000"]
