FROM python:3.11-slim

WORKDIR /app

# ffmpeg for video splitting and stitching
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

# Install deps first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . /app/backend

# Railway provides $PORT at runtime; bind 0.0.0.0 so the container is reachable.
# --app-dir /app so `backend.app:app` resolves; the COPY above places the package
# at /app/backend.
WORKDIR /app
EXPOSE 8000
CMD ["sh", "-c", "uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8000} --app-dir ."]
