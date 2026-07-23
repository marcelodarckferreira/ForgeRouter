FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# GIT_SHA identifies the exact commit this image was built from — passed by
# scripts/build.sh (git rev-parse --short HEAD). Not set => "unknown", which is
# itself a useful signal that an image was built outside the standard script.
ARG GIT_SHA=unknown
ENV FORGEROUTER_GIT_SHA=$GIT_SHA

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY VERSION ./VERSION
COPY app ./app
COPY config ./config
COPY scripts ./scripts
COPY tests ./tests
COPY pyproject.toml ./pyproject.toml

EXPOSE 2100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "2100"]

COPY frontend/dist /app/frontend/dist
