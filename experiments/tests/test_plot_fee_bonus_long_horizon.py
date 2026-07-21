from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analysis"))

from plot_fee_bonus_long_horizon import (  # noqa: E402
    render_metric,
    render_paired_difference,
    render_paired_premium_comparison,
)


class FeeBonusLongHorizonPlotTests(unittest.TestCase):
    def grouped_rows(self) -> list[dict[str, str]]:
        rows = []
        for fraction in (0.25, 0.5, 0.75):
            for series, offset in (("topostake_eta0", 0.0), ("topostake", 0.1)):
                rows.append(
                    {
                        "series": series,
                        "lazy_fraction": str(fraction),
                        "metric": "participation_reward_premium_per_stake",
                        "n": "20",
                        "mean": str(1.0 - fraction + offset),
                        "ci95": "0.05",
                    }
                )
            rows.append(
                {
                    "series": "full-minus-fee-only",
                    "lazy_fraction": str(fraction),
                    "metric": "participation_reward_premium_per_stake",
                    "n": "20",
                    "mean": "0.1",
                    "ci95": "0.03",
                }
            )
            rows.append(
                {
                    "series": "full-minus-fee-only",
                    "lazy_fraction": str(fraction),
                    "metric": "participation_weight_multiplier_premium",
                    "n": "20",
                    "mean": "0.07",
                    "ci95": "0.01",
                }
            )
        return rows

    def test_participation_panels_are_independent_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            rows = self.grouped_rows()
            render_metric(
                rows,
                "participation_reward_premium_per_stake",
                "premium",
                "participation",
                output / "absolute",
                0.01,
            )
            render_paired_difference(
                rows,
                "participation_reward_premium_per_stake",
                "difference",
                "incremental",
                output / "paired",
            )
            self.assertTrue((output / "absolute.pdf").exists())
            self.assertTrue((output / "absolute.png").exists())
            self.assertTrue((output / "paired.pdf").exists())
            self.assertTrue((output / "paired.png").exists())

    def test_paired_premium_comparison_is_independent_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "paired_premiums"
            render_paired_premium_comparison(self.grouped_rows(), output)
            self.assertTrue(output.with_suffix(".pdf").exists())
            self.assertTrue(output.with_suffix(".png").exists())


if __name__ == "__main__":
    unittest.main()
