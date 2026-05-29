FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create data directory
RUN mkdir -p /data

ENV PYTHONPATH=/app
ENV LOG_LEVEL=INFO
ENV DB_PATH=/data/hyperion.db

EXPOSE 8000

CMD ["uvicorn", "api.gateway:app", "--host", "0.0.0.0", "--port", "8000"]
