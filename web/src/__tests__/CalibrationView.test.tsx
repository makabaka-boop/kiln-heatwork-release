import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CalibrationView } from "../components/CalibrationView";
import type { CalibrationRecord } from "../types";

function record(id: number, verdict: "qualified" | "unqualified"): CalibrationRecord {
  const qualified = verdict === "qualified";
  return {
    id,
    probe_id: "TC-1",
    calibrated_at: "2026-09-12T10:00:00Z",
    tolerance: 2,
    groups: [
      {
        index: 0,
        set_temperature: 100,
        indicator_reading: qualified ? 101 : 101,
        standard_reading: 100,
        indication_error: 1,
      },
      {
        index: 1,
        set_temperature: 500,
        indicator_reading: qualified ? 502 : 502,
        standard_reading: 500,
        indication_error: 2,
      },
      {
        index: 2,
        set_temperature: 1000,
        indicator_reading: qualified ? 1000 : 1003,
        standard_reading: 1000,
        indication_error: qualified ? 0 : 3,
      },
    ],
    group_count: 3,
    indication_errors: qualified ? [1, 2, 0] : [1, 2, 3],
    max_abs_error: qualified ? 2 : 3,
    verdict,
    verdict_label: qualified ? "合格" : "不合格",
    created_at: "2026-09-12T10:05:00+00:00",
  };
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

let mock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  cleanup();
  mock = vi.fn();
  vi.stubGlobal("fetch", mock);
});
afterEach(() => vi.unstubAllGlobals());

describe("CalibrationView 提交后转入详情", () => {
  it("提交成功后详情展示结论与判定依据，编号可用于重新打开", async () => {
    mock.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/calibrations" && init?.method === "POST") {
        return Promise.resolve(jsonResponse(201, record(7, "qualified")));
      }
      throw new Error(`unexpected ${url}`);
    });
    render(<CalibrationView />);

    fireEvent.click(screen.getByTestId("cal-sample"));
    // 示例为 4 组，删一组到 3 组不影响提交体（直接提交示例即可，4 组合法）
    fireEvent.submit(screen.getByTestId("calibration-form"));

    const detail = await screen.findByTestId("calibration-detail");
    expect(detail).toHaveTextContent("合格");
    expect(screen.getByTestId("cal-verdict")).toHaveTextContent("合格");
    expect(screen.getByTestId("cal-max-abs-error")).toHaveTextContent("2");
    expect(screen.getByTestId("cal-tolerance-value")).toHaveTextContent("±2");
    expect(screen.getByTestId("cal-group-1-error-value")).toHaveTextContent("+2");
    expect(screen.getByTestId("cal-group-2-error-value")).toHaveTextContent("0");
    // 编号被带回查找框，刷新后可凭此重新打开
    expect(screen.getByTestId("cal-lookup-input")).toHaveValue("7");
    // 判定依据中的不可变说明
    expect(screen.getByTestId("cal-immutable-note")).toHaveTextContent("≤");
  });

  it("单点超差的核验单判定为不合格并在该行标注超差", async () => {
    mock.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/calibrations" && init?.method === "POST") {
        return Promise.resolve(jsonResponse(201, record(8, "unqualified")));
      }
      throw new Error(`unexpected ${url}`);
    });
    render(<CalibrationView />);
    fireEvent.click(screen.getByTestId("cal-sample"));
    fireEvent.submit(screen.getByTestId("calibration-form"));

    await screen.findByTestId("calibration-detail");
    expect(screen.getByTestId("cal-verdict")).toHaveTextContent("不合格");
    expect(screen.getByTestId("cal-max-abs-error")).toHaveTextContent("3");
    expect(screen.getByTestId("cal-group-2-error-value")).toHaveTextContent("+3");
    expect(screen.getByTestId("cal-group-2-error-value")).toHaveTextContent("超差");
    expect(screen.getByTestId("cal-immutable-note")).toHaveTextContent(">");
  });
});

describe("CalibrationView 按编号重新打开", () => {
  it("输入编号后请求详情并展示（刷新后重新打开的闭环）", async () => {
    mock.mockImplementation((url: string) => {
      if (url === "/api/calibrations/9") {
        return Promise.resolve(jsonResponse(200, record(9, "qualified")));
      }
      throw new Error(`unexpected ${url}`);
    });
    render(<CalibrationView />);

    fireEvent.change(screen.getByTestId("cal-lookup-input"), {
      target: { value: "9" },
    });
    fireEvent.submit(screen.getByTestId("cal-lookup"));

    await screen.findByTestId("calibration-detail");
    expect(screen.getByTestId("cal-probe-id-value")).toHaveTextContent("TC-1");
    expect(screen.getByTestId("cal-verdict")).toHaveTextContent("合格");
    expect(mock).toHaveBeenCalledWith("/api/calibrations/9");
  });

  it("编号不存在时就地提示，不展示详情", async () => {
    mock.mockImplementation((url: string) => {
      if (url === "/api/calibrations/404") {
        return Promise.resolve(
          jsonResponse(404, {
            detail: {
              reason: "calibration_not_found",
              message: "校准核验单 404 不存在",
            },
          }),
        );
      }
      throw new Error(`unexpected ${url}`);
    });
    render(<CalibrationView />);

    fireEvent.change(screen.getByTestId("cal-lookup-input"), {
      target: { value: "404" },
    });
    fireEvent.submit(screen.getByTestId("cal-lookup"));

    await screen.findByTestId("cal-lookup-error");
    expect(screen.getByTestId("cal-lookup-error")).toHaveTextContent("不存在");
    expect(screen.queryByTestId("calibration-detail")).not.toBeInTheDocument();
  });

  it("非法编号（非正整数）不发起请求并提示", () => {
    render(<CalibrationView />);
    fireEvent.change(screen.getByTestId("cal-lookup-input"), {
      target: { value: "abc" },
    });
    fireEvent.submit(screen.getByTestId("cal-lookup"));
    expect(screen.getByTestId("cal-lookup-error")).toHaveTextContent("正整数");
    expect(mock).not.toHaveBeenCalled();
  });

  it("重新编辑表单时已展示的详情立即隐藏", async () => {
    mock.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/calibrations" && init?.method === "POST") {
        return Promise.resolve(jsonResponse(201, record(7, "qualified")));
      }
      throw new Error(`unexpected ${url}`);
    });
    render(<CalibrationView />);
    fireEvent.click(screen.getByTestId("cal-sample"));
    fireEvent.submit(screen.getByTestId("calibration-form"));
    await screen.findByTestId("calibration-detail");

    // 再次编辑探头编号 -> 上一张结论已与当前输入不符，立即隐藏
    fireEvent.change(screen.getByTestId("cal-probe-id"), {
      target: { value: "TC-CHANGED" },
    });
    await waitFor(() =>
      expect(screen.queryByTestId("calibration-detail")).not.toBeInTheDocument(),
    );
  });
});
