FROM python:3.11-slim

# System dependencies for WeasyPrint PDF generation and PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    libpq-dev \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

EXPOSE 8000

# Shell form so $PORT (set by Render/Fly/Railway) is expanded at runtime.
CMD gunicorn "app:create_app()" --bind "0.0.0.0:${PORT:-8000}" --workers 2 --timeout 120
