FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY models/ models/
COPY data/ data/
COPY api/ api/
COPY scraper/ scraper/

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
