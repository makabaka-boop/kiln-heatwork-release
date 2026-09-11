import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BatchForm } from "../components/BatchForm";
import type { BatchSummary } from "../types";

const CREATED: BatchSummary = {
  id: 7,
  name: "K-2026-0911-A",
  point_count: 4,
  integral_raw: 21000,
  integral_display: "21000.0",
  verdict: "qualified",
  verdict_label: "合格",
  created_at: "2026-09-11T13:00:00+00:00",
};

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function fetchMock() {
  const mock = vi.fn();
  vi.stubGlobal("fetch", mock);
  return mock;
}

beforeEach(() => cleanup());
afterEach(() => vi.unstubAllGlobals());

describe("BatchForm 提交成功", () => {
  it("填入示例后提交，把名称与采样点 JSON 发给后端并回调结果", async () => {
    const mock = fetchMock().mockResolvedValue(jsonResponse(201, CREATED));
    const onCreated = vi.fn();
    render(<BatchForm onCreated={onCreated} />);

    fireEvent.click(screen.getByTestId("sample-fill"));
    fireEvent.submit(screen.getByTestId("batch-form"));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(CREATED));
    const [url, init] = mock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/batches");
    expect(init.method).toBe("POST");
    const payload = JSON.parse(String(init.body));
    expect(payload.name).toBe("K-2026-0911-A");
    expect(payload.points).toHaveLength(4);
    expect(payload.points[0]).toEqual({
      time: "2026-09-11T08:00:00Z",
      temperature: 600,
    });
  });
});

describe("BatchForm 校验失败", () => {
  const detail = {
    message: "提交数据未通过校验，本次数据未保存。",
    errors: [
      { index: null, field: "name", message: "窑次名称不能为空" },
      { index: 1, field: "temperature", message: "温度须在 0 至 1400°C 之间，收到 1500" },
      { index: 2, field: "time", message: "时刻必须严格递增：该点不晚于第 1 个采样点" },
      { index: null, field: "points", message: "首末采样间隔不得超过 12 小时" },
    ],
  };

  it("把每个错误渲染到对应位置，且不回调成功", async () => {
    fetchMock().mockResolvedValue(jsonResponse(422, { detail }));
    const onCreated = vi.fn();
    render(<BatchForm onCreated={onCreated} />);

    // 默认两行，加一行凑出索引 2
    fireEvent.click(screen.getByTestId("add-row"));
    fireEvent.submit(screen.getByTestId("batch-form"));

    await waitFor(() =>
      expect(screen.getByTestId("name-error")).toHaveTextContent(
        "窑次名称不能为空",
      ),
    );
    expect(screen.getByTestId("row-1-temperature-error")).toHaveTextContent(
      "温度须在 0 至 1400°C 之间，收到 1500",
    );
    expect(screen.getByTestId("row-2-time-error")).toHaveTextContent(
      "时刻必须严格递增",
    );
    expect(screen.getByTestId("form-errors")).toHaveTextContent(
      "首末采样间隔不得超过 12 小时",
    );
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("再次编辑时清空已展示的错误", async () => {
    fetchMock().mockResolvedValue(jsonResponse(422, { detail }));
    render(<BatchForm onCreated={vi.fn()} />);
    fireEvent.submit(screen.getByTestId("batch-form"));
    await waitFor(() => screen.getByTestId("name-error"));

    fireEvent.change(screen.getByTestId("name-input"), {
      target: { value: "K-1" },
    });
    expect(screen.queryByTestId("name-error")).not.toBeInTheDocument();
  });
});

describe("BatchForm JSON 填充", () => {
  it("非法 JSON 在填充框旁报错", () => {
    render(<BatchForm onCreated={vi.fn()} />);
    fireEvent.change(screen.getByTestId("json-input"), {
      target: { value: "{not json" },
    });
    fireEvent.click(screen.getByTestId("json-fill"));
    expect(screen.getByTestId("json-error")).toHaveTextContent("JSON 解析失败");
  });

  it("合法 JSON 数组填充为表单行", () => {
    render(<BatchForm onCreated={vi.fn()} />);
    fireEvent.change(screen.getByTestId("json-input"), {
      target: {
        value: JSON.stringify([
          { time: "2026-09-11T08:00:00Z", temperature: 600 },
          { time: "2026-09-11T09:00:00Z", temperature: 700 },
          { time: "2026-09-11T10:00:00Z", temperature: 650 },
        ]),
      },
    });
    fireEvent.click(screen.getByTestId("json-fill"));
    expect(screen.getByTestId("row-2-time")).toHaveValue(
      "2026-09-11T10:00:00Z",
    );
    expect(screen.getByTestId("row-2-temperature")).toHaveValue("650");
  });
});
