import { describe, expect, it } from "vitest";
import { verdictMeta } from "../verdict";

describe("verdictMeta", () => {
  it("三种结论各对应唯一中文标签", () => {
    expect(verdictMeta("underfired").label).toBe("欠烧");
    expect(verdictMeta("qualified").label).toBe("合格");
    expect(verdictMeta("overfired").label).toBe("过烧");
  });

  it("每种结论有独立色调", () => {
    const tones = new Set(
      (["underfired", "qualified", "overfired"] as const).map(
        (v) => verdictMeta(v).tone,
      ),
    );
    expect(tones.size).toBe(3);
  });
});
