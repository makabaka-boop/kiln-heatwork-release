"""积分核心测试：跨 600°C 切段、梯形法、half-up 舍入与判定边界。"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction

from app.heatwork import (
    classify,
    compute_heatwork,
    compute_segment_contributions,
    round_half_up_1,
)

T0 = datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc)


def at(minutes=0, seconds=0, microseconds=0):
    return T0 + timedelta(minutes=minutes, seconds=seconds, microseconds=microseconds)


class TestSegmentIntegration:
    def test_all_below_base_contributes_zero(self):
        points = [(at(minutes=0), 500.0), (at(minutes=120), 550.0)]
        assert compute_heatwork(points) == 0

    def test_constant_above_base_is_rectangle(self):
        # 660°C 恒定 300 min：(660-600) * 300 = 18000 °C·min
        points = [(at(minutes=0), 660.0), (at(minutes=300), 660.0)]
        assert compute_heatwork(points) == Fraction(18000)

    def test_crossing_up_splits_at_linear_intersection(self):
        # 500 -> 700 用 60 min，30 min 处越过 600°C，
        # 后 30 min 超出量 0 -> 100，三角形面积 = 1500
        points = [(at(minutes=0), 500.0), (at(minutes=60), 700.0)]
        assert compute_heatwork(points) == Fraction(1500)

    def test_crossing_down_splits_at_linear_intersection(self):
        points = [(at(minutes=0), 700.0), (at(minutes=60), 500.0)]
        assert compute_heatwork(points) == Fraction(1500)

    def test_zigzag_across_base_accumulates_each_excursion(self):
        # 700 -> 500 -> 700，各 60 min，两次穿越各贡献 1500
        points = [
            (at(minutes=0), 700.0),
            (at(minutes=60), 500.0),
            (at(minutes=120), 700.0),
        ]
        assert compute_heatwork(points) == Fraction(3000)

    def test_endpoint_exactly_at_base(self):
        # 600 -> 800 用 60 min：梯形 (0+200)/2*60 = 6000
        points = [(at(minutes=0), 600.0), (at(minutes=60), 800.0)]
        assert compute_heatwork(points) == Fraction(6000)

    def test_touching_base_from_above_keeps_both_triangles(self):
        # 700 -> 600 -> 700：两个三角形，各 100*60/2 = 3000
        points = [
            (at(minutes=0), 700.0),
            (at(minutes=60), 600.0),
            (at(minutes=120), 700.0),
        ]
        assert compute_heatwork(points) == Fraction(6000)

    def test_sub_minute_resolution_is_exact(self):
        # 30 秒 = 0.5 min，600 -> 700：三角形 100 * 0.5 / 2 = 25
        points = [(at(), 600.0), (at(seconds=30), 700.0)]
        assert compute_heatwork(points) == Fraction(25)

    def test_fractional_temperature_uses_exact_rational_math(self):
        # 650.5°C 恒定 90 min：50.5 * 90 = 4545 °C·min
        points = [(at(minutes=0), 650.5), (at(minutes=90), 650.5)]
        assert compute_heatwork(points) == Fraction(4545)


class TestSegmentContributions:
    """逐相邻段贡献明细：分钟数、贡献值与总积分的一致性。"""

    def test_crossing_up_splits_heating_minutes(self):
        # 500 -> 700 用 60 min，30 min 处越过 600°C：仅后 30 min 计热
        points = [(at(minutes=0), 500.0), (at(minutes=60), 700.0)]
        (seg,) = compute_segment_contributions(points)
        assert seg.index == 0
        assert seg.start == at(minutes=0) and seg.end == at(minutes=60)
        assert seg.heating_minutes == Fraction(30)
        assert seg.contribution == Fraction(1500)

    def test_crossing_down_splits_heating_minutes(self):
        points = [(at(minutes=0), 700.0), (at(minutes=60), 500.0)]
        (seg,) = compute_segment_contributions(points)
        assert seg.heating_minutes == Fraction(30)
        assert seg.contribution == Fraction(1500)

    def test_all_below_base_keeps_zero_contribution_segment(self):
        # 全程低于起点：段保留，分钟数与贡献均为 0
        points = [(at(minutes=0), 500.0), (at(minutes=120), 550.0)]
        (seg,) = compute_segment_contributions(points)
        assert seg.heating_minutes == 0
        assert seg.contribution == 0

    def test_fully_above_base_counts_whole_segment(self):
        points = [(at(minutes=0), 660.0), (at(minutes=300), 660.0)]
        (seg,) = compute_segment_contributions(points)
        assert seg.heating_minutes == Fraction(300)
        assert seg.contribution == Fraction(18000)

    def test_multi_segment_curve_matches_readme(self):
        # README 示例曲线：6000 / 12000 / 3000，合计 21000
        points = [
            (at(minutes=0), 600.0),
            (at(minutes=120), 700.0),
            (at(minutes=240), 700.0),
            (at(minutes=300), 600.0),
        ]
        segments = compute_segment_contributions(points)
        assert [s.index for s in segments] == [0, 1, 2]
        assert [s.heating_minutes for s in segments] == [120, 120, 60]
        assert [s.contribution for s in segments] == [6000, 12000, 3000]

    def test_segment_sum_equals_total_integral(self):
        # 各段贡献之和与总积分在精确有理数层面一致
        points = [
            (at(minutes=0), 550.0),
            (at(minutes=45), 705.5),
            (at(minutes=90), 598.0),
            (at(minutes=200), 800.0),
            (at(minutes=260), 500.0),
        ]
        segments = compute_segment_contributions(points)
        assert sum((s.contribution for s in segments), Fraction(0)) == (
            compute_heatwork(points)
        )

    def test_single_point_yields_no_segments(self):
        assert compute_segment_contributions([(at(minutes=0), 700.0)]) == []


class TestRounding:
    def test_half_up_rounds_midpoint_up(self):
        assert round_half_up_1(Fraction(150005, 100)) == Decimal("1500.1")

    def test_half_up_keeps_below_midpoint(self):
        assert round_half_up_1(Fraction(150004, 100)) == Decimal("1500.0")

    def test_verdict_threshold_edge_rounds_into_qualified(self):
        # 17999.95 half-up 保留一位 -> 18000.0，落入合格区间
        assert round_half_up_1(Fraction(1799995, 100)) == Decimal("18000.0")

    def test_exact_value_unchanged(self):
        assert round_half_up_1(Fraction(18000)) == Decimal("18000.0")


class TestClassify:
    def test_boundaries(self):
        assert classify(Decimal("17999.9")) == "underfired"
        assert classify(Decimal("18000.0")) == "qualified"
        assert classify(Decimal("24000.0")) == "qualified"
        assert classify(Decimal("24000.1")) == "overfired"
