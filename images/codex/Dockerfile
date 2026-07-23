# syntax=docker/dockerfile:1.25
ARG BASE_IMAGE=codex-remote-dev-base:local
FROM ${BASE_IMAGE}

ARG TARGETARCH
ARG CODEX_RELEASE_TAG=rust-v0.144.4
ARG PROJECT_VERSION=0.1.0-dev

LABEL org.opencontainers.image.title="Codex Remote Dev" \
      org.opencontainers.image.description="Community browser-hosted Codex CLI development container" \
      org.opencontainers.image.version="${PROJECT_VERSION}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.vendor="Community maintained; not affiliated with OpenAI"

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
    TMUX_SESSION=codex \
    START_MODE=menu \
    CODEX_CA_CERTIFICATE=

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Codex CLI: pinned official release asset + SHA-256 digest from GitHub release metadata.
RUN case "${TARGETARCH:-amd64}" in \
      amd64) asset="codex-x86_64-unknown-linux-musl.tar.gz"; binary="codex-x86_64-unknown-linux-musl" ;; \
      arm64) asset="codex-aarch64-unknown-linux-musl.tar.gz"; binary="codex-aarch64-unknown-linux-musl" ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && workdir="$(mktemp -d)" \
    && cd "$workdir" \
    && curl -fsSL "https://api.github.com/repos/openai/codex/releases/tags/${CODEX_RELEASE_TAG}" -o release.json \
    && digest="$(jq -r --arg asset "$asset" '.assets[] | select(.name == $asset) | .digest' release.json)" \
    && test -n "$digest" && test "$digest" != null \
    && curl -fsSL "https://github.com/openai/codex/releases/download/${CODEX_RELEASE_TAG}/${asset}" -o codex.tar.gz \
    && printf '%s  %s\n' "${digest#sha256:}" codex.tar.gz | sha256sum -c - \
    && tar -xzf codex.tar.gz \
    && install -m 0755 "$binary" /usr/local/bin/codex \
    && cd / \
    && rm -rf "$workdir"

COPY scripts/start-codex-web.sh /usr/local/bin/start-codex-web
COPY scripts/codex-menu.sh /usr/local/bin/codex-menu
COPY scripts/codex-doctor.sh /usr/local/bin/codex-doctor
COPY scripts/smoke-test.sh /usr/local/bin/codex-smoke-test
COPY third_party/ /usr/share/doc/codex-remote-dev/third_party/

RUN chmod 0755 \
      /usr/local/bin/start-codex-web \
      /usr/local/bin/codex-menu \
      /usr/local/bin/codex-doctor \
      /usr/local/bin/codex-smoke-test \
    && mkdir -p \
      /workspace \
      /root/.codex \
      /root/.config/gh \
      /root/.config/git \
      /root/.ssh \
    && codex-smoke-test

WORKDIR /workspace
EXPOSE 7681

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD pgrep -x ttyd >/dev/null && codex --version >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/start-codex-web"]
