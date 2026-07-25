# syntax=docker/dockerfile:1.25
ARG UBUNTU_VERSION=26.04
FROM ubuntu:${UBUNTU_VERSION}

# Re-declare the pre-FROM argument so it is available inside this build stage.
ARG UBUNTU_VERSION
ARG TARGETARCH
ARG BASE_VERSION=0.1.0-dev
ARG GH_VERSION=2.96.0
ARG TTYD_VERSION=1.7.7
ARG MISE_VERSION=2026.5.3
ARG PYTHON_VERSION=3.14.6
ARG NODE_VERSION=24.17.0
ARG UV_VERSION=0.11.30

LABEL org.opencontainers.image.title="Remote Dev Base" \
      org.opencontainers.image.description="Community remote development base for browser-hosted coding agents" \
      org.opencontainers.image.version="${BASE_VERSION}" \
      org.opencontainers.image.base.name="docker.io/library/ubuntu:${UBUNTU_VERSION}" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    HOME=/root \
    TERM=xterm-256color \
    COLORTERM=truecolor \
    REMOTE_DEV_UBUNTU_VERSION=${UBUNTU_VERSION} \
    MISE_DATA_DIR=/opt/remote-dev/mise \
    MISE_CACHE_DIR=/opt/remote-dev/mise-cache \
    MISE_CONFIG_DIR=/etc/mise \
    MISE_GLOBAL_CONFIG_FILE=/etc/mise/config.toml \
    PATH=/opt/remote-dev/mise/shims:/opt/remote-dev/mise/bin:/root/.local/bin:${PATH} \
    GH_CONFIG_DIR=/root/.config/gh \
    GH_HOST=github.com \
    GH_PAGER=cat \
    GH_NO_UPDATE_NOTIFIER=1 \
    GH_NO_EXTENSION_UPDATE_NOTIFIER=1 \
    DO_NOT_TRACK=1

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        bubblewrap \
        build-essential \
        ca-certificates \
        curl \
        fd-find \
        fzf \
        git \
        git-lfs \
        gzip \
        jq \
        less \
        libbz2-dev \
        libffi-dev \
        liblzma-dev \
        libreadline-dev \
        libsqlite3-dev \
        libssl-dev \
        make \
        nano \
        openssh-client \
        patch \
        pkg-config \
        procps \
        ripgrep \
        rsync \
        shellcheck \
        sqlite3 \
        tar \
        tini \
        tmux \
        tzdata \
        unzip \
        wget \
        xz-utils \
        zip \
        zlib1g-dev \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd \
    && git lfs install --system \
    && rm -rf /var/lib/apt/lists/*

# GitHub CLI: official release tarball + official checksum file.
RUN case "${TARGETARCH:-amd64}" in \
      amd64) gh_arch=amd64 ;; \
      arm64) gh_arch=arm64 ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && workdir="$(mktemp -d)" \
    && cd "$workdir" \
    && archive="gh_${GH_VERSION}_linux_${gh_arch}.tar.gz" \
    && curl -fsSLO "https://github.com/cli/cli/releases/download/v${GH_VERSION}/${archive}" \
    && curl -fsSLO "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_checksums.txt" \
    && grep " ${archive}$" "gh_${GH_VERSION}_checksums.txt" | sha256sum -c - \
    && tar -xzf "$archive" \
    && install -m 0755 "gh_${GH_VERSION}_linux_${gh_arch}/bin/gh" /usr/local/bin/gh \
    && cd / \
    && rm -rf "$workdir"

# ttyd: official static binary + official SHA256SUMS.
RUN case "${TARGETARCH:-amd64}" in \
      amd64) ttyd_arch=x86_64 ;; \
      arm64) ttyd_arch=aarch64 ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && workdir="$(mktemp -d)" \
    && cd "$workdir" \
    && asset="ttyd.${ttyd_arch}" \
    && curl -fsSLO "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/${asset}" \
    && curl -fsSLO "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/SHA256SUMS" \
    && grep " ${asset}$" SHA256SUMS | sha256sum -c - \
    && install -m 0755 "$asset" /usr/local/bin/ttyd \
    && cd / \
    && rm -rf "$workdir"

# mise: official release asset; digest is read from the pinned GitHub release metadata.
RUN case "${TARGETARCH:-amd64}" in \
      amd64) mise_arch=x64 ;; \
      arm64) mise_arch=arm64 ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && workdir="$(mktemp -d)" \
    && cd "$workdir" \
    && asset="mise-v${MISE_VERSION}-linux-${mise_arch}" \
    && curl -fsSL "https://api.github.com/repos/jdx/mise/releases/tags/v${MISE_VERSION}" -o release.json \
    && digest="$(jq -r --arg asset "$asset" '.assets[] | select(.name == $asset) | .digest' release.json)" \
    && test -n "$digest" && test "$digest" != null \
    && curl -fsSL "https://github.com/jdx/mise/releases/download/v${MISE_VERSION}/${asset}" -o mise \
    && printf '%s  %s\n' "${digest#sha256:}" mise | sha256sum -c - \
    && install -m 0755 mise /usr/local/bin/mise \
    && cd / \
    && rm -rf "$workdir"

# One current runtime per language. Other runtimes are deliberately not bundled.
RUN mkdir -p "$MISE_DATA_DIR" "$MISE_CACHE_DIR" "$MISE_CONFIG_DIR" \
    && mise settings set experimental true \
    && mise use --global \
        "python@${PYTHON_VERSION}" \
        "node@${NODE_VERSION}" \
        "uv@${UV_VERSION}" \
    && python --version \
    && node --version \
    && npm --version \
    && uv --version \
    && rm -rf "$MISE_CACHE_DIR"/*

COPY config/tmux.conf /etc/tmux.conf
COPY scripts/base-verify.sh /usr/local/bin/remote-dev-base-verify
RUN chmod 0644 /etc/tmux.conf \
    && chmod 0755 /usr/local/bin/remote-dev-base-verify \
    && remote-dev-base-verify

WORKDIR /workspace
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "--login"]
