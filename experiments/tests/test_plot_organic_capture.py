import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analysis"))

from plot_organic_capture import (  # noqa: E402
    render_metric,
    render_paired_capture,
    render_score_to_proposer_gain,
)


class PlotOrganicCaptureTests(unittest.TestCase):
    def test_render_metric_writes_publication_formats(self) -> None:
        rows = []
        for mode in ("none", "max-score"):
            for placement in ("random", "high-degree"):
                for stake in (0.1, 0.2, 0.3):
                    mean = stake + (0.05 if mode == "max-score" else 0.0)
                    rows.append(
                        {
                            "series": f"{mode}:{placement}",
                            "adversary_stake_fraction": str(stake),
                            "metric": "capture",
                            "mean": str(mean),
                            "ci95_low": str(mean - 0.01),
                            "ci95_high": str(mean + 0.01),
                        }
                    )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "capture"
            render_metric(
                rows,
                "capture",
                "Capture share",
                "Organic capture",
                output,
                lambda stake: stake,
                "Stake share",
            )
            self.assertTrue(output.with_suffix(".pdf").exists())
            self.assertTrue(output.with_suffix(".svg").exists())
            self.assertTrue(output.with_suffix(".png").exists())

    def test_render_paired_figures(self) -> None:
        rows = []
        for placement in ("random", "high-degree"):
            for stake in (0.1, 0.2, 0.3):
                for metric, mean in (
                    ("adversary_organic_relay_reward_share", 0.03),
                    ("adversary_score_share", 0.05),
                    ("adversary_proposer_weight_share", 0.005),
                ):
                    rows.append(
                        {
                            "series": f"max-score-minus-none:{placement}",
                            "adversary_stake_fraction": str(stake),
                            "metric": metric,
                            "mean": str(mean),
                            "ci95_low": str(mean - 0.002),
                            "ci95_high": str(mean + 0.002),
                        }
                    )
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "capture"
            attenuation = Path(directory) / "attenuation"
            render_paired_capture(rows, capture)
            render_score_to_proposer_gain(rows, attenuation)
            for output in (capture, attenuation):
                for suffix in (".pdf", ".svg", ".png"):
                    self.assertTrue(output.with_suffix(suffix).exists())


if __name__ == "__main__":
    unittest.main()
