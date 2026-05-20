FROM python:3.11-slim

WORKDIR /app

# نصب curl (برای نصب bun) و ffmpeg
RUN apt-get update && apt-get install -y curl ffmpeg && rm -rf /var/lib/apt/lists/*

# نصب bun (یک اجراکننده سریع جاوااسکریپت برای حل چالش‌های یوتیوب)
RUN curl -fsSL https://bun.sh/install | bash
ENV PATH="/root/.bun/bin:${PATH}"

# کپی فایل requirements و نصب وابستگی‌های پایتون
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# کپی بقیه فایل‌های پروژه
COPY . .

# اجرای ربات
CMD ["python", "bale_web.py"]
