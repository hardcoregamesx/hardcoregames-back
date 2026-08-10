FROM python:3.10-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN python -c "import io; p='requirements.txt'; s=io.open(p, encoding='utf-8-sig').read(); io.open(p,'w',encoding='utf-8').write(s)"
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN SECRET_KEY=build-only DEBUG=False ALLOWED_HOSTS=localhost DB_NAME=x DB_USER=x DB_PASSWORD=x DB_HOST=localhost DB_PORT=5432 python manage.py collectstatic --noinput
CMD ["gunicorn","ecommerceHardcoregamesBack.wsgi:application","--bind","0.0.0.0:8000","--workers","3","--timeout","120"]
