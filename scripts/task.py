#!/usr/bin/env python3
"""Cross-platform task runner for common TopoStake workflows.

This mirrors the Makefile targets without requiring `make`, which is useful on
Windows. Commands are executed from the repository root and use the current
Python interpreter for Python scripts.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable

FIGURE_SCRIPTS = [
    "analysis/plot_performance.py",
    "analysis/plot_crypto_overhead.py",
    "analysis/plot_fairness.py",
    "analysis/plot_weight_bound.py",
    "analysis/plot_padding_flooding.py",
    "analysis/plot_churn.py",
]


def run(cmd: List[str], env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    printable = " ".join(cmd)
    print(f"$ {printable}", flush=True)
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(cmd, cwd=ROOT, env=merged_env, check=check)


def task_test(_args: argparse.Namespace) -> None:
    run(["cargo", "fmt", "--check"])
    run(["cargo", "check"])
    run(["cargo", "test"])


def task_run_experiments(config: str, force: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = [PYTHON, "experiments/run_experiments.py", "--config", config]
    if force:
        cmd.append("--force")
    return run(cmd, check=check)


def task_summarize_config(config: str) -> None:
    run([PYTHON, "experiments/summarize.py", "--config", config])


def task_figures(_args: argparse.Namespace) -> None:
    for script in FIGURE_SCRIPTS:
        run([PYTHON, script])


def task_experiments_smoke(args: argparse.Namespace) -> None:
    config = "experiments/configs/smoke.yaml"
    task_run_experiments(config, force=args.force)
    task_summarize_config(config)
    task_figures(args)


def task_experiments_main(args: argparse.Namespace) -> None:
    config = "experiments/configs/main.yaml"
    task_run_experiments(config, force=args.force)
    task_summarize_config(config)


def task_tdsc_fast(args: argparse.Namespace) -> None:
    config = "experiments/configs/tdsc_fast.yaml"
    completed = task_run_experiments(config, force=args.force, check=False)
    task_summarize_config(config)
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, completed.args)


def task_frozen_smoke(args: argparse.Namespace) -> None:
    config = "experiments/configs/frozen_v1_smoke.yaml"
    task_run_experiments(config, force=args.force)
    task_summarize_config(config)


def task_frozen_devnet_check(args: argparse.Namespace) -> None:
    cmd = [PYTHON, "experiments/frozen_devnet_acceptance.py"]
    if args.artifact:
        cmd.extend(["--artifact", args.artifact, "--mode", args.mode])
    run(cmd)


def task_frozen_devnet_smoke(args: argparse.Namespace) -> None:
    cmd = [
        PYTHON,
        "experiments/run_frozen_devnet_smoke.py",
        "--modes",
        args.modes,
    ]
    if args.package:
        cmd.extend(["--package", args.package])
    if args.skip_existing:
        cmd.append("--skip-existing")
    if args.keep_enclaves:
        cmd.append("--keep-enclaves")
    run(cmd)


def task_frozen_devnet_matrix(args: argparse.Namespace, config: str) -> None:
    cmd = [
        PYTHON,
        "experiments/run_frozen_devnet_experiments.py",
        "--config",
        config,
    ]
    if args.package:
        cmd.extend(["--package", args.package])
    for option in ("seeds", "variants", "nodes", "loads", "topologies"):
        value = getattr(args, option)
        if value:
            cmd.extend([f"--{option}", value])
    if args.resume:
        cmd.append("--resume")
    if args.keep_enclaves:
        cmd.append("--keep-enclaves")
    if args.stop_on_failure:
        cmd.append("--stop-on-failure")
    if args.dry_run:
        cmd.append("--dry-run")
    run(cmd)


def task_frozen_devnet_pilot(args: argparse.Namespace) -> None:
    task_frozen_devnet_matrix(args, "experiments/configs/frozen_v1_devnet_pilot.yaml")


def task_frozen_devnet_main(args: argparse.Namespace) -> None:
    task_frozen_devnet_matrix(args, "experiments/configs/frozen_v1_devnet_main.yaml")


def task_summarize(_args: argparse.Namespace) -> None:
    run([PYTHON, "experiments/summarize.py"])


TASKS: Dict[str, Callable[[argparse.Namespace], None]] = {
    "test": task_test,
    "experiments-smoke": task_experiments_smoke,
    "experiments-main": task_experiments_main,
    "tdsc-fast": task_tdsc_fast,
    "frozen-smoke": task_frozen_smoke,
    "frozen-devnet-check": task_frozen_devnet_check,
    "frozen-devnet-smoke": task_frozen_devnet_smoke,
    "frozen-devnet-pilot": task_frozen_devnet_pilot,
    "frozen-devnet-main": task_frozen_devnet_main,
    "summarize": task_summarize,
    "figures": task_figures,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=sorted(TASKS))
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rerun experiment tasks even when existing summaries are present.",
    )
    parser.add_argument("--artifact", help="Devnet summary.json for frozen-devnet-check.")
    parser.add_argument(
        "--mode",
        choices=["baseline", "pathobs", "fee_only", "bonus_only", "topostake"],
        default="topostake",
    )
    parser.add_argument("--modes", default="baseline,pathobs,topostake", help="Modes for frozen-devnet-smoke.")
    parser.add_argument("--package", help="Path to the local ethereum-package checkout.")
    parser.add_argument("--skip-existing", action="store_true", help="Reuse existing devnet summary artifacts.")
    parser.add_argument("--keep-enclaves", action="store_true", help="Leave smoke enclaves running after collection.")
    parser.add_argument("--seeds", help="Comma-separated seed override for formal devnet runs.")
    parser.add_argument("--variants", help="Comma-separated variant override for formal devnet runs.")
    parser.add_argument("--nodes", help="Comma-separated node-count override for formal devnet runs.")
    parser.add_argument("--loads", help="Comma-separated tx-per-slot override for formal devnet runs.")
    parser.add_argument("--topologies", help="Comma-separated topology override for formal devnet runs.")
    parser.add_argument("--resume", action="store_true", help="Skip completed formal devnet runs.")
    parser.add_argument("--stop-on-failure", action="store_true", help="Stop a formal matrix at its first failure.")
    parser.add_argument("--dry-run", action="store_true", help="Print the formal matrix without launching Kurtosis.")
    args = parser.parse_args()

    TASKS[args.target](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
