PYTHON ?= python3
APP_MODULE := backend.gateway.app.main:app
FRONTEND := frontend/amadeus-ui

.PHONY: dev test lint run format fmt

dev:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check backend/gateway
	npm --prefix $(FRONTEND) run lint

format fmt:
	$(PYTHON) -m ruff format backend/gateway
	npm --prefix $(FRONTEND) run format

run:
	$(PYTHON) -m uvicorn $(APP_MODULE) --reload
