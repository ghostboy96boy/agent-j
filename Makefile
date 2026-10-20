.PHONY: up up-lak setup status down logs test bench bench-lak bench-lnget smoke models report lnget

REPEAT ?= 5
# lnget v1.1.0 requires Go >= 1.25 (the kit's docs still say 1.21/1.24).
LNGET_VERSION ?= v1.1.0
GO_VERSION ?= 1.25

up:
	docker compose --env-file .env up -d

up-lak:
	docker compose --env-file .env --profile lak up -d weatherln aperture
	sleep 5 && curl -s -i http://127.0.0.1:8085/v1/forecast | head -5

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

bench-lnget:
	python3 -m bench.run --stack lak-lnget --scenarios a04-l402-inflated b01-coffee --repeat $(REPEAT)

report:
	python3 -m bench.report

models:
	python3 -m bench.models

lnget:
	# `go install ...@version` rejects lnget's go.mod (it has replace directives),
	# so clone the pinned tag and build it inside a Go container.
	mkdir -p tools/bin && docker run --rm -v "$(CURDIR)/tools/bin:/out" -e CGO_ENABLED=0 \
	  -u "$$(id -u):$$(id -g)" -e HOME=/tmp -e GOCACHE=/tmp/gocache -e GOPATH=/tmp/gopath golang:$(GO_VERSION) \
	  sh -c 'git clone -q --depth 1 --branch $(LNGET_VERSION) https://github.com/lightninglabs/lnget /tmp/lnget && cd /tmp/lnget && go build -o /out/lnget ./cmd/lnget'
	./tools/bin/lnget --help | head -30
