# syntax=docker/dockerfile:1.26.0@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32
ARG BASE_IMAGE=remote-dev-base:local
FROM ${BASE_IMAGE}

ARG TARGETARCH
ARG CODEX_RELEASE_TAG=rust-v0.147.0
ARG CODEX_AMD64_SHA256=0246e2e773834e07f0fb5249ed6ebad12e4591e608f8c7bb97dd6a9690544c36
ARG CODEX_ARM64_SHA256=eb677c80f666b1ab8b4b1d083b66e8d614b1281d960bb6f9fd8ca98f58b38b90
ARG CODEX_CODE_MODE_HOST_AMD64_SHA256=0146adfaac8363ec9fcdb5895f7624db5b2e8617a283887938b7fb97a1dd4356
ARG CODEX_CODE_MODE_HOST_ARM64_SHA256=dfd4ff98ea4db30ed078af9c31b6f86e3da4836d0573aa87e225e5a5b54d3c7c
ARG PROJECT_VERSION=0.1.0-dev
ARG SOURCE_REVISION=local-untracked

LABEL org.opencontainers.image.title="Remote Dev" \
      org.opencontainers.image.description="Community browser-hosted remote development runtime with built-in Codex and optional vendor-installed agent roles" \
      org.opencontainers.image.version="${PROJECT_VERSION}" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.documentation="https://github.com/eXPerience83/remote-dev-containers/blob/${SOURCE_REVISION}/third_party/README.md" \
      org.opencontainers.image.vendor="Community maintained; not affiliated with OpenAI or Google" \
      io.github.experience83.remote-dev.project-license="Apache-2.0" \
      io.github.experience83.remote-dev.license-scope="Remote Dev project code only; bundled and runtime-installed components retain separate upstream terms" \
      io.github.experience83.remote-dev.third-party-notices="/usr/share/doc/remote-dev/third_party"

ENV HOME=/root \
    WORKSPACE=/workspace \
    CODEX_HOME=/root/.codex \
    GIT_CONFIG_GLOBAL=/root/.config/git/config \
    WEB_BIND=0.0.0.0 \
    WEB_PORT=7681 \
    WEB_BASE_PATH=/ \
    WEB_USERNAME=codex \
    WEB_MAX_CLIENTS=1 \
    WEB_CHECK_ORIGIN=1 \
    ALLOW_INSECURE_WEB=0 \
    REMOTE_DEV_ROLE=codex \
    START_MODE=menu \
    CODEX_CA_CERTIFICATE=

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Codex CLI: exact release asset verified against a repository-controlled SHA-256.
RUN case "${TARGETARCH}" in \
      amd64) asset="codex-x86_64-unknown-linux-musl.tar.gz"; binary="codex-x86_64-unknown-linux-musl"; expected_sha="$CODEX_AMD64_SHA256" ;; \
      arm64) asset="codex-aarch64-unknown-linux-musl.tar.gz"; binary="codex-aarch64-unknown-linux-musl"; expected_sha="$CODEX_ARM64_SHA256" ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && workdir="$(mktemp -d)" \
    && cd "$workdir" \
    && curl --fail --silent --show-error --location --retry 3 --retry-all-errors --connect-timeout 10 --max-time 300 \
      "https://github.com/openai/codex/releases/download/${CODEX_RELEASE_TAG}/${asset}" -o codex.tar.gz \
    && printf '%s  %s\n' "$expected_sha" codex.tar.gz | sha256sum -c - \
    && tar -xzf codex.tar.gz \
    && install -m 0755 "$binary" /usr/local/bin/codex \
    && cd / \
    && rm -rf "$workdir"

# Codex 0.147+ Code Mode uses a companion host process. Keep the existing
# outer-container isolation model and install only the matching official host
# beside /usr/local/bin/codex, where Codex resolves the legacy/sibling host.
RUN case "${TARGETARCH}" in \
      amd64) target="x86_64-unknown-linux-musl"; expected_sha="$CODEX_CODE_MODE_HOST_AMD64_SHA256" ;; \
      arm64) target="aarch64-unknown-linux-musl"; expected_sha="$CODEX_CODE_MODE_HOST_ARM64_SHA256" ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && asset="codex-code-mode-host-${target}.tar.gz" \
    && binary="codex-code-mode-host-${target}" \
    && workdir="$(mktemp -d)" \
    && cd "$workdir" \
    && curl --fail --silent --show-error --location --retry 3 --retry-all-errors --connect-timeout 10 --max-time 300 \
      "https://github.com/openai/codex/releases/download/${CODEX_RELEASE_TAG}/${asset}" -o code-mode-host.tar.gz \
    && printf '%s  %s\n' "$expected_sha" code-mode-host.tar.gz | sha256sum -c - \
    && member_count="$(tar -tzf code-mode-host.tar.gz | wc -l | tr -d ' ')" \
    && test "$member_count" = 1 \
    && test "$(tar -tzf code-mode-host.tar.gz)" = "$binary" \
    && tar -xzf code-mode-host.tar.gz \
    && install -m 0755 "$binary" /usr/local/bin/codex-code-mode-host \
    && cd / \
    && rm -rf "$workdir"

COPY scripts/start-remote-dev-web.sh /usr/local/bin/start-remote-dev-web
COPY scripts/start-codex-web.sh /usr/local/bin/start-codex-web
COPY scripts/attach-remote-dev-tmux.sh /usr/local/bin/attach-remote-dev-tmux
COPY scripts/run-direct-session.sh /usr/local/bin/run-direct-session
COPY scripts/run-codex.sh /usr/local/bin/run-codex
COPY scripts/remote-dev-codex-runtime.py /usr/local/bin/remote-dev-codex-runtime
COPY scripts/remote-dev-antigravity.sh /usr/local/bin/remote-dev-antigravity
COPY scripts/remote-dev-install-antigravity.sh /usr/local/bin/remote-dev-install-antigravity
COPY scripts/remote-dev-update-antigravity.sh /usr/local/bin/remote-dev-update-antigravity
COPY scripts/remote-dev-antigravity-oauth.py /usr/local/bin/remote-dev-antigravity-oauth
COPY scripts/remote-dev-antigravity-picker.py /usr/local/bin/remote-dev-antigravity-picker
COPY scripts/run-antigravity.sh /usr/local/bin/run-antigravity
COPY scripts/remote-dev-launcher.py /usr/local/bin/remote-dev-launcher
COPY scripts/remote-dev-menu.sh /usr/local/bin/remote-dev-menu
COPY scripts/codex-menu.sh /usr/local/bin/codex-menu
COPY scripts/remote-dev-doctor.sh /usr/local/bin/remote-dev-doctor
COPY scripts/codex-doctor.sh /usr/local/bin/codex-doctor
COPY scripts/remote-dev-healthcheck.sh /usr/local/bin/remote-dev-healthcheck
COPY scripts/remote-dev-version.sh /usr/local/bin/remote-dev-version
COPY scripts/lib/remote-dev-runtime.sh /usr/local/lib/remote-dev/remote-dev-runtime.sh
COPY scripts/lib/antigravity-paths.sh /usr/local/lib/remote-dev/antigravity-paths.sh
COPY scripts/lib/antigravity-runtime /usr/local/lib/remote-dev/antigravity-runtime
COPY scripts/lib/format-short-revision.sh /usr/local/lib/remote-dev/format-short-revision.sh
COPY scripts/secure-persistent-state.sh /usr/local/bin/secure-persistent-state
COPY scripts/smoke-test.sh /usr/local/bin/codex-smoke-test

RUN --mount=type=bind,source=scripts/test-run-codex-policy.sh,target=/tmp/test-run-codex-policy,ro \
    --mount=type=bind,source=scripts/test-remote-dev-menu.sh,target=/tmp/test-remote-dev-menu,ro \
    --mount=type=bind,source=scripts/test-role-neutral-runtime.sh,target=/tmp/test-role-neutral-runtime,ro \
    --mount=type=bind,source=scripts/test-remote-dev-launcher.sh,target=/tmp/test-remote-dev-launcher,ro \
    --mount=type=bind,source=scripts/remote-dev-codex-runtime.py,target=/tmp/remote-dev-codex-runtime.py,ro \
    --mount=type=bind,source=scripts/test-remote-dev-codex-runtime.py,target=/tmp/test-remote-dev-codex-runtime.py,ro \
    --mount=type=bind,source=scripts/test-codex-code-mode-host.py,target=/tmp/test-codex-code-mode-host.py,ro \
    --mount=type=bind,source=scripts/test-antigravity-oauth.py,target=/tmp/test-antigravity-oauth.py,ro \
    --mount=type=bind,source=scripts/test-antigravity-picker.py,target=/tmp/test-antigravity-picker.py,ro \
    --mount=type=bind,source=scripts/test-run-antigravity-picker.sh,target=/tmp/test-run-antigravity-picker.sh,ro \
    --mount=type=bind,source=scripts/test-antigravity-menu.sh,target=/tmp/test-antigravity-menu.sh,ro \
    chmod 0755 \
      /usr/local/bin/start-remote-dev-web \
      /usr/local/bin/start-codex-web \
      /usr/local/bin/attach-remote-dev-tmux \
      /usr/local/bin/run-direct-session \
      /usr/local/bin/run-codex \
      /usr/local/bin/remote-dev-codex-runtime \
      /usr/local/bin/remote-dev-antigravity \
      /usr/local/bin/remote-dev-install-antigravity \
      /usr/local/bin/remote-dev-update-antigravity \
      /usr/local/bin/remote-dev-antigravity-oauth \
      /usr/local/bin/remote-dev-antigravity-picker \
      /usr/local/bin/run-antigravity \
      /usr/local/bin/remote-dev-launcher \
      /usr/local/bin/remote-dev-menu \
      /usr/local/bin/codex-menu \
      /usr/local/bin/remote-dev-doctor \
      /usr/local/bin/codex-doctor \
      /usr/local/bin/remote-dev-healthcheck \
      /usr/local/bin/remote-dev-version \
      /usr/local/bin/secure-persistent-state \
      /usr/local/bin/codex-smoke-test \
    && chmod 0644 \
      /usr/local/lib/remote-dev/remote-dev-runtime.sh \
      /usr/local/lib/remote-dev/format-short-revision.sh \
    && chmod 0444 \
      /usr/local/lib/remote-dev/antigravity-paths.sh \
      /usr/local/lib/remote-dev/antigravity-runtime/*.sh \
    && python -m py_compile \
      /usr/local/bin/remote-dev-launcher \
      /usr/local/bin/remote-dev-codex-runtime \
      /usr/local/bin/remote-dev-antigravity-oauth \
      /usr/local/bin/remote-dev-antigravity-picker \
      /tmp/test-codex-code-mode-host.py \
    && python /tmp/test-remote-dev-codex-runtime.py \
    && REMOTE_DEV_CODEX_RUNTIME_ROOT=/tmp/nonexistent-codex-runtime /usr/local/bin/remote-dev-codex-runtime status --menu | grep -Eq '^Codex: bundled [0-9]+\.[0-9]+\.[0-9]+$' \
    && test -z "${REMOTE_DEV_CODEX_RUNTIME_ROOT:-}" \
    && python /tmp/test-antigravity-oauth.py \
    && REMOTE_DEV_ANTIGRAVITY_PICKER=/usr/local/bin/remote-dev-antigravity-picker python /tmp/test-antigravity-picker.py \
    && REMOTE_DEV_RUN_ANTIGRAVITY=/usr/local/bin/run-antigravity bash /tmp/test-run-antigravity-picker.sh \
    && REMOTE_DEV_MENU=/usr/local/bin/remote-dev-menu bash /tmp/test-antigravity-menu.sh \
    && REMOTE_DEV_RUNTIME_LIB=/usr/local/lib/remote-dev/remote-dev-runtime.sh bash /tmp/test-role-neutral-runtime \
    && REMOTE_DEV_LAUNCHER=/usr/local/bin/remote-dev-launcher bash /tmp/test-remote-dev-launcher \
    && REMOTE_DEV_MENU=/usr/local/bin/remote-dev-menu bash /tmp/test-remote-dev-menu \
    && bash /tmp/test-run-codex-policy \
    && test -x /usr/local/bin/codex-code-mode-host \
    && python /tmp/test-codex-code-mode-host.py \
    && grep -Fx 'export REMOTE_DEV_ROLE=codex' /usr/local/bin/start-codex-web \
    && grep -Fx 'exec /usr/local/bin/start-remote-dev-web "$@"' /usr/local/bin/start-codex-web \
    && grep -Fx 'export REMOTE_DEV_ROLE=codex' /usr/local/bin/codex-menu \
    && grep -Fx 'exec /usr/local/bin/remote-dev-menu "$@"' /usr/local/bin/codex-menu \
    && grep -Fx 'export REMOTE_DEV_ROLE=codex' /usr/local/bin/codex-doctor \
    && grep -Fx 'exec /usr/local/bin/remote-dev-doctor "$@"' /usr/local/bin/codex-doctor \
    && grep -Fx 'readonly runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh' /usr/local/bin/run-antigravity \
    && grep -Fx 'readonly oauth_helper=/usr/local/bin/remote-dev-antigravity-oauth' /usr/local/bin/run-antigravity \
    && grep -Fx 'readonly picker_helper=/usr/local/bin/remote-dev-antigravity-picker' /usr/local/bin/run-antigravity \
    && run-codex --print-policy | grep -Fx 'Inner sandbox: disabled explicitly' \
    && run-codex --print-policy | grep -Fx 'Isolation boundary: outer container' \
    && run-codex --print-policy | grep -Fx 'Codex approval mode: autonomous' \
    && run-codex --print-policy | grep -Fx 'Codex approval policy: never' \
    && run-codex --print-policy | grep -Fx 'Mode source: default' \
    && REMOTE_DEV_ROLE=antigravity REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1 remote-dev-antigravity status --menu | grep -Fx 'Antigravity: not installed' \
    && printf '%s\n' 'exit 91' > /tmp/antigravity-bash-env \
    && printf '%s\n' '#!/bin/sh' 'exit 92' > /tmp/curl \
    && chmod 0755 /tmp/curl \
    && /usr/bin/env \
      BASH_ENV=/tmp/antigravity-bash-env \
      PATH=/tmp \
      'BASH_FUNC_curl%%=() { exit 93; }' \
      REMOTE_DEV_ROLE=antigravity \
      REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1 \
      /usr/local/bin/remote-dev-antigravity status --menu \
      | /usr/bin/grep -Fx 'Antigravity: not installed' \
    && rm -f /tmp/antigravity-bash-env /tmp/curl \
    && test ! -e /root/.local/bin/agy \
    && install -d -m 0755 /usr/share/remote-dev /usr/share/doc/codex-remote-dev \
    && ln -sfn ../remote-dev/LICENSE /usr/share/doc/codex-remote-dev/LICENSE \
    && ln -sfn ../remote-dev/third_party /usr/share/doc/codex-remote-dev/third_party \
    && printf '%s\n' \
      "SOURCE_REVISION=${SOURCE_REVISION}" \
      "PROJECT_VERSION=${PROJECT_VERSION}" \
      "TARGETARCH=${TARGETARCH}" \
      "CODEX_RELEASE_TAG=${CODEX_RELEASE_TAG}" \
      "CODEX_AMD64_SHA256=${CODEX_AMD64_SHA256}" \
      "CODEX_ARM64_SHA256=${CODEX_ARM64_SHA256}" \
      "CODEX_CODE_MODE_HOST_AMD64_SHA256=${CODEX_CODE_MODE_HOST_AMD64_SHA256}" \
      "CODEX_CODE_MODE_HOST_ARM64_SHA256=${CODEX_CODE_MODE_HOST_ARM64_SHA256}" \
      > /usr/share/doc/remote-dev/third_party/CODEX-BUILD.env \
    && remote-dev-notices --check \
    && printf '%s\n' "$PROJECT_VERSION" > /usr/share/remote-dev/image-version \
    && printf '%s\n' "$SOURCE_REVISION" > /usr/share/remote-dev/source-revision \
    && chmod 0444 \
      /usr/share/remote-dev/image-version \
      /usr/share/remote-dev/source-revision \
      /usr/share/doc/remote-dev/third_party/CODEX-BUILD.env \
    && mkdir -p \
      /workspace \
      /root/.codex \
      /root/.config/gh \
      /root/.config/git \
      /root/.ssh \
      /root/.local/bin \
      /root/.local/share/remote-dev/codex-runtime \
      /root/.local/share/remote-dev/antigravity \
      /root/.gemini/antigravity-cli \
    && /usr/local/bin/secure-persistent-state \
    && if REMOTE_DEV_ROLE=codex REMOTE_DEV_CODEX_RUNTIME_ROOT=/workspace /usr/local/bin/secure-persistent-state >/dev/null 2>&1; then \
      echo 'unsafe Codex runtime root was accepted' >&2; exit 1; \
    fi \
    && REMOTE_DEV_ROLE=antigravity /usr/local/bin/secure-persistent-state \
    && REMOTE_DEV_ROLE=launcher remote-dev-doctor | grep -Fx 'Role: launcher' \
    && REMOTE_DEV_ROLE=shell remote-dev-doctor | grep -Fx 'Role: shell' \
    && REMOTE_DEV_ROLE=antigravity REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1 remote-dev-doctor | grep -Fx 'Role: antigravity' \
    && REMOTE_DEV_SKIP_TMUX_SMOKE=1 codex-smoke-test "$PROJECT_VERSION" "$SOURCE_REVISION"

WORKDIR /workspace
EXPOSE 7680 7681 7682

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD remote-dev-healthcheck

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/start-remote-dev-web"]
