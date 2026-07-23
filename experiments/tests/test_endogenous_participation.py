from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path


EXPERIMENTS = Path(__file__).resolve().parents[1]
if str(EXPERIMENTS) not in sys.path:
    sys.path.insert(0, str(EXPERIMENTS))

from endogenous_participation_report import (  # noqa: E402
    benefit_curve,
    geometric_mean,
    interpolate_curve,
    iterate_response,
    logarithmic_grid,
    prepare_index,
    solve_fixed_point,
)


class EndogenousParticipationTests(unittest.TestCase):
    def test_benefit_curve_uses_ratio_of_sums(self) -> None:
        rows = []
        for seed, reward, work in ((0, 1.0, 2.0), (1, 9.0, 18.0)):
            for metric, fee, full in (
                ("reward", reward, 3.0 * reward),
                ("work", work, work),
            ):
                rows.append(
                    {
                        "seed_index": str(seed),
                        "lazy_fraction": "0.5",
                        "metric": metric,
                        "fee_only_value": str(fee),
                        "full_value": str(full),
                    }
                )
        index, seeds, duplicates = prepare_index(rows)
        self.assertEqual(duplicates, 0)
        self.assertEqual(
            benefit_curve(index, seeds, [0.5], "reward", "work", "fee_only"),
            [0.5],
        )
        self.assertEqual(
            benefit_curve(index, seeds, [0.5], "reward", "work", "full"),
            [1.5],
        )

    def test_interpolation_modes_make_endpoint_assumption_explicit(self) -> None:
        xs = [0.25, 0.50, 0.75]
        ys = [1.0, 2.0, 4.0]
        self.assertAlmostEqual(interpolate_curve(0.375, xs, ys, "linear"), 1.5)
        self.assertAlmostEqual(interpolate_curve(0.0, xs, ys, "linear"), 0.0)
        self.assertAlmostEqual(interpolate_curve(0.0, xs, ys, "clamp"), 1.0)
        self.assertAlmostEqual(interpolate_curve(1.0, xs, ys, "linear"), 6.0)
        self.assertAlmostEqual(interpolate_curve(1.0, xs, ys, "clamp"), 4.0)

    def test_constant_benefit_has_closed_form_half_fixed_point(self) -> None:
        fixed = solve_fixed_point(
            [0.25, 0.75],
            [1.0, 1.0],
            cost_median=1.0,
            log_sigma=0.75,
            interpolation_mode="clamp",
        )
        self.assertAlmostEqual(fixed, 0.5)

    def test_larger_full_benefit_produces_larger_active_fraction(self) -> None:
        fractions = [0.25, 0.50, 0.75]
        fee = [1.0, 1.2, 1.5]
        full = [3.0, 3.6, 4.5]
        fee_fixed = solve_fixed_point(fractions, fee, 1.5, 0.75, "linear")
        full_fixed = solve_fixed_point(fractions, full, 1.5, 0.75, "linear")
        self.assertGreater(full_fixed - fee_fixed, 0.10)

    def test_damped_response_converges_from_distinct_initial_states(self) -> None:
        terminals = []
        for initial in (0.25, 0.50, 0.75):
            terminal, _steps, converged = iterate_response(
                initial,
                [0.25, 0.50, 0.75],
                [1.0, 1.2, 1.5],
                1.5,
                0.75,
                "linear",
                0.25,
                500,
                1e-10,
            )
            self.assertTrue(converged)
            terminals.append(terminal)
        self.assertLess(max(terminals) - min(terminals), 1e-8)

    def test_logarithmic_grid_includes_bounds(self) -> None:
        values = logarithmic_grid(0.25, 8.0, 6)
        self.assertTrue(math.isclose(values[0], 0.25))
        self.assertTrue(math.isclose(values[-1], 8.0))
        self.assertTrue(all(left < right for left, right in zip(values, values[1:])))

    def test_cost_reference_is_scale_consistent(self) -> None:
        self.assertAlmostEqual(geometric_mean([1.0, 4.0, 16.0]), 4.0)


if __name__ == "__main__":
    unittest.main()
