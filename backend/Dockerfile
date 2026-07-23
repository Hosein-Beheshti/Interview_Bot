FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Install the package itself (deps already installed above) so `interview_bot`
# is importable regardless of working directory.
RUN pip install --no-cache-dir -e . --no-deps

CMD ["uvicorn", "interview_bot.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
