# syntax=docker/dockerfile:1.26.0@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32
ARG BASE_IMAGE=codex-remote-dev-base:local
FROM ${BASE_IMAGE}

ARG TARGETARCH
ARG CODEX_RELEASE_TAG=rust-v0.146.0
ARG CODEX_AMD64_SHA256=5ba3b9405543953081f661d0854d266f76e2abbe51d41349355a36de7673776a
ARG CODEX_ARM64_SHA256=975bac91562abeedeb8f79636d51a86649b31f34a9de6a3bcb059565b6cf1f87
ARG PROJECT_VERSION=0.1.0-dev
ARG SOURCE_REVISION=local-untracked

LABEL org.opencontainers.image.title="Codex Remote Dev" \
      org.opencontainers.image.description="Community browser-hosted Codex CLI development container" \
      org.opencontainers.image.version="${PROJECT_VERSION}" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.documentation="https://github.com/eXPerience83/remote-dev-containers/blob/${SOURCE_REVISION}/third_party/README.md" \
      org.opencontainers.image.vendor="Community maintained; not affiliated with OpenAI" \
      io.github.experience83.remote-dev.project-license="Apache-2.0" \
      io.github.experience83.remote-dev.license-scope="Remote Dev project code only; bundled components retain upstream terms" \
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

COPY scripts/start-remote-dev-web.sh /usr/local/bin/start-remote-dev-web
COPY scripts/start-codex-web.sh /usr/local/bin/start-codex-web
COPY scripts/attach-remote-dev-tmux.sh /usr/local/bin/attach-remote-dev-tmux
COPY scripts/run-direct-session.sh /usr/local/bin/run-direct-session
COPY scripts/run-codex.sh /usr/local/bin/run-codex
COPY scripts/remote-dev-menu.sh /usr/local/bin/remote-dev-menu
COPY scripts/codex-menu.sh /usr/local/bin/codex-menu
COPY scripts/remote-dev-doctor.sh /usr/local/bin/remote-dev-doctor
COPY scripts/codex-doctor.sh /usr/local/bin/codex-doctor
COPY scripts/remote-dev-version.sh /usr/local/bin/remote-dev-version
COPY scripts/lib/remote-dev-runtime.sh /usr/local/lib/remote-dev/remote-dev-runtime.sh
COPY scripts/lib/format-short-revision.sh /usr/local/lib/remote-dev/format-short-revision.sh
COPY scripts/secure-persistent-state.sh /usr/local/bin/secure-persistent-state
COPY scripts/smoke-test.sh /usr/local/bin/codex-smoke-test

RUN --mount=type=bind,source=scripts/test-run-codex-policy.sh,target=/tmp/test-run-codex-policy,ro \
    --mount=type=bind,source=scripts/test-role-neutral-runtime.sh,target=/tmp/test-role-neutral-runtime,ro \
    chmod 0755 \
      /usr/local/bin/start-remote-dev-web \
      /usr/local/bin/start-codex-web \
      /usr/local/bin/attach-remote-dev-tmux \
      /usr/local/bin/run-direct-session \
      /usr/local/bin/run-codex \
      /usr/local/bin/remote-dev-menu \
      /usr/local/bin/codex-menu \
      /usr/local/bin/remote-dev-doctor \
      /usr/local/bin/codex-doctor \
      /usr/local/bin/remote-dev-version \
      /usr/local/bin/secure-persistent-state \
      /usr/local/bin/codex-smoke-test \
    && chmod 0644 \
      /usr/local/lib/remote-dev/remote-dev-runtime.sh \
      /usr/local/lib/remote-dev/format-short-revision.sh \
    && REMOTE_DEV_RUNTIME_LIB=/usr/local/lib/remote-dev/remote-dev-runtime.sh bash /tmp/test-role-neutral-runtime \
    && bash /tmp/test-run-codex-policy \
    && grep -Fx 'export REMOTE_DEV_ROLE=codex' /usr/local/bin/start-codex-web \
    && grep -Fx 'exec /usr/local/bin/start-remote-dev-web "$@"' /usr/local/bin/start-codex-web \
    && grep -Fx 'export REMOTE_DEV_ROLE=codex' /usr/local/bin/codex-menu \
    && grep -Fx 'exec /usr/local/bin/remote-dev-menu "$@"' /usr/local/bin/codex-menu \
    && grep -Fx 'export REMOTE_DEV_ROLE=codex' /usr/local/bin/codex-doctor \
    && grep -Fx 'exec /usr/local/bin/remote-dev-doctor "$@"' /usr/local/bin/codex-doctor \
    && run-codex --print-policy | grep -Fx 'Inner sandbox: disabled explicitly' \
    && run-codex --print-policy | grep -Fx 'Isolation boundary: outer container' \
    && run-codex --print-policy | grep -Fx 'Codex approval policy: untrusted' \
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
    && /usr/local/bin/secure-persistent-state \
    && REMOTE_DEV_ROLE=shell remote-dev-doctor | grep -Fx 'Role: shell' \
    && REMOTE_DEV_SKIP_TMUX_SMOKE=1 codex-smoke-test "$PROJECT_VERSION" "$SOURCE_REVISION"

WORKDIR /workspace
EXPOSE 7681

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD pgrep -x ttyd >/dev/null && codex --version >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/start-remote-dev-web"]
