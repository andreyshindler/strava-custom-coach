FROM python:3.12-slim

WORKDIR /app

# Install gunicorn + onboarding deps
COPY onboarding/requirements.txt /tmp/req-onboarding.txt
RUN pip install --no-cache-dir -r /tmp/req-onboarding.txt gunicorn


# Copy all source
COPY scripts/ /app/scripts/
COPY onboarding/ /app/onboarding/

# Default: telegram bot. Override in docker-compose for the web service.
ENV PYTHONPATH=/app/scripts
CMD ["python", "/app/scripts/telegram_bot.py", "--loop"]
