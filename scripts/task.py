#!/usr/bin/env python3
"""Cross-platform task runner for common TopoStake workflows.

This mirrors the Makefile targets without requiring `make`, which is useful on
Windows. Commands are executed from the repository root and use the current
Python interpreter for Python scripts.
"""

from __future__ import annotations

import argparse
import json
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

PAPER_FIGURE_JOBS = [
    ("analysis/plot_performance.py", ("results/processed/runs.csv",)),
    ("analysis/plot_weight_bound.py", ("results/processed/runs.csv",)),
    (
        "analysis/plot_padding_flooding.py",
        (
            "results/processed/runs.csv",
            "results/processed/node_epoch_metrics_all.csv",
        ),
    ),
    "analysis/plot_path_padding_sim.py",
    "analysis/plot_flooding_sim.py",
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


def task_run_experiments(
    config: str,
    force: bool = False,
    check: bool = True,
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]:
    cmd = [PYTHON, "experiments/run_experiments.py", "--config", config]
    if force:
        cmd.append("--force")
    if dry_run:
        cmd.append("--dry-run")
    return run(cmd, check=check)


def task_summarize_config(config: str) -> None:
    run([PYTHON, "experiments/summarize.py", "--config", config])


def task_figures(_args: argparse.Namespace) -> None:
    for script in FIGURE_SCRIPTS:
        run([PYTHON, script])


def run_figure_if_ready(
    script: str,
    required_inputs: tuple[str, ...] = (),
    script_args: tuple[str, ...] = (),
) -> bool:
    missing = [path for path in required_inputs if not (ROOT / path).is_file()]
    if missing:
        print(
            f"skip: {script} (missing {', '.join(missing)})",
            flush=True,
        )
        return False
    run([PYTHON, script, *script_args])
    return True


def task_paper_figures(_args: argparse.Namespace) -> None:
    for job in PAPER_FIGURE_JOBS:
        if isinstance(job, str):
            run_figure_if_ready(job)
        else:
            script, required_inputs = job
            run_figure_if_ready(script, required_inputs)

    config = _args.config or "experiments/configs/frozen_v1_sustained_outage_main.yaml"
    spec = json.loads((ROOT / config).read_text(encoding="utf-8"))
    processed = Path("results/processed") / str(spec["suite"])
    required_inputs = (
        str(processed / "sustained_outage_runs.csv"),
        str(processed / "sustained_outage_paired.csv"),
        str(processed / "sustained_outage_epoch_paired.csv"),
    )
    run_figure_if_ready(
        "analysis/plot_sustained_outage.py",
        required_inputs,
        ("--config", config),
    )


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


def task_frozen_security(args: argparse.Namespace, config: str) -> None:
    task_run_experiments(config, force=args.force, dry_run=args.dry_run)
    if args.dry_run:
        return
    task_frozen_padding_check(args)
    cmd = [PYTHON, "experiments/frozen_security_report.py", "--config", config]
    if args.allow_incomplete:
        cmd.append("--allow-incomplete")
    run(cmd)


def task_frozen_security_pilot(args: argparse.Namespace) -> None:
    task_frozen_security(args, "experiments/configs/frozen_v1_security_pilot.yaml")


def task_frozen_security_main(args: argparse.Namespace) -> None:
    task_frozen_security(args, "experiments/configs/frozen_v1_security_main.yaml")


def task_frozen_security_report(args: argparse.Namespace) -> None:
    config = args.config or "experiments/configs/frozen_v1_security_main.yaml"
    task_frozen_padding_check(args)
    cmd = [PYTHON, "experiments/frozen_security_report.py", "--config", config]
    if args.allow_incomplete:
        cmd.append("--allow-incomplete")
    run(cmd)


def task_frozen_padding_check(_args: argparse.Namespace) -> None:
    run(["cargo", "run", "--release", "--bin", "frozen_padding_check"])


def task_frozen_evidence_bench(_args: argparse.Namespace) -> None:
    run(["cargo", "run", "--release", "--bin", "frozen_evidence_bench"])
    run([PYTHON, "analysis/plot_frozen_evidence.py"])


def task_frozen_security_figures(_args: argparse.Namespace) -> None:
    run([PYTHON, "analysis/plot_frozen_security.py"])


def task_fee_bonus(args: argparse.Namespace, config: str) -> None:
    task_run_experiments(config, force=args.force, dry_run=args.dry_run)
    if args.dry_run:
        return
    cmd = [PYTHON, "experiments/fee_bonus_long_horizon_report.py", "--config", config]
    if args.allow_incomplete:
        cmd.append("--allow-incomplete")
    run(cmd)
    run([PYTHON, "analysis/plot_fee_bonus_long_horizon.py", "--config", config])


def task_fee_bonus_pilot(args: argparse.Namespace) -> None:
    task_fee_bonus(args, "experiments/configs/frozen_v1_fee_bonus_pilot.yaml")


def task_fee_bonus_main(args: argparse.Namespace) -> None:
    task_fee_bonus(args, "experiments/configs/frozen_v1_fee_bonus_main.yaml")


def task_fee_bonus_report(args: argparse.Namespace) -> None:
    config = args.config or "experiments/configs/frozen_v1_fee_bonus_pilot.yaml"
    cmd = [PYTHON, "experiments/fee_bonus_long_horizon_report.py", "--config", config]
    if args.allow_incomplete:
        cmd.append("--allow-incomplete")
    run(cmd)


def task_fee_bonus_figures(args: argparse.Namespace) -> None:
    config = args.config or "experiments/configs/frozen_v1_fee_bonus_pilot.yaml"
    run([PYTHON, "analysis/plot_fee_bonus_long_horizon.py", "--config", config])


def task_organic_capture(args: argparse.Namespace, config: str) -> None:
    task_run_experiments(config, force=args.force, dry_run=args.dry_run)
    if args.dry_run:
        return
    cmd = [PYTHON, "experiments/organic_capture_report.py", "--config", config]
    if args.allow_incomplete:
        cmd.append("--allow-incomplete")
    run(cmd)
    run([PYTHON, "analysis/plot_organic_capture.py", "--config", config])


def task_organic_capture_pilot(args: argparse.Namespace) -> None:
    task_organic_capture(args, "experiments/configs/frozen_v1_organic_capture_pilot.yaml")


def task_organic_capture_main(args: argparse.Namespace) -> None:
    task_organic_capture(args, "experiments/configs/frozen_v1_organic_capture_main.yaml")


def task_organic_capture_report(args: argparse.Namespace) -> None:
    config = args.config or "experiments/configs/frozen_v1_organic_capture_pilot.yaml"
    cmd = [PYTHON, "experiments/organic_capture_report.py", "--config", config]
    if args.allow_incomplete:
        cmd.append("--allow-incomplete")
    run(cmd)


def task_organic_capture_figures(args: argparse.Namespace) -> None:
    config = args.config or "experiments/configs/frozen_v1_organic_capture_pilot.yaml"
    run([PYTHON, "analysis/plot_organic_capture.py", "--config", config])


def task_sustained_outage(args: argparse.Namespace, config: str) -> None:
    cmd = [PYTHON, "experiments/run_sustained_outage.py", "--config", config]
    if args.force:
        cmd.append("--force")
    if args.dry_run:
        cmd.append("--dry-run")
    run(cmd)
    if args.dry_run:
        return
    run([PYTHON, "experiments/sustained_outage_report.py", "--config", config])
    run([PYTHON, "analysis/plot_sustained_outage.py", "--config", config])


def task_sustained_outage_pilot(args: argparse.Namespace) -> None:
    task_sustained_outage(
        args, "experiments/configs/frozen_v1_sustained_outage_pilot.yaml"
    )


def task_sustained_outage_main(args: argparse.Namespace) -> None:
    task_sustained_outage(
        args, "experiments/configs/frozen_v1_sustained_outage_main.yaml"
    )


def task_sustained_outage_report(args: argparse.Namespace) -> None:
    config = args.config or "experiments/configs/frozen_v1_sustained_outage_main.yaml"
    run([PYTHON, "experiments/sustained_outage_report.py", "--config", config])


def task_sustained_outage_figures(args: argparse.Namespace) -> None:
    config = args.config or "experiments/configs/frozen_v1_sustained_outage_main.yaml"
    run([PYTHON, "analysis/plot_sustained_outage.py", "--config", config])


def task_frozen_devnet_figures(_args: argparse.Namespace) -> None:
    run([PYTHON, "experiments/reprocess_frozen_devnet_resources.py"])
    run([PYTHON, "analysis/plot_frozen_devnet.py"])


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
    "frozen-security-pilot": task_frozen_security_pilot,
    "frozen-security-main": task_frozen_security_main,
    "frozen-security-report": task_frozen_security_report,
    "frozen-security-figures": task_frozen_security_figures,
    "frozen-fee-bonus-pilot": task_fee_bonus_pilot,
    "frozen-fee-bonus-main": task_fee_bonus_main,
    "frozen-fee-bonus-report": task_fee_bonus_report,
    "frozen-fee-bonus-figures": task_fee_bonus_figures,
    "frozen-organic-capture-pilot": task_organic_capture_pilot,
    "frozen-organic-capture-main": task_organic_capture_main,
    "frozen-organic-capture-report": task_organic_capture_report,
    "frozen-organic-capture-figures": task_organic_capture_figures,
    "frozen-sustained-outage-pilot": task_sustained_outage_pilot,
    "frozen-sustained-outage-main": task_sustained_outage_main,
    "frozen-sustained-outage-report": task_sustained_outage_report,
    "frozen-sustained-outage-figures": task_sustained_outage_figures,
    "frozen-evidence-bench": task_frozen_evidence_bench,
    "frozen-padding-check": task_frozen_padding_check,
    "frozen-devnet-check": task_frozen_devnet_check,
    "frozen-devnet-figures": task_frozen_devnet_figures,
    "frozen-devnet-smoke": task_frozen_devnet_smoke,
    "frozen-devnet-pilot": task_frozen_devnet_pilot,
    "frozen-devnet-main": task_frozen_devnet_main,
    "summarize": task_summarize,
    "figures": task_figures,
    "paper-figures": task_paper_figures,
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
    parser.add_argument("--config", help="Config override for report or figure tasks.")
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Write a partial frozen-security report while a matrix is still running.",
    )
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
