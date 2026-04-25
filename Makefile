.PHONY: dev backend frontend install

install:
	cd backend && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && pnpm install

backend:
	USE_MOCK_EMBEDDINGS=true uvicorn backend.app:app --reload --port 8000

backend-real:
	uvicorn backend.app:app --reload --port 8000

frontend:
	cd frontend && pnpm dev

dev:
	@echo "Run 'make backend' and 'make frontend' in two terminals."
	@echo "Or use: (cd backend && .venv/bin/uvicorn backend.app:app --reload --port 8000 --app-dir ..) & (cd frontend && pnpm dev)"
