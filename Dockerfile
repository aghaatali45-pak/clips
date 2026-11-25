FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir yt-dlp
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py best-moments.js ./

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
