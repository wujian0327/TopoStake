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


def task_bench(_args: argparse.Namespace) -> None:
    run(
        ["cargo", "bench", "--bench", "bls_path", "--", "--quiet"],
        env={"CRITERION_QUICK": "1"},
    )


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


def task_summarize(_args: argparse.Namespace) -> None:
    run([PYTHON, "experiments/summarize.py"])


TASKS: Dict[str, Callable[[argparse.Namespace], None]] = {
    "test": task_test,
    "bench": task_bench,
    "experiments-smoke": task_experiments_smoke,
    "experiments-main": task_experiments_main,
    "tdsc-fast": task_tdsc_fast,
    "frozen-smoke": task_frozen_smoke,
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
    args = parser.parse_args()

    TASKS[args.target](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
