"""两条窑次记录的升温轨迹与累计计热对比（纯计算，不触碰持久化）。

约定与计热核心完全一致（复用 :mod:`app.heatwork` 的实现）：

* 相邻采样点之间温度**线性**变化，这是唯一的插值约定；
* 累计计热只累计温度**高于 600 °C** 的部分，跨越起点先求交点再切段；
* 两条曲线各自以**首个采样时刻**为经过 0 分钟对齐；
* 求值时间轴为两条曲线所有采样时刻（换算成经过分钟）的并集，
  限制在共同持续区间 ``[0, min(双方持续分钟数)]`` 内。

每个对齐节点输出温度差与累计计热差（当前记录 − 参照记录），
全程使用 Fraction 做精确有理数运算，仅对外输出时才转 float。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from typing import List, Optional, Sequence, Tuple, Union

from .heatwork import HEATWORK_BASE_C, _minutes, _segment_area_and_minutes

Number = Union[int, float]
TimedSample = Tuple[datetime, Number]


@dataclass(frozen=True)
class Curve:
    """以首个采样时刻为经过 0 分钟的温度折线及其累计计热。

    ``elapsed_minutes`` 严格递增且首项为 0；``heatwork_prefix[i]``
    为从经过 0 分钟到第 ``i`` 个采样点的累计计热（°C·min）。
    """

    elapsed_minutes: Tuple[Fraction, ...]
    temperatures: Tuple[Fraction, ...]
    heatwork_prefix: Tuple[Fraction, ...]

    @property
    def span_minutes(self) -> Fraction:
        """曲线总持续分钟数（单点曲线为 0）。"""
        return self.elapsed_minutes[-1]


def build_curve(points: Sequence[TimedSample]) -> Curve:
    """由 ``(时刻, 摄氏温度)`` 序列构建对齐曲线，时刻须已严格递增。"""
    if not points:
        raise ValueError("构建曲线至少需要 1 个采样点")
    first = points[0][0]
    elapsed = tuple(_minutes(moment - first) for moment, _ in points)
    temperatures = tuple(Fraction(temperature) for _, temperature in points)
    base = Fraction(HEATWORK_BASE_C)
    total = Fraction(0)
    prefix: List[Fraction] = [total]
    for index in range(len(elapsed) - 1):
        area, _ = _segment_area_and_minutes(
            elapsed[index + 1] - elapsed[index],
            temperatures[index] - base,
            temperatures[index + 1] - base,
        )
        total += area
        prefix.append(total)
    return Curve(
        elapsed_minutes=elapsed,
        temperatures=temperatures,
        heatwork_prefix=tuple(prefix),
    )


def _segment_index(curve: Curve, t: Fraction) -> int:
    """定位经过 ``t`` 分钟所在的采样段下标（右端点归入末段）。"""
    for index in range(len(curve.elapsed_minutes) - 1):
        if t < curve.elapsed_minutes[index + 1]:
            return index
    return len(curve.elapsed_minutes) - 2


def temperature_at(curve: Curve, t: Fraction) -> Fraction:
    """经过 ``t`` 分钟处的温度：段内线性插值（``t`` 须落在曲线区间内）。"""
    if len(curve.elapsed_minutes) == 1:
        return curve.temperatures[0]
    index = _segment_index(curve, t)
    t0 = curve.elapsed_minutes[index]
    t1 = curve.elapsed_minutes[index + 1]
    temp0 = curve.temperatures[index]
    temp1 = curve.temperatures[index + 1]
    return temp0 + (temp1 - temp0) * (t - t0) / (t1 - t0)


def heatwork_at(curve: Curve, t: Fraction) -> Fraction:
    """经过 ``t`` 分钟处的累计计热：前缀和 + 所在段的部分贡献。"""
    if t <= 0 or len(curve.elapsed_minutes) == 1:
        return Fraction(0)
    index = _segment_index(curve, t)
    t0 = curve.elapsed_minutes[index]
    base = Fraction(HEATWORK_BASE_C)
    area, _ = _segment_area_and_minutes(
        t - t0,
        curve.temperatures[index] - base,
        temperature_at(curve, t) - base,
    )
    return curve.heatwork_prefix[index] + area


@dataclass(frozen=True)
class CompareNode:
    """一个对齐节点上的两类差值（当前记录 − 参照记录）。"""

    elapsed_minutes: Fraction
    temperature_delta: Fraction
    heatwork_delta: Fraction


@dataclass(frozen=True)
class CurveComparison:
    """共同持续区间内的对齐节点序列。"""

    common_minutes: Fraction
    nodes: Tuple[CompareNode, ...]


def compare_curves(current: Curve, reference: Curve) -> Optional[CurveComparison]:
    """在共同持续区间的并集时间轴上求两条曲线的逐节点差值。

    共同区间为 ``[0, min(双方持续分钟数)]``；区间不为正（例如任一方
    只有单个采样点、持续时间为 0）时返回 ``None``。
    """
    common = min(current.span_minutes, reference.span_minutes)
    if common <= 0:
        return None
    timeline = sorted(
        {
            t
            for t in current.elapsed_minutes + reference.elapsed_minutes
            if t <= common
        }
    )
    nodes = tuple(
        CompareNode(
            elapsed_minutes=t,
            temperature_delta=temperature_at(current, t)
            - temperature_at(reference, t),
            heatwork_delta=heatwork_at(current, t) - heatwork_at(reference, t),
        )
        for t in timeline
    )
    return CurveComparison(common_minutes=common, nodes=nodes)
