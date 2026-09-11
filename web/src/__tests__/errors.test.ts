import { describe, expect, it } from "vitest";
import { mapApiErrors, rowErrors } from "../errors";
import type { ApiFieldError } from "../types";

describe("mapApiErrors", () => {
  it("把 name 错误映射到名称输入框", () => {
    const errors: ApiFieldError[] = [
      { index: null, field: "name", message: "窑次名称不能为空" },
    ];
    const mapped = mapApiErrors(errors);
    expect(mapped.name).toBe("窑次名称不能为空");
    expect(mapped.global).toEqual([]);
    expect(mapped.rows.size).toBe(0);
  });

  it("把带索引的错误映射到对应采样点行的对应字段", () => {
    const errors: ApiFieldError[] = [
      { index: 1, field: "temperature", message: "温度须在 0 至 1400°C 之间" },
      { index: 2, field: "time", message: "时刻必须严格递增" },
      { index: 2, field: "temperature", message: "温度必须为数字（摄氏）" },
    ];
    const mapped = mapApiErrors(errors);
    expect(rowErrors(mapped, 1).temperature).toBe("温度须在 0 至 1400°C 之间");
    expect(rowErrors(mapped, 2).time).toBe("时刻必须严格递增");
    expect(rowErrors(mapped, 2).temperature).toBe("温度必须为数字（摄氏）");
    expect(rowErrors(mapped, 0)).toEqual({});
  });

  it("把整表错误（数量、首末间隔）归入全局区域", () => {
    const errors: ApiFieldError[] = [
      { index: null, field: "points", message: "采样点数量须在 2 至 200 个之间" },
      { index: null, field: "points", message: "首末采样间隔不得超过 12 小时" },
    ];
    const mapped = mapApiErrors(errors);
    expect(mapped.global).toHaveLength(2);
    expect(mapped.rows.size).toBe(0);
  });

  it("point 级错误落在对应行", () => {
    const mapped = mapApiErrors([
      { index: 3, field: "point", message: "第 3 个采样点必须为 JSON 对象" },
    ]);
    expect(rowErrors(mapped, 3).point).toBe("第 3 个采样点必须为 JSON 对象");
  });
});
