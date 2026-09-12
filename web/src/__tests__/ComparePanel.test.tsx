import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ComparePanel } from "../components/ComparePanel";
import type { BatchSummary, CompareResult } from "../types";

function summary(id: number, name: string): BatchSummary {
  return {
    id,
    name,
    point_count: 4,
    integral_raw: 21000,
    integral_display: "21000.0",
    verdict: "qualified",
    verdict_label: "合格",
    created_at: "2026-09-11T13:00:00+00:00",
  };
}

function result(referenceId: number): CompareResult {
  const side = (id: number) => ({
    id,
    name: `K-${id}`,
    point_count: 4,
    integral_display: "21000.0",
    verdict: "qualified" as const,
    verdict_label: "合格",
    created_at: "2026-09-11T13:00:00+00:00",
  });
  return {
    batch: side(1),
    reference: side(referenceId),
    common_minutes: 300,
    nodes: [
      { elapsed_minutes: 0, temperature_delta: 0, heatwork_delta: 0 },
      { elapsed_minutes: 30, temperature_delta: 25, heatwork_delta: 375 },
      { elapsed_minutes: 60, temperature_delta: -12.5, heatwork_delta: -7.25 },
    ],
  };
}

afterEach(() => cleanup());

function renderPanel(overrides: Partial<Parameters<typeof ComparePanel>[0]> = {}) {
  const props: Parameters<typeof ComparePanel>[0] = {
    currentId: 1,
    batches: [summary(1, "K-1"), summary(2, "K-2"), summary(3, "K-3")],
    referenceId: null,
    result: null,
    error: null,
    loading: false,
    onSelectReference: () => {},
    ...overrides,
  };
  render(<ComparePanel {...props} />);
  return props;
}

describe("ComparePanel", () => {
  it("参照候选排除当前窑次，选择后立即回调", () => {
    const onSelectReference = vi.fn();
    renderPanel({ onSelectReference });

    const select = screen.getByTestId("compare-reference-select");
    expect(select).not.toHaveTextContent("#1 K-1");
    expect(select).toHaveTextContent("#2 K-2");
    expect(select).toHaveTextContent("#3 K-3");

    fireEvent.change(select, { target: { value: "3" } });
    expect(onSelectReference).toHaveBeenCalledWith(3);

    fireEvent.change(select, { target: { value: "" } });
    expect(onSelectReference).toHaveBeenCalledWith(null);
  });

  it("没有其他窑次时提示暂无参照", () => {
    renderPanel({ batches: [summary(1, "K-1")] });
    expect(screen.getByTestId("compare-empty")).toHaveTextContent(
      "暂无其他窑次可作为参照",
    );
  });

  it("对比结果按节点展示经过分钟与带符号差值", () => {
    renderPanel({ referenceId: 2, result: result(2) });

    expect(screen.getByTestId("compare-summary")).toHaveTextContent(
      "共同持续区间为 300 分钟",
    );
    expect(screen.getByTestId("compare-summary")).toHaveTextContent("K-2");
    // 零差值不带符号，正差值带 +，负差值带 −，非整数保留两位小数
    expect(screen.getByTestId("compare-0-temperature-delta")).toHaveTextContent(
      "0",
    );
    expect(screen.getByTestId("compare-1-temperature-delta")).toHaveTextContent(
      "+25",
    );
    expect(screen.getByTestId("compare-1-heatwork-delta")).toHaveTextContent(
      "+375",
    );
    expect(screen.getByTestId("compare-2-temperature-delta")).toHaveTextContent(
      "-12.5",
    );
    expect(screen.getByTestId("compare-2-heatwork-delta")).toHaveTextContent(
      "-7.25",
    );
  });

  it("加载中与失败提示分别展示", () => {
    const { unmount } = render(
      <ComparePanel
        currentId={1}
        batches={[summary(1, "K-1"), summary(2, "K-2")]}
        referenceId={2}
        result={null}
        error={null}
        loading
        onSelectReference={() => {}}
      />,
    );
    expect(screen.getByTestId("compare-loading")).toBeInTheDocument();
    unmount();

    renderPanel({
      referenceId: 2,
      error: "窑次 2「K-2」第 0 个采样点时刻无法解析，无法参与对比。",
    });
    expect(screen.getByTestId("compare-error")).toHaveTextContent(
      "无法参与对比",
    );
    expect(screen.queryByTestId("compare-table")).not.toBeInTheDocument();
  });
});
