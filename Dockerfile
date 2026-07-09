FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config ./config
COPY scripts ./scripts
COPY tests ./tests
COPY pyproject.toml ./pyproject.toml

EXPOSE 2100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "2100"]

COPY frontend/dist /app/frontend/dist
