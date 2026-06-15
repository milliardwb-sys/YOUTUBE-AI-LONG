.PHONY: api demo job-demo test mobile-check check docker-up docker-down

api:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

demo:
	cd backend && python run_demo.py

job-demo:
	cd backend && RUN_JOBS_INLINE=true python run_job_demo.py

test:
	cd backend && pytest

mobile-check:
	cd mobile && npm run check

check:
	cd backend && python -c "import app.main" && pytest
	cd mobile && npm run check

docker-up:
	docker compose up --build

docker-down:
	docker compose down
