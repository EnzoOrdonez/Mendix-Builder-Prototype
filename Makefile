.PHONY: setup setup-python setup-node build-sdk test test-unit test-integration test-e2e lint serve clean

# ============================================
# MendixFormAgent — Makefile
# ============================================

# --- Setup ---
setup: setup-python setup-node build-sdk
	@echo "[mendex] Setup completo."

setup-python:
	@echo "[mendex] Instalando dependencias Python..."
	pip install -e ".[dev]"

setup-node:
	@echo "[mendex] Instalando dependencias Node.js..."
	cd mendix_sdk && npm install

build-sdk:
	@echo "[mendex] Compilando módulo TypeScript..."
	cd mendix_sdk && npm run build

# --- Test ---
test: test-unit

test-unit:
	pytest tests/unit -v

test-integration:
	pytest tests/integration -v

test-e2e:
	pytest tests/e2e -v -m e2e

test-all:
	pytest tests/ -v

# --- Lint ---
lint:
	ruff check src/ tests/
	ruff format --check src/ tests/
	mypy src/

format:
	ruff check --fix src/ tests/
	ruff format src/ tests/

# --- Server ---
serve:
	python -m mendex serve

# --- Clean ---
clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	rm -rf mendix_sdk/dist
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "[mendex] Limpieza completa."
