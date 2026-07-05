#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
REPO_DIR=$(CDPATH= cd "$SCRIPT_DIR/.." && pwd)

GETH_DIR="${GETH_DIR:-$REPO_DIR/clients/go-ethereum-topostake-prompt14}"
GETH_IMAGE="${GETH_IMAGE:-topostake/geth:dev}"
GETH_RUNTIME_IMAGE="${GETH_RUNTIME_IMAGE:-ubuntu:24.04}"
GETH_BINARY="${GETH_BINARY:-}"

usage() {
    cat <<'EOF'
Usage: scripts/geth_image.sh <command>

Commands:
  info           Print geth checkout and image metadata.
  package-local  Package a locally compiled geth binary into GETH_IMAGE.
  verify         Run `geth version` inside GETH_IMAGE.

Environment:
  GETH_DIR            go-ethereum checkout/worktree path, default ./clients/go-ethereum-topostake-prompt14.
  GETH_IMAGE          Output image tag, default topostake/geth:dev.
  GETH_RUNTIME_IMAGE  Runtime base image, default ubuntu:24.04.
  GETH_BINARY         Local geth binary path. Defaults to $GETH_DIR/geth.
EOF
}

require_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        echo "docker is not installed or not on PATH" >&2
        exit 127
    fi
}

commit_hash() {
    if [ -e "$GETH_DIR/.git" ]; then
        git -C "$GETH_DIR" rev-parse --short HEAD
    else
        printf 'unknown'
    fi
}

find_geth_binary() {
    if [ "$GETH_BINARY" ]; then
        printf '%s\n' "$GETH_BINARY"
        return
    fi
    if [ -x "$GETH_DIR/geth" ]; then
        printf '%s\n' "$GETH_DIR/geth"
        return
    fi
    if [ -x "$GETH_DIR/build/bin/geth" ]; then
        printf '%s\n' "$GETH_DIR/build/bin/geth"
        return
    fi
    echo "could not find a local geth binary" >&2
    echo "set GETH_BINARY=/path/to/geth or build geth first" >&2
    exit 1
}

cmd_info() {
    printf 'GETH_DIR=%s\n' "$GETH_DIR"
    printf 'GETH_IMAGE=%s\n' "$GETH_IMAGE"
    printf 'GETH_RUNTIME_IMAGE=%s\n' "$GETH_RUNTIME_IMAGE"
    printf 'GETH_COMMIT=%s\n' "$(commit_hash)"
    if [ -x "$(find_geth_binary 2>/dev/null || true)" ]; then
        printf 'GETH_BINARY=%s\n' "$(find_geth_binary)"
    else
        printf 'GETH_BINARY=missing\n'
    fi
}

cmd_package_local() {
    require_docker
    binary_path=$(find_geth_binary)
    if [ ! -x "$binary_path" ]; then
        echo "local geth binary is not executable: $binary_path" >&2
        exit 1
    fi

    docker image inspect "$GETH_RUNTIME_IMAGE" >/dev/null 2>&1 || docker pull "$GETH_RUNTIME_IMAGE"
    tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/topostake-geth-image.XXXXXX")
    cp "$binary_path" "$tmp_dir/geth"
    printf 'FROM %s\n' "$GETH_RUNTIME_IMAGE" > "$tmp_dir/Dockerfile"
    cat >> "$tmp_dir/Dockerfile" <<'EOF'
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
COPY geth /usr/local/bin/geth
ENTRYPOINT ["geth"]
EOF

    cmd_info
    printf 'GETH_BINARY=%s\n' "$binary_path"
    DOCKER_BUILDKIT=0 docker build -t "$GETH_IMAGE" "$tmp_dir"
    rm -rf "$tmp_dir"
}

cmd_verify() {
    require_docker
    docker run --rm "$GETH_IMAGE" version
}

if [ "$#" -ne 1 ]; then
    usage
    exit 2
fi

case "$1" in
    info)
        cmd_info
        ;;
    package-local)
        cmd_package_local
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
