FROM python:3.11-slim
RUN apt-get update && apt-get install -y \
    build-essential cmake pkg-config ninja-build \
    ffmpeg libchromaprint-tools \
    libavdevice-dev libavfilter-dev libavformat-dev \
    libavcodec-dev libswresample-dev libswscale-dev libavutil-dev \
    espeak \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY config.py models.py main.py ./
COPY services/ ./services/
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]