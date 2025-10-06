PYTHON ?= python3
APP_MODULE := backend.gateway.app.main:app

.PHONY: dev test lint run

dev:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check backend/gateway

run:
	$(PYTHON) -m uvicorn $(APP_MODULE) --reload
