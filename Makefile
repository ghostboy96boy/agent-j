.PHONY: up setup status down logs test bench bench-lak smoke models report lnget

REPEAT ?= 5
# lnget v1.1.0 requires Go >= 1.25 (the kit's docs still say 1.21/1.24).
LNGET_VERSION ?= v1.1.0
GO_VERSION ?= 1.25

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
	python3 -m bench.run --strict --models groq/openai/gpt-oss-120b --scenarios b01-coffee

bench:
	python3 -m bench.run --repeat $(REPEAT)

bench-lak:
	python3 -m bench.run --stack lak-lncli --repeat $(REPEAT)

report:
	python3 -m bench.report

models:
	python3 -m bench.models

lnget:
	mkdir -p tools/bin && docker run --rm -v "$(CURDIR)/tools/bin:/out" -e GOBIN=/out -e CGO_ENABLED=0 -u "$$(id -u):$$(id -g)" -e GOCACHE=/tmp/gocache -e GOPATH=/tmp/gopath golang:$(GO_VERSION) go install github.com/lightninglabs/lnget/cmd/lnget@$(LNGET_VERSION) && ./tools/bin/lnget --help | head -20
