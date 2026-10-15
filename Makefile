.PHONY: up setup status down logs test bench smoke

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
	python3 -m bench.run --models groq/llama-3.3-70b-versatile --scenarios b01-coffee

bench:
	python3 -m bench.run
