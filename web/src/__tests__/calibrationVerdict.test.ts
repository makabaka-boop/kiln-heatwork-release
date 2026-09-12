import { describe, expect, it } from "vitest";
import { calibrationVerdictMeta } from "../calibrationVerdict";

describe("calibrationVerdictMeta", () => {
  it("合格结论为绿色并提示可投入使用", () => {
    const meta = calibrationVerdictMeta("qualified");
    expect(meta.label).toBe("合格");
    expect(meta.tone).toBe("ok");
    expect(meta.hint).toContain("可投入使用");
  });

  it("不合格结论为红色并提示不得投入使用", () => {
    const meta = calibrationVerdictMeta("unqualified");
    expect(meta.label).toBe("不合格");
    expect(meta.tone).toBe("bad");
    expect(meta.hint).toContain("不得投入使用");
  });
});
