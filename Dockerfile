FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Run as an unprivileged user. It owns /app only so the SQLite fallback
# (sqlite:///./escalate.db, used when DATABASE_URL is unset) can create its
# file; with Postgres nothing is written locally.
RUN useradd --create-home --uid 10001 app && chown app:app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
