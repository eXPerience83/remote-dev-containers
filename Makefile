SHELL := /bin/bash
DATA_ROOT ?= data
.DEFAULT_GOAL := build

.PHONY: build smoke preflight validate agent-contract-tests package ttyd-osc52-check

ttyd-osc52-check:
	python3 web/ttyd-osc52/validate.py
	python3 web/ttyd-osc52/generate.py --check
	node web/ttyd-osc52/test_osc52.js
	python3 web/ttyd-osc52/test_generate.py

build:
	./scripts/build-local.sh

smoke: agent-contract-tests
	docker run --rm --entrypoint /usr/local/bin/codex-smoke-test remote-dev:local
	docker run --rm \
		--network none \
		--entrypoint /opt/remote-dev/mise/shims/python \
		-v "$(CURDIR)/scripts/test-remote-dev-context7-runtime-isolation.py:/tmp/test-remote-dev-context7-runtime-isolation.py:ro" \
		-e REMOTE_DEV_CONTEXT7_DEVICE_LOGIN_HELPER=/usr/local/bin/remote-dev-context7-device-login \
		remote-dev:local /tmp/test-remote-dev-context7-runtime-isolation.py
	timeout --foreground 60s docker run --rm \
		--user 0:0 \
		--network none \
		--tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
		--entrypoint /opt/remote-dev/mise/shims/python \
		-v "$(CURDIR)/scripts/test-codex-runtime-noexec-staging.py:/tmp/test-codex-runtime-noexec-staging.py:ro" \
		-e REMOTE_DEV_CODEX_RUNTIME_MANAGER=/usr/local/bin/remote-dev-codex-runtime \
		remote-dev:local /tmp/test-codex-runtime-noexec-staging.py
	bash scripts/runtime-smoke-test.sh remote-dev:local

preflight:
	python3 scripts/preflight-data-layout.py --root "$(DATA_ROOT)"

agent-contract-tests:
	python3 scripts/test-development-scratch.py
	python3 scripts/test_truenas_acl_audit.py
	REMOTE_DEV_RUNTIME_LIB=./scripts/lib/remote-dev-runtime.sh REMOTE_DEV_TEST_SKIP_STATE_BOUNDARY=1 bash scripts/test-role-neutral-runtime.sh
	REMOTE_DEV_MENU=./scripts/remote-dev-menu.sh bash scripts/test-remote-dev-menu.sh
	REMOTE_DEV_MENU=./scripts/remote-dev-menu.sh REMOTE_DEV_RUNTIME_LIB=./scripts/lib/remote-dev-runtime.sh bash scripts/test-project-menu-selection.sh
	REMOTE_DEV_MENU=./scripts/remote-dev-menu.sh bash scripts/test-antigravity-menu.sh
	REMOTE_DEV_RUN_ANTIGRAVITY=./scripts/run-antigravity.sh bash scripts/test-run-antigravity-picker.sh
	REMOTE_DEV_ATTACH_TMUX=./scripts/attach-remote-dev-tmux.sh bash scripts/test-direct-codex-project-entry.sh
	bash scripts/test-antigravity-runtime.sh
	python3 scripts/test-remote-dev-context7-device-login.py
	python3 scripts/test-remote-dev-context7-adoption.py
	python3 scripts/test-remote-dev-context7-runtime-isolation.py
	bash scripts/test-remote-dev-context7-entrypoint.sh

validate: agent-contract-tests ttyd-osc52-check
	bash -n scripts/*.sh scripts/lib/*.sh scripts/fixtures/*.sh
	python3 -m py_compile web/ttyd-osc52/generate.py web/ttyd-osc52/validate.py web/ttyd-osc52/test_generate.py scripts/remote-dev-launcher.py scripts/remote-dev-codex-runtime.py scripts/remote-dev-prepare-development-scratch.py scripts/test-development-scratch.py scripts/test-remote-dev-codex-runtime.py scripts/test-codex-runtime-code-mode-probe.py scripts/test-codex-runtime-noexec-staging.py scripts/init-data-layout.py scripts/preflight-data-layout.py scripts/truenas-acl-audit.py scripts/test_truenas_acl_audit.py scripts/lib/data_layout.py scripts/antigravity_download.py scripts/run-antigravity-inspection.py scripts/inspect-antigravity-cli.py scripts/detect-antigravity-installer.py scripts/discover-antigravity-payload.py scripts/reconcile-antigravity-review-state.py scripts/update-antigravity-review-evidence.py scripts/update-antigravity-review-doc.py scripts/validate-antigravity-review-artifact.py scripts/test_antigravity_download.py scripts/test_run_antigravity_inspection.py scripts/test_detect_antigravity_installer.py scripts/test_discover_antigravity_payload.py scripts/test_reconcile_antigravity_review_state.py scripts/test_update_antigravity_review_evidence.py scripts/test_update_antigravity_review_doc.py scripts/test_validate_antigravity_review_artifact.py scripts/test_optional_review_workflows.py scripts/remote-dev-context7-device-login.py scripts/update-context7-review.py scripts/test_update_context7_review.py scripts/test-remote-dev-context7-device-login.py scripts/test-remote-dev-context7-adoption.py scripts/test-remote-dev-context7-runtime-isolation.py scripts/test_single_stack_compose.py scripts/test_canonical_data_layout.py scripts/test_preflight_data_layout.py scripts/test_inspect_antigravity_cli.py scripts/validate-renovate-ownership.py scripts/test_validate_renovate_ownership.py scripts/format-edge-build-identity.py scripts/test_edge_build_identity.py scripts/update-upstream-changelog.py scripts/test_update_upstream_changelog.py scripts/render-vulnerability-rescan-alert.py scripts/test_render_vulnerability_rescan_alert.py scripts/test_resolve_published_image_digest.py scripts/test_periodic_image_rescan_workflow.py scripts/test_publish_edge_security_cadence.py
	python3 scripts/test-codex-runtime-code-mode-probe.py
	python3 scripts/test_edge_build_identity.py
	python3 scripts/test_update_upstream_changelog.py
	python3 scripts/test_update_context7_review.py
	python3 scripts/test_antigravity_download.py
	python3 scripts/test_run_antigravity_inspection.py
	python3 scripts/test_detect_antigravity_installer.py
	python3 scripts/test_discover_antigravity_payload.py
	python3 scripts/test_reconcile_antigravity_review_state.py
	python3 scripts/test_update_antigravity_review_evidence.py
	python3 scripts/test_update_antigravity_review_doc.py
	python3 scripts/test_validate_antigravity_review_artifact.py
	python3 scripts/test_optional_review_workflows.py
	python3 scripts/update-antigravity-review-doc.py --reviewed third_party/antigravity-cli-inspection.json
	python3 scripts/validate-antigravity-review-artifact.py --kind detection --artifact third_party/antigravity-cli-detection.json
	bash scripts/test-image-identity.sh
	REMOTE_DEV_IMAGE_NAMES_LIB=./scripts/lib/remote-dev-image-names.sh bash scripts/test-image-name-compat.sh
	bash scripts/test-compose-image-compat.sh
	REMOTE_DEV_LAUNCHER=./scripts/remote-dev-launcher.py bash scripts/test-remote-dev-launcher.sh
	python3 scripts/test_single_stack_compose.py
	python3 scripts/test_canonical_data_layout.py
	python3 scripts/test_preflight_data_layout.py
	python3 scripts/test_inspect_antigravity_cli.py
	bash scripts/validate-version-pins.sh
	jq -e . renovate.json >/dev/null
	python3 scripts/validate-renovate-ownership.py --root .
	python3 scripts/test_validate_renovate_ownership.py
	python3 scripts/test_render_vulnerability_rescan_alert.py
	python3 scripts/test_resolve_published_image_digest.py
	python3 scripts/test_periodic_image_rescan_workflow.py
	python3 scripts/test_publish_edge_security_cadence.py
	jq -e '.schema_version == 2 and .blocking_findings == []' third_party/antigravity-cli-inspection.json >/dev/null
	@for file in compose/*.yml; do docker compose -f "$$file" config --quiet; echo "OK $$file"; done

package:
	tar --exclude=.git -czf codex-remote-dev-starter.tar.gz .
