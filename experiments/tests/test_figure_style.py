from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = ROOT / "analysis"


class FigureStyleTests(unittest.TestCase):
    def test_paper_figures_do_not_draw_panel_titles(self) -> None:
        offenders: list[str] = []
        for path in sorted(ANALYSIS.glob("plot_*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr in {"set_title", "suptitle"}:
                    offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
