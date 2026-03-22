FROM python:3.12-slim

WORKDIR /app

# Install system deps: espeak for TTS fallback, ffmpeg for audio conversion
RUN apt-get update && apt-get install -y --no-install-recommends \
    espeak \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install piper TTS (lightweight neural TTS)
RUN curl -L https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz \
    | tar -xz -C /usr/local/bin --strip-components=1 piper/piper \
    && chmod +x /usr/local/bin/piper

# Download piper voice model (en_US ryan medium)
RUN mkdir -p /root/.local/share/piper && \
    curl -L -o /root/.local/share/piper/en_US-ryan-medium.onnx \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/medium/en_US-ryan-medium.onnx && \
    curl -L -o /root/.local/share/piper/en_US-ryan-medium.onnx.json \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/medium/en_US-ryan-medium.onnx.json

# Install gunicorn + onboarding deps
COPY onboarding/requirements.txt /tmp/req-onboarding.txt
RUN pip install --no-cache-dir -r /tmp/req-onboarding.txt gunicorn


# Copy all source
COPY scripts/ /app/scripts/
COPY onboarding/ /app/onboarding/

# Default: telegram bot. Override in docker-compose for the web service.
ENV PYTHONPATH=/app/scripts
CMD ["python", "/app/scripts/telegram_bot.py", "--loop"]
