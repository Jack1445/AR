FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PYTHONUNBUFFERED=1 AR_PORTAL_BIND=0.0.0.0 AR_PORTAL_PORT=38480
EXPOSE 38480
CMD ["python", "portal_server.py"]
