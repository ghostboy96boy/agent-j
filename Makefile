.PHONY: up setup status down logs

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
