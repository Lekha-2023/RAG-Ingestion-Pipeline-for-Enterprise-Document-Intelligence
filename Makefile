install:
	python -m pip install -e ".[dev]"
test:
	pytest -q
run:
	python run.py
docker-run:
	docker compose up --build
