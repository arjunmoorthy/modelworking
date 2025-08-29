# ----- Base Python image -----
FROM python:3.11-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system deps for psycopg2
RUN apt-get update && apt-get install -y build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

# ----- Install Python dependencies -----
COPY apps/patient-platform/patient-api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# ----- Copy application code -----
COPY apps/patient-platform/patient-api/src ./src
# Include model inputs (prompts, CTCAE docs/vector store) at /app/model_inputs
COPY apps/patient-platform/patient-api/model_inputs ./model_inputs

EXPOSE 8000

# Start FastAPI with uvicorn
# - Honor PORT env (default 8000) for App Runner
# - Enable proxy headers so WS works behind reverse proxies
CMD ["sh","-c","uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --app-dir src --proxy-headers --forwarded-allow-ips='*'"]