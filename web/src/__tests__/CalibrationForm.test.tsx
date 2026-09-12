import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CalibrationForm } from "../components/CalibrationForm";
import type { CalibrationRecord } from "../types";

const CREATED: CalibrationRecord = {
  id: 5,
  probe_id: "TC-K-2026-0912-01",
  calibrated_at: "2026-09-12T10:00:00Z",
  tolerance: 2,
  groups: [
    {
      index: 0,
      set_temperature: 100,
      indicator_reading: 101,
      standard_reading: 100,
      indication_error: 1,
    },
    {
      index: 1,
      set_temperature: 500,
      indicator_reading: 502,
      standard_reading: 500,
      indication_error: 2,
    },
    {
      index: 2,
      set_temperature: 800,
      indicator_reading: 798,
      standard_reading: 800,
      indication_error: -2,
    },
    {
      index: 3,
      set_temperature: 1200,
      indicator_reading: 1201,
      standard_reading: 1200,
      indication_error: 1,
    },
  ],
  group_count: 4,
  indication_errors: [1, 2, -2, 1],
  max_abs_error: 2,
  verdict: "qualified",
  verdict_label: "合格",
  created_at: "2026-09-12T10:05:00+00:00",
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

describe("CalibrationForm 提交成功", () => {
  it("填入示例后提交，把探头编号/校准时间/允许偏差/校准组上送并回调结果", async () => {
    const mock = fetchMock().mockResolvedValue(jsonResponse(201, CREATED));
    const onCreated = vi.fn();
    const onDirty = vi.fn();
    render(<CalibrationForm onCreated={onCreated} onDirty={onDirty} />);

    fireEvent.click(screen.getByTestId("cal-sample"));
    fireEvent.submit(screen.getByTestId("calibration-form"));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(CREATED));
    const [url, init] = mock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/calibrations");
    expect(init.method).toBe("POST");
    const payload = JSON.parse(String(init.body));
    expect(payload.probe_id).toBe("TC-K-2026-0912-01");
    expect(payload.calibrated_at).toBe("2026-09-12T10:00:00Z");
    expect(payload.tolerance).toBe(2);
    expect(payload.groups).toHaveLength(4);
    expect(payload.groups[0]).toEqual({
      set_temperature: 100,
      indicator_reading: 101,
      standard_reading: 100,
    });
  });
});

describe("CalibrationForm 校验失败", () => {
  const detail = {
    message: "校准核验数据未通过校验，本次数据未保存。",
    errors: [
      { index: null, field: "probe_id", message: "探头编号不能为空" },
      { index: null, field: "tolerance", message: "允许偏差必须为正数" },
      {
        index: 0,
        field: "indicator_reading",
        message: "温度读数须在 0 至 1400°C 之间，收到 1500",
      },
      { index: 1, field: "set_temperature", message: "设定温度必须严格递增" },
      { index: null, field: "groups", message: "校准组数量须在 3 至 12 组之间" },
    ],
  };

  it("把每个错误渲染到对应位置，且不回调成功", async () => {
    fetchMock().mockResolvedValue(jsonResponse(422, { detail }));
    const onCreated = vi.fn();
    render(<CalibrationForm onCreated={onCreated} />);

    fireEvent.submit(screen.getByTestId("calibration-form"));

    await waitFor(() =>
      expect(screen.getByTestId("cal-probe-id-error")).toHaveTextContent(
        "探头编号不能为空",
      ),
    );
    expect(screen.getByTestId("cal-tolerance-error")).toHaveTextContent(
      "允许偏差必须为正数",
    );
    expect(screen.getByTestId("cal-group-0-indicator-error")).toHaveTextContent(
      "0 至 1400°C",
    );
    expect(screen.getByTestId("cal-group-1-set-error")).toHaveTextContent(
      "严格递增",
    );
    expect(screen.getByTestId("cal-form-errors")).toHaveTextContent("3 至 12 组");
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("409 重复核验单错误同样定位到探头编号输入框", async () => {
    fetchMock().mockResolvedValue(
      jsonResponse(409, {
        detail: {
          reason: "duplicate_calibration",
          message: "校准核验数据未保存。",
          errors: [
            {
              index: null,
              field: "probe_id",
              message: "探头 TC-1 在该校准时间已有核验单，不能重复提交。",
            },
          ],
        },
      }),
    );
    const onCreated = vi.fn();
    render(<CalibrationForm onCreated={onCreated} />);
    fireEvent.submit(screen.getByTestId("calibration-form"));

    await waitFor(() =>
      expect(screen.getByTestId("cal-probe-id-error")).toHaveTextContent(
        "不能重复提交",
      ),
    );
    expect(onCreated).not.toHaveBeenCalled();
  });
});
