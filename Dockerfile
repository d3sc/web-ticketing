FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FLASK_APP=helpdesk
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 app
COPY --chown=app:app . .
USER app
EXPOSE 8000
CMD ["sh", "-c", "flask db upgrade && exec gunicorn --bind 0.0.0.0:8000 --workers 2 --threads 4 --access-logfile - 'helpdesk:create_app()'"]
