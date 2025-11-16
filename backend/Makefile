.PHONY: install migrate test run clean

install:
	pip install -r requirements.txt

migrate:
	alembic upgrade head

migrate-create:
	alembic revision --autogenerate -m "$(message)"

migrate-down:
	alembic downgrade -1

test:
	pytest

run:
	uvicorn app.main:app --reload --port 8000

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -f owlquill.db
