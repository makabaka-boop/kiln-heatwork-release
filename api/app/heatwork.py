"""烧成计热（heatwork）积分核心。

约定（与窑炉控制器导出的采样数据配套）：

* 相邻两个采样点之间，温度随时间**线性**变化，这是唯一的插值约定；
* 只累计温度**高于** 600 °C 的部分，即对 max(T(t) - 600, 0) 关于时间积分；
* 当某段跨越 600 °C 时，先按线性关系求出交点，把段切成两段，
  仅对高于 600 °C 的那一段用梯形法（退化为三角形）求面积；
* 积分结果单位为 °C·min，最终按四舍五入（half-up）保留一位小数。

示例（README 中有同样的演算）：

    两点 (00:00, 500 °C) 与 (01:00, 700 °C)，间隔 60 min。
    温度从 500 线性升到 700，在 30 min 处越过 600 °C。
    只有后 30 min 高于 600 °C，超出量从 0 线性升到 100 °C，
    面积 = 1/2 * 30 min * 100 °C = 1500.0 °C·min。

实现上全程使用 Fraction 做精确有理数运算，避免浮点误差影响
四舍五入的边界判定；只有最终对外输出时才转成 float / Decimal。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction
from typing import List, Sequence, Tuple, Union

#: 计热起点：只累计高于该温度的部分
HEATWORK_BASE_C = 600

#: 判定阈值（°C·min），作用于四舍五入后的一位小数值
UNDERFIRED_LIMIT = Decimal("18000.0")
OVERFIRED_LIMIT = Decimal("24000.0")

VERDICT_UNDERFIRED = "underfired"
VERDICT_QUALIFIED = "qualified"
VERDICT_OVERFIRED = "overfired"

VERDICT_LABELS = {
    VERDICT_UNDERFIRED: "欠烧",
    VERDICT_QUALIFIED: "合格",
    VERDICT_OVERFIRED: "过烧",
}

Number = Union[int, float]
SamplePoint = Tuple[datetime, Number]


@dataclass(frozen=True)
class SegmentContribution:
    """单个相邻采样段的计热贡献明细（精确有理数）。

    ``heating_minutes`` 为段内温度高于计热起点的有效计热分钟数；
    ``contribution`` 为该段对 max(T-600, 0) 积分的未舍入贡献（°C·min）。
    """

    index: int
    start: datetime
    end: datetime
    heating_minutes: Fraction
    contribution: Fraction


def _minutes(delta: timedelta) -> Fraction:
    """把 timedelta 精确转换为分钟（有理数）。"""
    microseconds = (
        delta.days * 86_400_000_000
        + delta.seconds * 1_000_000
        + delta.microseconds
    )
    return Fraction(microseconds, 60_000_000)


def _segment_area_and_minutes(
    dt_min: Fraction, excess0: Fraction, excess1: Fraction
) -> Tuple[Fraction, Fraction]:
    """单段的精确积分与有效计热分钟数。

    ``dt_min`` 为段长（分钟），``excess0``/``excess1`` 为两端点
    温度减去 600 °C 的超出量（可为负）。段内温度线性变化。
    返回 ``(面积贡献, 高于计热起点的分钟数)``。
    """
    if excess0 <= 0 and excess1 <= 0:
        # 整段不高于 600 °C，不累计
        return Fraction(0), Fraction(0)
    if excess0 > 0 and excess1 > 0:
        # 整段高于 600 °C，梯形面积，整段计热
        return (excess0 + excess1) * dt_min / 2, dt_min
    # 段内跨越 600 °C：先线性求交点位置 s* ∈ (0, 1)，再切段
    # T(s) = T0 + (T1 - T0) * s = 600  =>  s* = excess0 / (excess0 - excess1)
    s_star = excess0 / (excess0 - excess1)
    if excess0 > 0:
        # 从高于 600 °C 降到交点：三角形面积，前 s* 段计热
        return excess0 * (s_star * dt_min) / 2, s_star * dt_min
    # 从交点升到高于 600 °C：三角形面积，后 1-s* 段计热
    return excess1 * ((1 - s_star) * dt_min) / 2, (1 - s_star) * dt_min


def _segment_area(dt_min: Fraction, excess0: Fraction, excess1: Fraction) -> Fraction:
    """单段对 max(T-600, 0) 的精确积分。"""
    area, _ = _segment_area_and_minutes(dt_min, excess0, excess1)
    return area


def compute_segment_contributions(
    points: Sequence[SamplePoint],
) -> List[SegmentContribution]:
    """逐相邻采样段计算计热贡献明细，按时间顺序返回。

    ``points`` 为 ``(时刻, 摄氏温度)`` 序列，时刻须已按递增排列。
    各段贡献之和与 :func:`compute_heatwork` 完全一致（同为精确有理数）；
    低于计热起点的段保留在结果中，贡献与计热分钟数均为 0。
    """
    base = Fraction(HEATWORK_BASE_C)
    segments: List[SegmentContribution] = []
    for index, ((t0, temp0), (t1, temp1)) in enumerate(zip(points, points[1:])):
        dt_min = _minutes(t1 - t0)
        area, heating = _segment_area_and_minutes(
            dt_min, Fraction(temp0) - base, Fraction(temp1) - base
        )
        segments.append(
            SegmentContribution(
                index=index,
                start=t0,
                end=t1,
                heating_minutes=heating,
                contribution=area,
            )
        )
    return segments


def compute_heatwork(points: Sequence[SamplePoint]) -> Fraction:
    """计算一批采样点的烧成计热值，返回精确的 °C·min（Fraction）。

    ``points`` 为 ``(时刻, 摄氏温度)`` 序列，时刻须已按递增排列。
    总积分即各相邻段贡献之和，与分段明细天然一致。
    """
    return sum(
        (segment.contribution for segment in compute_segment_contributions(points)),
        Fraction(0),
    )


def round_half_up_1(value: Fraction) -> Decimal:
    """把精确的积分值按四舍五入（half-up）保留一位小数。"""
    with localcontext() as ctx:
        ctx.prec = 60
        decimal_value = Decimal(value.numerator) / Decimal(value.denominator)
        return decimal_value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def classify(display_value: Decimal) -> str:
    """按保留一位小数后的展示值判定：欠烧 / 合格 / 过烧。"""
    if display_value < UNDERFIRED_LIMIT:
        return VERDICT_UNDERFIRED
    if display_value <= OVERFIRED_LIMIT:
        return VERDICT_QUALIFIED
    return VERDICT_OVERFIRED
