SHELL := /bin/bash

.PHONY: build smoke validate package

build:
	./scripts/build-local.sh

smoke:
	docker run --rm --entrypoint /usr/local/bin/codex-smoke-test remote-dev:local
	bash scripts/runtime-smoke-test.sh remote-dev:local

validate:
	bash -n scripts/*.sh scripts/lib/*.sh
	python3 -m py_compile scripts/remote-dev-launcher.py scripts/test_single_stack_compose.py scripts/test_canonical_data_layout.py
	REMOTE_DEV_IMAGE_NAMES_LIB=./scripts/lib/remote-dev-image-names.sh bash scripts/test-image-name-compat.sh
	bash scripts/test-compose-image-compat.sh
	REMOTE_DEV_LAUNCHER=./scripts/remote-dev-launcher.py bash scripts/test-remote-dev-launcher.sh
	python3 scripts/test_single_stack_compose.py
	python3 scripts/test_canonical_data_layout.py
	bash scripts/validate-version-pins.sh
	jq -e . renovate.json >/dev/null
	@for file in compose/*.yml; do docker compose -f "$$file" config --quiet; echo "OK $$file"; done

package:
	tar --exclude=.git -czf codex-remote-dev-starter.tar.gz .
