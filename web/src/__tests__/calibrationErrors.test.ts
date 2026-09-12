import { describe, expect, it } from "vitest";
import {
  calibrationGroupErrors,
  mapCalibrationErrors,
} from "../calibrationErrors";
import type { ApiFieldError } from "../types";

describe("mapCalibrationErrors", () => {
  it("把表头字段错误映射到对应输入框", () => {
    const errors: ApiFieldError[] = [
      { index: null, field: "probe_id", message: "探头编号不能为空" },
      { index: null, field: "calibrated_at", message: "时刻无法解析" },
      { index: null, field: "tolerance", message: "允许偏差必须为正数" },
    ];
    const mapped = mapCalibrationErrors(errors);
    expect(mapped.probe_id).toBe("探头编号不能为空");
    expect(mapped.calibrated_at).toBe("时刻无法解析");
    expect(mapped.tolerance).toBe("允许偏差必须为正数");
    expect(mapped.global).toEqual([]);
    expect(mapped.groups.size).toBe(0);
  });

  it("把带索引的错误映射到对应校准组的对应输入框", () => {
    const errors: ApiFieldError[] = [
      {
        index: 0,
        field: "indicator_reading",
        message: "温度读数须在 0 至 1400°C 之间",
      },
      { index: 1, field: "set_temperature", message: "设定温度必须严格递增" },
      { index: 1, field: "standard_reading", message: "温度读数必须为数字" },
    ];
    const mapped = mapCalibrationErrors(errors);
    expect(calibrationGroupErrors(mapped, 0).indicator_reading).toBe(
      "温度读数须在 0 至 1400°C 之间",
    );
    expect(calibrationGroupErrors(mapped, 1).set_temperature).toBe(
      "设定温度必须严格递增",
    );
    expect(calibrationGroupErrors(mapped, 1).standard_reading).toBe(
      "温度读数必须为数字",
    );
    expect(calibrationGroupErrors(mapped, 2)).toEqual({});
  });

  it("重复核验单（probe_id）错误落在探头编号输入框", () => {
    const mapped = mapCalibrationErrors([
      { index: null, field: "probe_id", message: "已有核验单，不能重复提交" },
    ]);
    expect(mapped.probe_id).toContain("不能重复提交");
  });

  it("整单错误（组数）归入全局区域", () => {
    const mapped = mapCalibrationErrors([
      { index: null, field: "groups", message: "校准组数量须在 3 至 12 组之间" },
      { index: 2, field: "group", message: "第 2 组必须为 JSON 对象" },
    ]);
    expect(mapped.global).toEqual(["校准组数量须在 3 至 12 组之间"]);
    expect(calibrationGroupErrors(mapped, 2).group).toBe(
      "第 2 组必须为 JSON 对象",
    );
  });
});
