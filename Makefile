.PHONY: install test lint up down

DATABASE_URL ?= postgresql+psycopg://paper:paper@localhost:5432/paper_trader
export DATABASE_URL

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest --basetemp .tmp/pytest -p no:cacheprovider

lint:
	python -m ruff check .
	python -m ruff format --check .

up:
	docker compose up --build -d

down:
	docker compose down
