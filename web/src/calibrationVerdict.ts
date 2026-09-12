import type { CalibrationVerdict } from "./types";

export interface CalibrationVerdictMeta {
  label: string;
  tone: "ok" | "bad";
  hint: string;
}

export const CALIBRATION_VERDICT_META: Record<
  CalibrationVerdict,
  CalibrationVerdictMeta
> = {
  qualified: {
    label: "合格",
    tone: "ok",
    hint: "最大绝对误差未超过允许偏差，探头可投入使用",
  },
  unqualified: {
    label: "不合格",
    tone: "bad",
    hint: "存在示值误差超过允许偏差的校准点，探头不得投入使用",
  },
};

export function calibrationVerdictMeta(
  verdict: CalibrationVerdict,
): CalibrationVerdictMeta {
  return CALIBRATION_VERDICT_META[verdict];
}
