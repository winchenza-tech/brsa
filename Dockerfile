FROM python:3.11-slim

# Sistem araçlarını kur
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-tur \
    chromium \
    libglib2.0-0 \
    libnss3 \
    libatk-bridge2.0-0 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpangocairo-1.0-0 \
    libgtk-3-0 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Playwright'ın kendi Chromium indirmesini engelle, sistemininkini kullan
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

# Çalışma klasörü
WORKDIR /app

# Önce bağımlılıkları kur (cache için ayrı adım)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install-deps chromium

# Kodları kopyala
COPY . .

# Botu başlat
CMD ["python", "main.py"]
