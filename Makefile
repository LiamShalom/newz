.PHONY: dev backend frontend install reset

install:
	cd backend && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && pnpm install

backend:
	backend/.venv/bin/uvicorn backend.app:app --reload --port 8000 --host 0.0.0.0

frontend:
	cd frontend && pnpm dev

dev:
	@echo "Run 'make backend' and 'make frontend' in two terminals."
	@echo "Or use: (cd backend && .venv/bin/uvicorn backend.app:app --reload --port 8000 --app-dir ..) & (cd frontend && pnpm dev)"

reset:
	-lsof -ti :8000 | xargs kill -9 2>/dev/null || true
	-lsof -ti :5173 | xargs kill -9 2>/dev/null || true
	rm -rf data/clips data/newz.db data/newz.db-shm data/newz.db-wal backend/data
	mkdir -p data/clips
	@echo "Reset done. Run 'make backend' and 'make frontend' in two terminals."
