import type { ApiFieldError } from "./types";

/** 单个校准组上的错误，按输入框分列 */
export interface CalibrationGroupErrors {
  set_temperature?: string;
  indicator_reading?: string;
  standard_reading?: string;
  group?: string;
}

/** 映射到核验单各位置的错误集合 */
export interface CalibrationFormErrors {
  probe_id?: string;
  calibrated_at?: string;
  tolerance?: string;
  /** 与具体校准组无关的整单错误（组数等） */
  global: string[];
  groups: Map<number, CalibrationGroupErrors>;
}

export const EMPTY_CALIBRATION_ERRORS: CalibrationFormErrors = {
  global: [],
  groups: new Map(),
};

/**
 * 把后端 422/409 错误映射到核验单位置：
 * - field=probe_id / calibrated_at / tolerance -> 对应表头输入框下方
 * - field=set_temperature / indicator_reading / standard_reading / group
 *   且带 index -> 对应校准组的对应输入框
 * - 其余（groups/body 等）-> 表单顶部整体错误区
 */
export function mapCalibrationErrors(
  errors: ApiFieldError[],
): CalibrationFormErrors {
  const result: CalibrationFormErrors = { global: [], groups: new Map() };
  for (const error of errors) {
    if (error.field === "probe_id") {
      result.probe_id = error.message;
      continue;
    }
    if (error.field === "calibrated_at") {
      result.calibrated_at = error.message;
      continue;
    }
    if (error.field === "tolerance") {
      result.tolerance = error.message;
      continue;
    }
    if (
      error.index !== null &&
      (error.field === "set_temperature" ||
        error.field === "indicator_reading" ||
        error.field === "standard_reading" ||
        error.field === "group")
    ) {
      const group = result.groups.get(error.index) ?? {};
      group[error.field as keyof CalibrationGroupErrors] = error.message;
      result.groups.set(error.index, group);
      continue;
    }
    result.global.push(error.message);
  }
  return result;
}

export function calibrationGroupErrors(
  form: CalibrationFormErrors,
  index: number,
): CalibrationGroupErrors {
  return form.groups.get(index) ?? {};
}
