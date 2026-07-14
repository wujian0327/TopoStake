import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analysis"))

from plot_organic_capture import render_metric  # noqa: E402


class PlotOrganicCaptureTests(unittest.TestCase):
    def test_render_metric_writes_pdf_and_png(self) -> None:
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
            self.assertTrue(output.with_suffix(".png").exists())


if __name__ == "__main__":
    unittest.main()
