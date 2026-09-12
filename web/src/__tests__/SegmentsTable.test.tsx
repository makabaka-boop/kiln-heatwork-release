import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { SegmentsTable } from "../components/SegmentsTable";
import type { SegmentContribution } from "../types";

const SEGMENTS: SegmentContribution[] = [
  {
    index: 0,
    start_time: "2026-09-11T08:00:00Z",
    end_time: "2026-09-11T10:00:00Z",
    heating_minutes: 120,
    contribution: 6000,
    share: 2 / 7,
  },
  {
    index: 1,
    start_time: "2026-09-11T10:00:00Z",
    end_time: "2026-09-11T12:00:00Z",
    heating_minutes: 120,
    contribution: 12000,
    share: 4 / 7,
  },
  {
    index: 2,
    start_time: "2026-09-11T12:00:00Z",
    end_time: "2026-09-11T13:00:00Z",
    heating_minutes: 0,
    contribution: 0,
    share: 0,
  },
];

afterEach(() => cleanup());

describe("SegmentsTable", () => {
  it("按时间顺序渲染每段的起止时刻、分钟数、贡献与占比", () => {
    render(<SegmentsTable segments={SEGMENTS} note={null} />);

    const row0 = screen.getByTestId("segment-row-0");
    expect(row0).toHaveTextContent("2026-09-11T08:00:00Z");
    expect(row0).toHaveTextContent("2026-09-11T10:00:00Z");
    expect(screen.getByTestId("segment-0-minutes")).toHaveTextContent("120");
    expect(screen.getByTestId("segment-0-contribution")).toHaveTextContent(
      "6000",
    );
    expect(row0).toHaveTextContent("28.6%");

    expect(screen.getByTestId("segment-1-contribution")).toHaveTextContent(
      "12000",
    );
    expect(screen.getByTestId("segment-row-1")).toHaveTextContent("57.1%");
  });

  it("低于起点的零贡献段保留展示", () => {
    render(<SegmentsTable segments={SEGMENTS} note={null} />);

    const zeroRow = screen.getByTestId("segment-row-2");
    expect(zeroRow).toBeVisible();
    expect(zeroRow).toHaveClass("segment-zero");
    expect(screen.getByTestId("segment-2-minutes")).toHaveTextContent("0");
    expect(screen.getByTestId("segment-2-contribution")).toHaveTextContent("0");
    expect(zeroRow).toHaveTextContent("0.0%");
  });

  it("非整数计热分钟数保留两位小数", () => {
    const segments: SegmentContribution[] = [
      {
        index: 0,
        start_time: "2026-09-11T00:00:00Z",
        end_time: "2026-09-11T01:00:00Z",
        heating_minutes: 30.25,
        contribution: 1500,
        share: 1,
      },
    ];
    render(<SegmentsTable segments={segments} note={null} />);
    expect(screen.getByTestId("segment-0-minutes")).toHaveTextContent("30.25");
  });

  it("明细缺失时展示后端给出的原因说明", () => {
    render(
      <SegmentsTable
        segments={null}
        note="该记录为升级前保存，未保存分段明细；已存采样点时刻无法解析，无法补算。"
      />,
    );
    expect(screen.queryByTestId("segments-table")).not.toBeInTheDocument();
    expect(screen.getByTestId("segments-note")).toHaveTextContent(
      "已存采样点时刻无法解析",
    );
  });
});
