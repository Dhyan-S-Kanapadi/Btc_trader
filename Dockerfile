FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system trader && useradd --system --gid trader --create-home trader

COPY . .
RUN python -m pip install .

USER trader

ENTRYPOINT ["trader"]
CMD ["--help"]
