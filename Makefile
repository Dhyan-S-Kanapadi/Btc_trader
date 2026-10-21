.PHONY: install test lint up down frontend-install frontend-dev frontend-test frontend-build frontend-lint

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

frontend-install:
	npm --prefix frontend ci

frontend-dev:
	npm --prefix frontend run dev

frontend-test:
	npm --prefix frontend test

frontend-build:
	npm --prefix frontend run build
	npm --prefix frontend run check:bundle

frontend-lint:
	npm --prefix frontend run lint
