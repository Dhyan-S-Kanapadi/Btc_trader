.PHONY: install test lint up down

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest --basetemp .tmp/pytest -p no:cacheprovider

lint:
	python -m ruff check .
	python -m ruff format --check .

up:
	docker compose up --build

down:
	docker compose down
