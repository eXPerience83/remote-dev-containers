SHELL := /bin/bash

.PHONY: build smoke validate package

build:
	./scripts/build-local.sh

smoke:
	docker run --rm --entrypoint /usr/local/bin/codex-smoke-test remote-dev:local
	bash scripts/runtime-smoke-test.sh remote-dev:local

validate:
	bash -n scripts/*.sh scripts/lib/*.sh
	REMOTE_DEV_IMAGE_NAMES_LIB=./scripts/lib/remote-dev-image-names.sh bash scripts/test-image-name-compat.sh
	bash scripts/validate-version-pins.sh
	jq -e . renovate.json >/dev/null
	@for file in compose/*.yml; do docker compose -f "$$file" config --quiet; echo "OK $$file"; done

package:
	tar --exclude=.git -czf codex-remote-dev-starter.tar.gz .
