.PHONY: install check backend-lint backend-test frontend-install frontend-lint frontend-build dev-backend dev-frontend inspect clean clean-all

PY_BACKEND := weatherflow-backend
PY_DEV := --package $(PY_BACKEND) --extra dev
DATA_DIR ?= $(HOME)/.local/share/weatherflow/data

install:
	uv sync --all-packages --all-extras
	cd frontend && npm install

check: backend-lint backend-test frontend-lint frontend-build

backend-lint:
	uv run $(PY_DEV) ruff check backend/app backend/tests cli/weatherflow_cli

backend-test:
	uv run $(PY_DEV) pytest backend/tests -q

frontend-install:
	cd frontend && npm install

frontend-lint:
	cd frontend && npm run lint

frontend-build:
	cd frontend && npm run build

dev-backend:
	DATA_DIR=$(DATA_DIR) uv run --package $(PY_BACKEND) uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8765

dev-frontend:
	cd frontend && npm run dev

inspect:
	@echo "Repository size:"
	@du -sh .
	@echo ""
	@echo "Runtime data:"
	@du -sh "$(DATA_DIR)" 2>/dev/null || true
	@echo ""
	@echo "Generated directories in repo:"
	@find . -type d \( -name '.venv' -o -name 'node_modules' -o -name '.next' -o -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' -o -name '*.egg-info' \) -prune -print | sort
	@echo ""
	@echo "Local-only files in repo:"
	@find . -maxdepth 4 -type f \( -name '.env' -o -name '*.db' -o -name '*.db-wal' -o -name '*.db-shm' -o -name '*.pyc' \) -print | sort

clean:
	find . -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' -o -name '.next' -o -name '*.egg-info' \) -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
	rm -rf .weatherflow backend/data

clean-all: clean
	rm -rf .venv backend/.venv cli/.venv frontend/node_modules
