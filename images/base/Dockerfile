# syntax=docker/dockerfile:1.25.0@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
ARG UBUNTU_VERSION=26.04
ARG UBUNTU_DIGEST=sha256:3131b4cc82a783df6c9df078f86e01819a13594b865c2cad47bd1bca2b7063bb
FROM ubuntu:${UBUNTU_VERSION}@${UBUNTU_DIGEST}

# Re-declare the pre-FROM arguments so they are available inside this build stage.
ARG UBUNTU_VERSION
ARG UBUNTU_DIGEST
ARG TARGETARCH
ARG BASE_VERSION=0.1.0-dev
ARG GH_VERSION=2.97.0
ARG GH_AMD64_SHA256=a2c9b8497e1f85b1ad0dfcb78b5a622e098801b8e461e459e88e1ee12f018112
ARG GH_ARM64_SHA256=73ea440ecad9c9e284429997ee6f93577bc6f7bc6fba357ef62c53ad8fb641a5
ARG TTYD_VERSION=1.7.7
ARG TTYD_AMD64_SHA256=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55
ARG TTYD_ARM64_SHA256=b38acadd89d1d396a0f5649aa52c539edbad07f4bc7348b27b4f4b7219dd4165
ARG MISE_VERSION=2026.7.18
ARG MISE_AMD64_SHA256=e1fc2899f2bc7dfe9a3553f4c2d5944cf69d11b5f561545504a20f1e11cd6cc5
ARG MISE_ARM64_SHA256=7d96bad004ba706d7ce4e999113f61296ff317ad23754471743be883817e8a75
ARG PYTHON_VERSION=3.14.6
ARG NODE_VERSION=24.18.1
ARG NPM_VERSION=12.0.2
ARG UV_VERSION=0.12.0

LABEL org.opencontainers.image.title="Remote Dev Base" \
      org.opencontainers.image.description="Community remote development base for browser-hosted coding agents" \
      org.opencontainers.image.version="${BASE_VERSION}" \
      org.opencontainers.image.base.name="docker.io/library/ubuntu:${UBUNTU_VERSION}@${UBUNTU_DIGEST}" \
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
    MISE_GLOBAL_CONFIG_FILE=/etc/mise/mise.toml \
    PATH=/opt/remote-dev/mise/shims:/opt/remote-dev/mise/bin:/root/.local/bin:${PATH} \
    GH_CONFIG_DIR=/root/.config/gh \
    GH_HOST=github.com \
    GH_PAGER=cat \
    GH_NO_UPDATE_NOTIFIER=1 \
    GH_NO_EXTENSION_UPDATE_NOTIFIER=1 \
    DO_NOT_TRACK=1

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# APT repositories are moving inputs even when the Ubuntu image digest is pinned.
# Final images follow current Ubuntu security revisions, then pass smoke tests and
# vulnerability scans before public tags are promoted.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
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

# GitHub CLI: exact release asset verified against a repository-controlled SHA-256.
RUN case "${TARGETARCH}" in \
      amd64) gh_arch=amd64; expected_sha="$GH_AMD64_SHA256" ;; \
      arm64) gh_arch=arm64; expected_sha="$GH_ARM64_SHA256" ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && workdir="$(mktemp -d)" \
    && cd "$workdir" \
    && archive="gh_${GH_VERSION}_linux_${gh_arch}.tar.gz" \
    && curl --fail --silent --show-error --location --retry 3 --retry-all-errors --connect-timeout 10 --max-time 300 \
      "https://github.com/cli/cli/releases/download/v${GH_VERSION}/${archive}" -o "$archive" \
    && printf '%s  %s\n' "$expected_sha" "$archive" | sha256sum -c - \
    && tar -xzf "$archive" \
    && install -m 0755 "gh_${GH_VERSION}_linux_${gh_arch}/bin/gh" /usr/local/bin/gh \
    && cd / \
    && rm -rf "$workdir"

# ttyd: exact release asset verified against a repository-controlled SHA-256.
RUN case "${TARGETARCH}" in \
      amd64) ttyd_arch=x86_64; expected_sha="$TTYD_AMD64_SHA256" ;; \
      arm64) ttyd_arch=aarch64; expected_sha="$TTYD_ARM64_SHA256" ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && workdir="$(mktemp -d)" \
    && cd "$workdir" \
    && asset="ttyd.${ttyd_arch}" \
    && curl --fail --silent --show-error --location --retry 3 --retry-all-errors --connect-timeout 10 --max-time 300 \
      "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/${asset}" -o "$asset" \
    && printf '%s  %s\n' "$expected_sha" "$asset" | sha256sum -c - \
    && install -m 0755 "$asset" /usr/local/bin/ttyd \
    && cd / \
    && rm -rf "$workdir"

# mise: exact release asset verified against a repository-controlled SHA-256.
RUN case "${TARGETARCH}" in \
      amd64) mise_arch=x64; expected_sha="$MISE_AMD64_SHA256" ;; \
      arm64) mise_arch=arm64; expected_sha="$MISE_ARM64_SHA256" ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && workdir="$(mktemp -d)" \
    && cd "$workdir" \
    && asset="mise-v${MISE_VERSION}-linux-${mise_arch}" \
    && curl --fail --silent --show-error --location --retry 3 --retry-all-errors --connect-timeout 10 --max-time 300 \
      "https://github.com/jdx/mise/releases/download/v${MISE_VERSION}/${asset}" -o mise \
    && printf '%s  %s\n' "$expected_sha" mise | sha256sum -c - \
    && install -m 0755 mise /usr/local/bin/mise \
    && cd / \
    && rm -rf "$workdir"

# Runtime config and resolved artifacts are immutable build inputs. Strict locked
# installation refuses missing URLs and verifies every committed checksum.
COPY --chmod=0444 mise.toml mise.lock /etc/mise/

# One current runtime per language. Other runtimes are deliberately not bundled.
RUN mkdir -p "$MISE_DATA_DIR" "$MISE_CACHE_DIR" "$MISE_CONFIG_DIR" \
    && mise install --locked \
    && npm install --global --ignore-scripts --no-audit --no-fund "npm@${NPM_VERSION}" \
    && python --version \
    && node --version \
    && test "$(npm --version)" = "$NPM_VERSION" \
    && uv --version \
    && rm -rf "${MISE_CACHE_DIR:?}"/*

COPY config/tmux.conf /etc/tmux.conf
COPY scripts/base-verify.sh /usr/local/bin/remote-dev-base-verify
RUN chmod 0644 /etc/tmux.conf \
    && chmod 0755 /usr/local/bin/remote-dev-base-verify \
    && remote-dev-base-verify

WORKDIR /workspace
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "--login"]
