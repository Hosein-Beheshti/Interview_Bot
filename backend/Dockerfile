FROM python:3.14-slim

# Log straight through rather than buffering output a crash would then discard.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first: this layer stays cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Install the package itself (deps already installed above) so `interview_bot`
# is importable regardless of working directory.
RUN pip install --no-cache-dir -e . --no-deps

# Drop privileges. A remote-code-execution bug in any dependency should not also
# hand over root inside the container.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Bind whatever port the platform assigns. Render, Fly, and Cloud Run all inject
# $PORT and route to it; a hard-coded port makes the container unreachable there.
# Shell form so the variable is expanded at runtime, with a local-dev default.
#
# `::` rather than 0.0.0.0: Railway's private network is IPv6-only, so the
# frontend's nginx proxy cannot reach an IPv4-only listener. A dual-stack socket
# still accepts IPv4 (as IPv4-mapped), so docker-compose is unaffected.
CMD ["sh", "-c", "exec uvicorn interview_bot.api.app:app --host :: --port ${PORT:-8000}"]
