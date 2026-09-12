"""热电偶校准核验：逐点示值误差与合格判定。

现场更换或年检热电偶后，质检员填写探头编号、校准时间、允许偏差与
三至十二组（设定温度、仪表读数、标准器读数），本模块负责校验与判定：

* 每组示值误差 = 仪表读数 − 标准器读数；
* 最大绝对误差 = 各组 |示值误差| 的最大值；
* 最大绝对误差 ≤ 允许偏差判合格，否则不合格（边界恰等算合格）。

全程用 ``Fraction`` 按十进制输入的字面值做精确有理数运算，
避免浮点误差影响「恰等于允许偏差」的边界判定，最后才转 float 出参。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from fractions import Fraction
from typing import Any, List, Optional, Tuple

from .validation import FieldError, parse_iso8601

MIN_GROUPS = 3
MAX_GROUPS = 12
MIN_READING_C = 0
MAX_READING_C = 1400
MAX_PROBE_LENGTH = 80

CALIBRATION_PASS = "qualified"
CALIBRATION_FAIL = "unqualified"
CALIBRATION_LABELS = {
    CALIBRATION_PASS: "合格",
    CALIBRATION_FAIL: "不合格",
}


@dataclass
class CalibrationGroup:
    """校验通过的一组校准读数，同时保留精确有理数形态。"""

    set_temperature: float
    indicator_reading: float
    standard_reading: float
    set_fraction: Fraction
    indicator_fraction: Fraction
    standard_fraction: Fraction

    @property
    def indication_error(self) -> Fraction:
        """示值误差 = 仪表读数 − 标准器读数。"""
        return self.indicator_fraction - self.standard_fraction


@dataclass
class NormalizedCalibration:
    probe_id: str
    calibrated_at_raw: str
    calibrated_at_utc: Any  # datetime，归一化为 UTC，用作重复判定键
    tolerance: float
    tolerance_fraction: Fraction
    groups: List[CalibrationGroup]


def _reading_error(field: str, value: Any) -> Optional[str]:
    """单个温度读数（设定温度/仪表读数/标准器读数）的范围校验。"""
    # bool 是 int 的子类，必须显式排除
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "温度读数必须为数字（摄氏）"
    if value != value:  # NaN
        return "温度读数不能为 NaN"
    if not (MIN_READING_C <= value <= MAX_READING_C):
        return (
            f"温度读数须在 {MIN_READING_C} 至 {MAX_READING_C}°C 之间，收到 {value}"
        )
    return None


def _fraction(value: Any) -> Fraction:
    """按十进制字面值构造精确有理数。

    JSON 数字进入 Python 后已是 float，``str(float)`` 给出最短的十进制
    表示（如 0.1 -> '0.1'），据此构造的 Fraction 与质检员写下的小数
    严格一致，保证「恰等于允许偏差」的判定不受二进制浮点影响。
    """
    return Fraction(str(value))


def validate_calibration(
    payload: Any,
) -> Tuple[Optional[NormalizedCalibration], List[FieldError]]:
    """校验整张核验单。返回 (规范化数据, 错误列表)；有错时数据为 None。

    与窑次提交一致：手工逐层校验并**收集全部错误**，每条错误带
    ``index``（组下标，从 0 开始；与具体组无关时为 None）与 ``field``，
    前端据此定位到对应输入框。只要存在任一错误即整体失败，不得落库。
    """
    errors: List[FieldError] = []
    if not isinstance(payload, dict):
        return None, [FieldError(None, "body", "请求体必须为 JSON 对象")]

    # ---- 探头编号 ----
    probe_id = payload.get("probe_id")
    if not isinstance(probe_id, str) or not probe_id.strip():
        errors.append(FieldError(None, "probe_id", "探头编号不能为空"))
        probe_clean = ""
    else:
        probe_clean = probe_id.strip()
        if len(probe_clean) > MAX_PROBE_LENGTH:
            errors.append(
                FieldError(
                    None,
                    "probe_id",
                    f"探头编号不能超过 {MAX_PROBE_LENGTH} 个字符",
                )
            )

    # ---- 校准时间 ----
    calibrated_at_raw = payload.get("calibrated_at")
    calibrated_moment, at_error = parse_iso8601(calibrated_at_raw)
    if at_error:
        errors.append(FieldError(None, "calibrated_at", at_error))

    # ---- 允许偏差 ----
    tolerance_raw = payload.get("tolerance")
    tolerance_fraction: Optional[Fraction] = None
    if isinstance(tolerance_raw, bool) or not isinstance(
        tolerance_raw, (int, float)
    ):
        errors.append(FieldError(None, "tolerance", "允许偏差必须为正数（°C）"))
    elif tolerance_raw != tolerance_raw:  # NaN
        errors.append(FieldError(None, "tolerance", "允许偏差不能为 NaN"))
    elif tolerance_raw <= 0:
        errors.append(
            FieldError(
                None,
                "tolerance",
                f"允许偏差必须为正数（°C），收到 {tolerance_raw}",
            )
        )
    else:
        tolerance_fraction = _fraction(tolerance_raw)

    # ---- 校准组数 ----
    groups = payload.get("groups")
    if not isinstance(groups, list):
        errors.append(FieldError(None, "groups", "groups 必须为校准组数组"))
        return None, errors
    if not (MIN_GROUPS <= len(groups) <= MAX_GROUPS):
        errors.append(
            FieldError(
                None,
                "groups",
                f"校准组数量须在 {MIN_GROUPS} 至 {MAX_GROUPS} 组之间，"
                f"收到 {len(groups)} 组",
            )
        )

    # ---- 逐组校验 ----
    normalized_groups: List[Optional[CalibrationGroup]] = []
    set_fractions: List[Tuple[int, Fraction]] = []  # 设定温度可解析的组
    for idx, group in enumerate(groups):
        if not isinstance(group, dict):
            errors.append(FieldError(idx, "group", f"第 {idx} 组必须为 JSON 对象"))
            normalized_groups.append(None)
            continue

        set_value = group.get("set_temperature")
        indicator_value = group.get("indicator_reading")
        standard_value = group.get("standard_reading")

        set_error = _reading_error("set_temperature", set_value)
        indicator_error = _reading_error("indicator_reading", indicator_value)
        standard_error = _reading_error("standard_reading", standard_value)

        if set_error:
            errors.append(FieldError(idx, "set_temperature", set_error))
        if indicator_error:
            errors.append(FieldError(idx, "indicator_reading", indicator_error))
        if standard_error:
            errors.append(FieldError(idx, "standard_reading", standard_error))

        if set_error is None:
            set_fractions.append((idx, _fraction(set_value)))

        if set_error is None and indicator_error is None and standard_error is None:
            normalized_groups.append(
                CalibrationGroup(
                    set_temperature=float(set_value),
                    indicator_reading=float(indicator_value),
                    standard_reading=float(standard_value),
                    set_fraction=_fraction(set_value),
                    indicator_fraction=_fraction(indicator_value),
                    standard_fraction=_fraction(standard_value),
                )
            )
        else:
            normalized_groups.append(None)

    # ---- 跨组校验：设定温度严格递增（只比较本身可解析的组） ----
    for (prev_idx, prev_set), (idx, current_set) in zip(
        set_fractions, set_fractions[1:]
    ):
        if current_set <= prev_set:
            errors.append(
                FieldError(
                    idx,
                    "set_temperature",
                    "设定温度必须严格递增（按校准点由低到高填写）："
                    f"该组不高于第 {prev_idx} 组的 {float(prev_set):g}°C",
                )
            )

    if errors:
        return None, errors

    assert calibrated_moment is not None and tolerance_fraction is not None
    return (
        NormalizedCalibration(
            probe_id=probe_clean,
            calibrated_at_raw=calibrated_at_raw.strip(),
            calibrated_at_utc=calibrated_moment.astimezone(timezone.utc),
            tolerance=float(tolerance_raw),
            tolerance_fraction=tolerance_fraction,
            groups=[group for group in normalized_groups if group is not None],
        ),
        [],
    )


def evaluate_calibration(
    normalized: NormalizedCalibration,
) -> Tuple[str, List[Fraction], Fraction]:
    """计算示值误差与最大绝对误差并给出结论。

    返回 (结论, 逐组示值误差, 最大绝对误差)；结论边界恰等算合格。
    """
    errors_fraction = [group.indication_error for group in normalized.groups]
    max_abs = max(abs(value) for value in errors_fraction)
    verdict = (
        CALIBRATION_PASS
        if max_abs <= normalized.tolerance_fraction
        else CALIBRATION_FAIL
    )
    return verdict, errors_fraction, max_abs
