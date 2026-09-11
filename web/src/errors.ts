import type { ApiFieldError } from "./types";

/** 单个采样点行上的错误，按输入框分列 */
export interface RowErrors {
  time?: string;
  temperature?: string;
  point?: string;
}

/** 映射到表单各位置的错误集合 */
export interface FormErrors {
  name?: string;
  /** 与具体采样点无关的整表错误（数量、首末间隔等） */
  global: string[];
  rows: Map<number, RowErrors>;
}

export const EMPTY_ERRORS: FormErrors = { global: [], rows: new Map() };

/**
 * 把后端 422 错误映射到表单位置：
 * - field=name          -> 名称输入框下方
 * - field=time/temperature/point 且带 index -> 对应采样点行的对应输入框
 * - 其余（points/body 等）-> 表单顶部整体错误区
 */
export function mapApiErrors(errors: ApiFieldError[]): FormErrors {
  const result: FormErrors = { global: [], rows: new Map() };
  for (const error of errors) {
    if (error.field === "name") {
      result.name = error.message;
      continue;
    }
    if (
      error.index !== null &&
      (error.field === "time" ||
        error.field === "temperature" ||
        error.field === "point")
    ) {
      const row = result.rows.get(error.index) ?? {};
      row[error.field] = error.message;
      result.rows.set(error.index, row);
      continue;
    }
    result.global.push(error.message);
  }
  return result;
}

export function rowErrors(form: FormErrors, index: number): RowErrors {
  return form.rows.get(index) ?? {};
}
