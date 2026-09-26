# Playwright's image already ships Chromium and all its system libraries
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker ./worker
COPY demo_portal ./demo_portal
COPY scripts ./scripts

CMD ["python", "-m", "worker.main"]
