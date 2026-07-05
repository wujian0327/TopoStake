#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
REPO_DIR=$(CDPATH= cd "$SCRIPT_DIR/.." && pwd)

LIGHTHOUSE_DIR="${LIGHTHOUSE_DIR:-$REPO_DIR/clients/lighthouse}"
LIGHTHOUSE_IMAGE="${LIGHTHOUSE_IMAGE:-topostake/lighthouse:dev}"
UPSTREAM_IMAGE="${UPSTREAM_IMAGE:-sigp/lighthouse:latest}"
LIGHTHOUSE_RUNTIME_IMAGE="${LIGHTHOUSE_RUNTIME_IMAGE:-ubuntu:24.04}"
LIGHTHOUSE_REPO="${LIGHTHOUSE_REPO:-https://github.com/sigp/lighthouse.git}"

usage() {
    cat <<'EOF'
Usage: scripts/lighthouse_image.sh <command>

Commands:
  info          Print Lighthouse checkout and image metadata.
  clone         Clone Lighthouse if LIGHTHOUSE_DIR does not exist.
  build         Build LIGHTHOUSE_IMAGE from LIGHTHOUSE_DIR using Lighthouse Dockerfile.
  build-simple  Build with a generated Dockerfile that does not require Docker BuildKit.
  package-local Package a locally compiled lighthouse binary into LIGHTHOUSE_IMAGE.
  tag-upstream  Tag UPSTREAM_IMAGE as LIGHTHOUSE_IMAGE for a fast zero-diff plumbing check.
  verify        Run `lighthouse --version` inside LIGHTHOUSE_IMAGE.

Environment:
  LIGHTHOUSE_DIR     Lighthouse checkout path, default ./clients/lighthouse.
  LIGHTHOUSE_IMAGE   Output image tag, default topostake/lighthouse:dev.
  UPSTREAM_IMAGE     Source image for tag-upstream, default sigp/lighthouse:latest.
  LIGHTHOUSE_RUNTIME_IMAGE
                     Runtime base image for package-local, default ubuntu:24.04.
  LIGHTHOUSE_REPO    Repo URL for clone, default https://github.com/sigp/lighthouse.git.
  LIGHTHOUSE_BINARY  Local lighthouse binary for package-local.
EOF
}

require_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        echo "docker is not installed or not on PATH" >&2
        exit 127
    fi
}

require_git() {
    if ! command -v git >/dev/null 2>&1; then
        echo "git is not installed or not on PATH" >&2
        exit 127
    fi
}

commit_hash() {
    if [ -d "$LIGHTHOUSE_DIR/.git" ]; then
        git -C "$LIGHTHOUSE_DIR" rev-parse --short HEAD
    else
        printf 'unknown'
    fi
}

cmd_info() {
    printf 'LIGHTHOUSE_DIR=%s\n' "$LIGHTHOUSE_DIR"
    printf 'LIGHTHOUSE_IMAGE=%s\n' "$LIGHTHOUSE_IMAGE"
    printf 'UPSTREAM_IMAGE=%s\n' "$UPSTREAM_IMAGE"
    printf 'LIGHTHOUSE_RUNTIME_IMAGE=%s\n' "$LIGHTHOUSE_RUNTIME_IMAGE"
    printf 'LIGHTHOUSE_COMMIT=%s\n' "$(commit_hash)"
    if [ -f "$LIGHTHOUSE_DIR/Dockerfile" ]; then
        printf 'DOCKERFILE=%s\n' "$LIGHTHOUSE_DIR/Dockerfile"
    else
        printf 'DOCKERFILE=missing\n'
    fi
}

cmd_clone() {
    require_git
    if [ -d "$LIGHTHOUSE_DIR/.git" ]; then
        echo "Lighthouse checkout already exists: $LIGHTHOUSE_DIR"
        cmd_info
        return
    fi
    git clone --depth 1 "$LIGHTHOUSE_REPO" "$LIGHTHOUSE_DIR"
    cmd_info
}

cmd_build() {
    require_docker
    if [ ! -f "$LIGHTHOUSE_DIR/Dockerfile" ]; then
        echo "missing Lighthouse Dockerfile at $LIGHTHOUSE_DIR/Dockerfile" >&2
        echo "run: LIGHTHOUSE_DIR=$LIGHTHOUSE_DIR scripts/lighthouse_image.sh clone" >&2
        exit 1
    fi
    cmd_info
    DOCKER_BUILDKIT=1 docker build -t "$LIGHTHOUSE_IMAGE" "$LIGHTHOUSE_DIR"
}

cmd_build_simple() {
    require_docker
    if [ ! -f "$LIGHTHOUSE_DIR/Dockerfile" ]; then
        echo "missing Lighthouse Dockerfile at $LIGHTHOUSE_DIR/Dockerfile" >&2
        echo "run: LIGHTHOUSE_DIR=$LIGHTHOUSE_DIR scripts/lighthouse_image.sh clone" >&2
        exit 1
    fi
    tmp_file=$(mktemp "${TMPDIR:-/tmp}/topostake-lighthouse-dockerfile.XXXXXX")
    cat > "$tmp_file" <<'EOF'
FROM rust:1.88.0-bullseye AS builder
RUN apt-get update && apt-get -y upgrade && apt-get install -y cmake libclang-dev
ARG FEATURES
ARG PROFILE=release
ARG CARGO_USE_GIT_CLI=true
ENV FEATURES=$FEATURES
ENV PROFILE=$PROFILE
ENV CARGO_NET_GIT_FETCH_WITH_CLI=$CARGO_USE_GIT_CLI
ENV CARGO_INCREMENTAL=1

WORKDIR /lighthouse
COPY . .
RUN make

FROM ubuntu:22.04
RUN apt-get update && apt-get -y upgrade && apt-get install -y --no-install-recommends \
  libssl-dev \
  ca-certificates \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local/cargo/bin/lighthouse /usr/local/bin/lighthouse
EOF
    cmd_info
    echo "SIMPLE_DOCKERFILE=$tmp_file"
    DOCKER_BUILDKIT=0 docker build -f "$tmp_file" -t "$LIGHTHOUSE_IMAGE" "$LIGHTHOUSE_DIR"
    rm -f "$tmp_file"
}

find_lighthouse_binary() {
    if [ "${LIGHTHOUSE_BINARY:-}" ]; then
        printf '%s\n' "$LIGHTHOUSE_BINARY"
        return
    fi
    if [ -x "$LIGHTHOUSE_DIR/target/release/lighthouse" ]; then
        printf '%s\n' "$LIGHTHOUSE_DIR/target/release/lighthouse"
        return
    fi
    if [ -x "$HOME/.cargo/bin/lighthouse" ]; then
        printf '%s\n' "$HOME/.cargo/bin/lighthouse"
        return
    fi
    echo "could not find a local lighthouse binary" >&2
    echo "set LIGHTHOUSE_BINARY=/path/to/lighthouse or build Lighthouse first" >&2
    exit 1
}

cmd_package_local() {
    require_docker
    binary_path=$(find_lighthouse_binary)
    if [ ! -x "$binary_path" ]; then
        echo "local lighthouse binary is not executable: $binary_path" >&2
        exit 1
    fi

    docker image inspect "$LIGHTHOUSE_RUNTIME_IMAGE" >/dev/null 2>&1 || docker pull "$LIGHTHOUSE_RUNTIME_IMAGE"
    tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/topostake-lighthouse-image.XXXXXX")
    cp "$binary_path" "$tmp_dir/lighthouse"
    printf 'FROM %s\n' "$LIGHTHOUSE_RUNTIME_IMAGE" > "$tmp_dir/Dockerfile"
    cat >> "$tmp_dir/Dockerfile" <<'EOF'
COPY lighthouse /usr/local/bin/lighthouse
EOF

    cmd_info
    printf 'LIGHTHOUSE_BINARY=%s\n' "$binary_path"
    DOCKER_BUILDKIT=0 docker build -t "$LIGHTHOUSE_IMAGE" "$tmp_dir"
    rm -rf "$tmp_dir"
}

cmd_tag_upstream() {
    require_docker
    docker image inspect "$UPSTREAM_IMAGE" >/dev/null 2>&1 || docker pull "$UPSTREAM_IMAGE"
    docker tag "$UPSTREAM_IMAGE" "$LIGHTHOUSE_IMAGE"
    cmd_info
}

cmd_verify() {
    require_docker
    docker run --rm "$LIGHTHOUSE_IMAGE" lighthouse --version
}

if [ "$#" -ne 1 ]; then
    usage
    exit 2
fi

case "$1" in
    info)
        cmd_info
        ;;
    clone)
        cmd_clone
        ;;
    build)
        cmd_build
        ;;
    build-simple)
        cmd_build_simple
        ;;
    package-local)
        cmd_package_local
        ;;
    tag-upstream)
        cmd_tag_upstream
        ;;
    verify)
        cmd_verify
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        usage
        exit 2
        ;;
esac
