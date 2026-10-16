.PHONY: up setup status down logs test bench smoke models

up:
	docker compose --env-file .env up -d

setup:
	bash scripts/setup.sh

status:
	bash scripts/status.sh

logs:
	docker compose logs -f --tail=100

down:
	docker compose down -v

test:
	python3 -m unittest discover -s tests

smoke:
	python3 -m bench.run --models groq/openai/gpt-oss-120b --scenarios b01-coffee

bench:
	python3 -m bench.run

models:
	python3 -m bench.models
