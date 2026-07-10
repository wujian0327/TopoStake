#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PACKAGE="${KURTOSIS_PACKAGE:-github.com/ethpandaops/ethereum-package}"
DEFAULT_ENCLAVE="${DEFAULT_ENCLAVE:-topostake-devnet}"
CUSTOM_ENCLAVE="${CUSTOM_ENCLAVE:-topostake-devnet-custom}"
DEFAULT_ARGS="${DEFAULT_ARGS:-$ROOT_DIR/results/raw/topostake-devnet-4node-1validator-custom-geth-private.yaml}"
CUSTOM_ARGS="${CUSTOM_ARGS:-$ROOT_DIR/results/raw/topostake-devnet-4node-1validator-custom-geth-private.yaml}"
LIGHTHOUSE_IMAGE="${LIGHTHOUSE_IMAGE:-}"
DRY_RUN=0

usage() {
    cat <<'EOF'
Usage: scripts/kurtosis_devnet.sh [--dry-run] <command>

Commands:
  start-default   Start the current TopoStake custom geth+lighthouse devnet.
  start-custom    Start the current TopoStake custom geth+lighthouse devnet.
  status          Inspect default and custom enclaves if they exist.
  clean           Remove default and custom enclaves.

Environment:
  LIGHTHOUSE_IMAGE   Override cl_image for start-custom, e.g. topostake/lighthouse:dev.
  KURTOSIS_PACKAGE   Ethereum package path/ref, default github.com/ethpandaops/ethereum-package.
  DEFAULT_ENCLAVE    Default enclave name, default topostake-devnet.
  CUSTOM_ENCLAVE     Custom enclave name, default topostake-devnet-custom.
  CUSTOM_ARGS        Args file. Current default is results/raw/topostake-devnet-4node-1validator-custom-geth-private.yaml.
EOF
}

run_cmd() {
    printf '+'
    for arg in "$@"; do
        printf ' %s' "$arg"
    done
    printf '\n'
    if [ "$DRY_RUN" -eq 0 ]; then
        "$@"
    fi
}

require_kurtosis() {
    if ! command -v kurtosis >/dev/null 2>&1; then
        echo "kurtosis CLI is not installed or not on PATH" >&2
        exit 127
    fi
}

custom_args_file() {
    source_args="$1"
    dashboard_path=""
    dashboard_src="$ROOT_DIR/kurtosis/grafana-dashboards"

    if [ -d "$PACKAGE" ] && [ -d "$dashboard_src" ]; then
        dashboard_path="/topostake-grafana-dashboards"
        if [ "$DRY_RUN" -eq 0 ]; then
            mkdir -p "$PACKAGE$dashboard_path"
            cp "$dashboard_src"/*.json "$PACKAGE$dashboard_path"/
        fi
    fi

    if [ -z "$LIGHTHOUSE_IMAGE" ] && [ -z "$dashboard_path" ]; then
        printf '%s\n' "$source_args"
        return
    fi

    tmp_file=$(mktemp "${TMPDIR:-/tmp}/topostake-devnet-custom-lighthouse.XXXXXX.yaml")
    if [ -n "$LIGHTHOUSE_IMAGE" ]; then
        sed "s|^    cl_image: .*|    cl_image: $LIGHTHOUSE_IMAGE|" "$source_args" > "$tmp_file"
    else
        cp "$source_args" "$tmp_file"
    fi

    if [ -n "$dashboard_path" ]; then
        awk -v dashboard_path="$dashboard_path" '
            /^  additional_dashboards:/ {
                print "  additional_dashboards:"
                print "    - " dashboard_path
                skip_dashboard_items = 1
                next
            }
            skip_dashboard_items && /^    - / { next }
            skip_dashboard_items { skip_dashboard_items = 0 }
            { print }
        ' "$tmp_file" > "$tmp_file.next"
        mv "$tmp_file.next" "$tmp_file"
    fi

    printf '%s\n' "$tmp_file"
}

inspect_if_exists() {
    enclave="$1"
    if kurtosis enclave inspect "$enclave" >/tmp/kurtosis_devnet_inspect.$$ 2>/dev/null; then
        cat /tmp/kurtosis_devnet_inspect.$$
    else
        echo "Enclave '$enclave' is not running."
    fi
    rm -f /tmp/kurtosis_devnet_inspect.$$
}

if [ "$#" -eq 0 ]; then
    usage
    exit 2
fi

if [ "$1" = "--dry-run" ]; then
    DRY_RUN=1
    shift
fi

if [ "$#" -ne 1 ]; then
    usage
    exit 2
fi

command="$1"
require_kurtosis

case "$command" in
    start-default)
        run_cmd kurtosis run --enclave "$DEFAULT_ENCLAVE" "$PACKAGE" --args-file "$DEFAULT_ARGS"
        ;;
    start-custom)
        args_file=$(custom_args_file "$CUSTOM_ARGS")
        run_cmd kurtosis run --enclave "$CUSTOM_ENCLAVE" "$PACKAGE" --args-file "$args_file"
        if [ "$args_file" != "$CUSTOM_ARGS" ]; then
            rm -f "$args_file"
        fi
        ;;
    status)
        inspect_if_exists "$DEFAULT_ENCLAVE"
        inspect_if_exists "$CUSTOM_ENCLAVE"
        ;;
    clean)
        run_cmd kurtosis enclave rm -f "$DEFAULT_ENCLAVE" "$CUSTOM_ENCLAVE"
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        usage
        exit 2
        ;;
esac
