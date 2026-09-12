import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { BatchDetail, BatchSummary, CompareResult } from "../types";

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
    segments: [],
    segments_note: null,
  };
}

function detail(id: number, name: string): BatchDetail {
  return { ...summary(id, name), points: [] };
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** 可控的 Promise，测试自行决定何时让请求返回 */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

let mock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  cleanup();
  mock = vi.fn();
  vi.stubGlobal("fetch", mock);
});

afterEach(() => vi.unstubAllGlobals());

/** 初始历史列表就绪，返回两条窑次 */
async function renderWithHistory() {
  mock.mockImplementation((url: string) => {
    if (url === "/api/batches") {
      return Promise.resolve(
        jsonResponse(200, { batches: [summary(1, "K-1"), summary(2, "K-2")] }),
      );
    }
    throw new Error(`unexpected ${url}`);
  });
  render(<App />);
  await screen.findByTestId("history-row-1");
  // 清掉列表请求，后续断言只关注详情/提交请求
  mock.mockClear();
}

describe("失效结果隐藏", () => {
  it("提交成功后再修改名称，上一窑次的判定结果立即隐藏", async () => {
    mock.mockImplementation((url: string) => {
      if (url === "/api/batches") {
        // GET 列表与 POST 提交同路径，按 method 区分
        return Promise.resolve(jsonResponse(200, { batches: [] }));
      }
      throw new Error(`unexpected ${url}`);
    });
    render(<App />);
    await waitFor(() => expect(mock).toHaveBeenCalled());

    mock.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/batches" && init?.method === "POST") {
        return Promise.resolve(jsonResponse(201, summary(9, "K-OK")));
      }
      if (url === "/api/batches") {
        return Promise.resolve(
          jsonResponse(200, { batches: [summary(9, "K-OK")] }),
        );
      }
      throw new Error(`unexpected ${url}`);
    });

    fireEvent.change(screen.getByTestId("name-input"), {
      target: { value: "K-OK" },
    });
    fireEvent.submit(screen.getByTestId("batch-form"));
    await screen.findByTestId("result");
    expect(screen.getByTestId("result-name")).toHaveTextContent("K-OK");

    // 再改名称 -> 上一窑次结果已失效，必须隐藏
    fireEvent.change(screen.getByTestId("name-input"), {
      target: { value: "K-OK-改" },
    });
    expect(screen.queryByTestId("result")).not.toBeInTheDocument();
  });

  it("提交成功后再修改采样点，上一窑次的判定结果立即隐藏", async () => {
    mock.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/batches" && init?.method === "POST") {
        return Promise.resolve(jsonResponse(201, summary(9, "K-OK")));
      }
      if (url === "/api/batches") {
        return Promise.resolve(
          jsonResponse(200, { batches: [summary(9, "K-OK")] }),
        );
      }
      throw new Error(`unexpected ${url}`);
    });
    render(<App />);

    fireEvent.change(screen.getByTestId("row-0-time"), {
      target: { value: "2026-09-11T08:00:00Z" },
    });
    fireEvent.submit(screen.getByTestId("batch-form"));
    await screen.findByTestId("result");

    fireEvent.change(screen.getByTestId("row-0-temperature"), {
      target: { value: "650" },
    });
    expect(screen.queryByTestId("result")).not.toBeInTheDocument();
  });
});

describe("历史详情请求乱序", () => {
  it("快速切换两条窑次且响应逆序返回时，最终展示最后选择的窑次", async () => {
    await renderWithHistory();
    const d1 = deferred<Response>();
    const d2 = deferred<Response>();
    mock.mockImplementation((url: string) => {
      if (url === "/api/batches/1") return d1.promise;
      if (url === "/api/batches/2") return d2.promise;
      throw new Error(`unexpected ${url}`);
    });

    fireEvent.click(screen.getByTestId("history-row-1"));
    fireEvent.click(screen.getByTestId("history-row-2"));

    // 切换瞬间高亮与加载态就指向最后选择的第 2 条
    expect(screen.getByTestId("history-row-2")).toHaveClass("selected");
    expect(screen.getByTestId("history-row-1")).not.toHaveClass("selected");
    expect(screen.getByTestId("detail-loading")).toBeInTheDocument();

    // 先点的第 1 条响应最后才回来
    d2.resolve(jsonResponse(200, detail(2, "K-2")));
    d1.resolve(jsonResponse(200, detail(1, "K-1")));

    await screen.findByTestId("batch-detail");
    expect(screen.getByTestId("detail-verdict")).toBeInTheDocument();
    // 详情标题指向最后选择的 K-2（K-1 仅作为参照候选出现在下拉框中）
    expect(
      screen.getByRole("heading", { name: "窑次详情：K-2" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "窑次详情：K-1" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId("detail-loading")).not.toBeInTheDocument();
  });
});

describe("旧失败提示清除", () => {
  it("详情加载失败后成功打开其他记录，失败提示随新详情清除", async () => {
    await renderWithHistory();

    fireEvent.click(screen.getByTestId("history-row-1"));
    await screen.findByTestId("detail-error");
    // 列表初始实现对详情 URL 会抛错，这里正好作为失败请求
    expect(screen.getByTestId("detail-error")).toBeInTheDocument();

    mock.mockImplementation((url: string) => {
      if (url === "/api/batches/2") {
        return Promise.resolve(jsonResponse(200, detail(2, "K-2")));
      }
      throw new Error(`unexpected ${url}`);
    });

    fireEvent.click(screen.getByTestId("history-row-2"));
    await screen.findByTestId("batch-detail");
    expect(screen.queryByTestId("detail-error")).not.toBeInTheDocument();
    expect(screen.getByTestId("batch-detail")).toHaveTextContent("K-2");
  });

  it("同一条记录先失败后成功，成功响应到达后失败提示不残留", async () => {
    await renderWithHistory();
    const d1 = deferred<Response>();
    mock.mockImplementation((url: string) =>
      url === "/api/batches/1" ? d1.promise : Promise.reject(new Error("boom")),
    );
    fireEvent.click(screen.getByTestId("history-row-1"));
    d1.reject(new Error("网络中断"));
    await screen.findByTestId("detail-error");
    expect(screen.queryByTestId("batch-detail")).not.toBeInTheDocument();

    const d2 = deferred<Response>();
    mock.mockImplementation((url: string) =>
      url === "/api/batches/1" ? d2.promise : Promise.reject(new Error("boom")),
    );
    fireEvent.click(screen.getByTestId("history-row-1"));
    expect(screen.queryByTestId("detail-error")).not.toBeInTheDocument();
    d2.resolve(jsonResponse(200, detail(1, "K-1")));

    await screen.findByTestId("batch-detail");
    expect(screen.queryByTestId("detail-error")).not.toBeInTheDocument();
  });
});

describe("切换中的加载态", () => {
  it("从已打开的详情切换到慢请求的窑次时，旧详情卸载并明确显示加载中与新选中行", async () => {
    await renderWithHistory();
    mock.mockImplementation((url: string) => {
      if (url === "/api/batches/1") {
        return Promise.resolve(jsonResponse(200, detail(1, "K-1")));
      }
      throw new Error(`unexpected ${url}`);
    });
    fireEvent.click(screen.getByTestId("history-row-1"));
    await screen.findByText("窑次详情：K-1");

    const d2 = deferred<Response>();
    mock.mockImplementation((url: string) =>
      url === "/api/batches/2" ? d2.promise : Promise.reject(new Error("boom")),
    );
    fireEvent.click(screen.getByTestId("history-row-2"));

    // 立即反映新选择：新行高亮、旧详情消失、加载态出现
    expect(screen.getByTestId("history-row-2")).toHaveClass("selected");
    expect(screen.getByTestId("history-row-1")).not.toHaveClass("selected");
    expect(screen.queryByTestId("batch-detail")).not.toBeInTheDocument();
    expect(screen.getByTestId("detail-loading")).toBeInTheDocument();

    d2.resolve(jsonResponse(200, detail(2, "K-2")));
    await screen.findByText("窑次详情：K-2");
    expect(screen.queryByTestId("detail-loading")).not.toBeInTheDocument();
  });

  it("慢请求期间又选择第三条窑次，前一条的迟到响应不会顶替当前选择", async () => {
    await renderWithHistory();
    const d1 = deferred<Response>();
    const d2 = deferred<Response>();
    mock.mockImplementation((url: string) => {
      if (url === "/api/batches/1") return d1.promise;
      if (url === "/api/batches/2") return d2.promise;
      throw new Error(`unexpected ${url}`);
    });

    fireEvent.click(screen.getByTestId("history-row-1"));
    // 第 1 条还在加载时切到第 2 条；随后列表/场景中只验证最后选择
    fireEvent.click(screen.getByTestId("history-row-2"));
    d1.resolve(jsonResponse(200, detail(1, "K-1")));
    expect(screen.queryByTestId("batch-detail")).not.toBeInTheDocument();
    expect(screen.getByTestId("detail-loading")).toBeInTheDocument();
    d2.resolve(jsonResponse(200, detail(2, "K-2")));

    await screen.findByText("窑次详情：K-2");
  });
});

/** 复算生成的新窑次（id=2，来源为 id=1 的 K-1） */
function recomputedSummary(): BatchSummary {
  return {
    ...summary(2, "K-1"),
    source_batch_id: 1,
    source_name: "K-1",
    recomputed_at: "2026-09-12T01:00:00+00:00",
    source: {
      id: 1,
      name: "K-1",
      integral_display: "21000.0",
      verdict: "qualified",
      verdict_label: "合格",
      created_at: "2026-09-11T13:00:00+00:00",
    },
  };
}

function recomputedDetail(): BatchDetail {
  return { ...recomputedSummary(), points: [] };
}

describe("按当前规则复算", () => {
  it("复算成功：生成新记录，详情展示来源关系，历史列表标识复算自某窑次", async () => {
    let recomputed = false;
    mock.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/batches/1/recompute" && init?.method === "POST") {
        recomputed = true;
        return Promise.resolve(jsonResponse(201, recomputedSummary()));
      }
      if (url === "/api/batches/2") {
        return Promise.resolve(jsonResponse(200, recomputedDetail()));
      }
      if (url === "/api/batches/1") {
        return Promise.resolve(jsonResponse(200, detail(1, "K-1")));
      }
      if (url === "/api/batches") {
        return Promise.resolve(
          jsonResponse(200, {
            batches: recomputed
              ? [recomputedSummary(), summary(1, "K-1")]
              : [summary(1, "K-1")],
          }),
        );
      }
      throw new Error(`unexpected ${url}`);
    });
    render(<App />);
    await screen.findByTestId("history-row-1");
    fireEvent.click(screen.getByTestId("history-row-1"));
    await screen.findByTestId("batch-detail");

    fireEvent.click(screen.getByTestId("recompute-button"));

    // 新窑次详情打开，展示「复算自某窑次」与复算时间
    await screen.findByTestId("detail-source");
    expect(screen.getByTestId("detail-source")).toHaveTextContent(
      "复算自窑次 #1",
    );
    expect(screen.getByTestId("detail-recomputed-at")).toBeInTheDocument();
    // 历史列表新增一行并标识来源，新行被选中
    expect(screen.getByTestId("history-row-2")).toHaveClass("selected");
    expect(screen.getByTestId("history-source-2")).toHaveTextContent(
      "复算自 K-1",
    );
  });

  it("复算失败：停留在原详情并显示提示，不清除当前选择", async () => {
    mock.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/batches/1/recompute" && init?.method === "POST") {
        return Promise.resolve(
          jsonResponse(422, {
            detail: {
              reason: "source_invalid",
              message:
                "该记录的原始采样点未通过当前校验，无法复算，未新增记录。",
              errors: [
                {
                  index: 0,
                  field: "time",
                  message: "时刻必须为 ISO 8601 字符串",
                },
              ],
            },
          }),
        );
      }
      if (url === "/api/batches/1") {
        return Promise.resolve(jsonResponse(200, detail(1, "K-1")));
      }
      if (url === "/api/batches") {
        return Promise.resolve(
          jsonResponse(200, { batches: [summary(1, "K-1")] }),
        );
      }
      throw new Error(`unexpected ${url}`);
    });
    render(<App />);
    await screen.findByTestId("history-row-1");
    fireEvent.click(screen.getByTestId("history-row-1"));
    await screen.findByTestId("batch-detail");

    fireEvent.click(screen.getByTestId("recompute-button"));

    await screen.findByTestId("recompute-error");
    expect(screen.getByTestId("recompute-error")).toHaveTextContent(
      "未通过当前校验",
    );
    // 原详情与当前选择保持不变，历史列表不新增行
    expect(screen.getByTestId("batch-detail")).toBeInTheDocument();
    expect(screen.getByTestId("history-row-1")).toHaveClass("selected");
    expect(screen.queryByTestId("history-row-2")).not.toBeInTheDocument();
  });
});

/** 对比结果：当前 K-1 对参照 K-2，含正/零差值节点 */
function compareResult(batchId: number, referenceId: number): CompareResult {
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
    batch: side(batchId),
    reference: side(referenceId),
    common_minutes: 300,
    nodes: [
      { elapsed_minutes: 0, temperature_delta: 0, heatwork_delta: 0 },
      { elapsed_minutes: 30, temperature_delta: 25, heatwork_delta: 375 },
      { elapsed_minutes: 60, temperature_delta: 50, heatwork_delta: 1500 },
    ],
  };
}

describe("轨迹对比", () => {
  it("选择参照后请求对比并展示对齐节点与带符号差值", async () => {
    mock.mockImplementation((url: string) => {
      if (url === "/api/batches/1/compare/2") {
        return Promise.resolve(jsonResponse(200, compareResult(1, 2)));
      }
      if (url === "/api/batches/1") {
        return Promise.resolve(jsonResponse(200, detail(1, "K-1")));
      }
      if (url === "/api/batches") {
        return Promise.resolve(
          jsonResponse(200, { batches: [summary(1, "K-1"), summary(2, "K-2")] }),
        );
      }
      throw new Error(`unexpected ${url}`);
    });
    render(<App />);
    await screen.findByTestId("history-row-1");
    fireEvent.click(screen.getByTestId("history-row-1"));
    await screen.findByTestId("batch-detail");

    // 参照候选排除当前窑次自身
    const select = screen.getByTestId("compare-reference-select");
    expect(select).not.toHaveTextContent("#1 K-1");
    expect(select).toHaveTextContent("#2 K-2");

    fireEvent.change(select, { target: { value: "2" } });

    await screen.findByTestId("compare-table");
    expect(screen.getByTestId("compare-summary")).toHaveTextContent(
      "共同持续区间为 300 分钟",
    );
    expect(screen.getByTestId("compare-0-temperature-delta")).toHaveTextContent(
      "0",
    );
    expect(screen.getByTestId("compare-1-temperature-delta")).toHaveTextContent(
      "+25",
    );
    expect(screen.getByTestId("compare-1-heatwork-delta")).toHaveTextContent(
      "+375",
    );
    expect(screen.getByTestId("compare-2-elapsed")).toHaveTextContent("60");
    expect(screen.getByTestId("compare-2-heatwork-delta")).toHaveTextContent(
      "+1500",
    );
  });

  it("切换参照立即重算，迟到的旧响应不顶替新结果", async () => {
    const d1 = deferred<Response>();
    const d2 = deferred<Response>();
    mock.mockImplementation((url: string) => {
      if (url === "/api/batches/1/compare/2") return d1.promise;
      if (url === "/api/batches/1/compare/3") return d2.promise;
      if (url === "/api/batches/1") {
        return Promise.resolve(jsonResponse(200, detail(1, "K-1")));
      }
      if (url === "/api/batches") {
        return Promise.resolve(
          jsonResponse(200, {
            batches: [summary(1, "K-1"), summary(2, "K-2"), summary(3, "K-3")],
          }),
        );
      }
      throw new Error(`unexpected ${url}`);
    });
    render(<App />);
    await screen.findByTestId("history-row-1");
    fireEvent.click(screen.getByTestId("history-row-1"));
    await screen.findByTestId("batch-detail");

    const select = screen.getByTestId("compare-reference-select");
    fireEvent.change(select, { target: { value: "2" } });
    // 第一次对比仍在途时切换参照 -> 立即发起新请求
    fireEvent.change(select, { target: { value: "3" } });
    expect(screen.getByTestId("compare-loading")).toBeInTheDocument();

    // 旧参照的响应最后才回来，不得顶替新结果
    d2.resolve(jsonResponse(200, compareResult(1, 3)));
    d1.resolve(jsonResponse(200, compareResult(1, 2)));

    await screen.findByTestId("compare-table");
    expect(screen.getByTestId("compare-summary")).toHaveTextContent("K-3");
    expect(screen.getByTestId("compare-summary")).not.toHaveTextContent(
      "参照 #2",
    );
    expect(screen.queryByTestId("compare-loading")).not.toBeInTheDocument();
  });

  it("对比失败：保留当前详情与已选参照，就地提示且不新增记录", async () => {
    mock.mockImplementation((url: string) => {
      if (url === "/api/batches/1/compare/2") {
        return Promise.resolve(
          jsonResponse(422, {
            detail: {
              reason: "series_invalid",
              message:
                "窑次 2「K-2」第 0 个采样点时刻无法解析（时刻必须为 ISO 8601 字符串），无法参与对比。",
            },
          }),
        );
      }
      if (url === "/api/batches/1") {
        return Promise.resolve(jsonResponse(200, detail(1, "K-1")));
      }
      if (url === "/api/batches") {
        return Promise.resolve(
          jsonResponse(200, { batches: [summary(1, "K-1"), summary(2, "K-2")] }),
        );
      }
      throw new Error(`unexpected ${url}`);
    });
    render(<App />);
    await screen.findByTestId("history-row-1");
    fireEvent.click(screen.getByTestId("history-row-1"));
    await screen.findByTestId("batch-detail");

    fireEvent.change(screen.getByTestId("compare-reference-select"), {
      target: { value: "2" },
    });

    await screen.findByTestId("compare-error");
    expect(screen.getByTestId("compare-error")).toHaveTextContent(
      "无法参与对比",
    );
    // 当前详情、已选参照与历史选择都保留，不出现对比表
    expect(screen.getByTestId("batch-detail")).toBeInTheDocument();
    expect(screen.getByTestId("compare-reference-select")).toHaveValue("2");
    expect(screen.getByTestId("history-row-1")).toHaveClass("selected");
    expect(screen.queryByTestId("compare-table")).not.toBeInTheDocument();
    // 复算入口不受对比失败影响，仍可使用
    expect(screen.getByTestId("recompute-button")).toBeEnabled();
  });

  it("切换到其他窑次详情后，对比选择与结果随之重置", async () => {
    mock.mockImplementation((url: string) => {
      if (url === "/api/batches/1/compare/2") {
        return Promise.resolve(jsonResponse(200, compareResult(1, 2)));
      }
      if (url === "/api/batches/1") {
        return Promise.resolve(jsonResponse(200, detail(1, "K-1")));
      }
      if (url === "/api/batches/2") {
        return Promise.resolve(jsonResponse(200, detail(2, "K-2")));
      }
      if (url === "/api/batches") {
        return Promise.resolve(
          jsonResponse(200, { batches: [summary(1, "K-1"), summary(2, "K-2")] }),
        );
      }
      throw new Error(`unexpected ${url}`);
    });
    render(<App />);
    await screen.findByTestId("history-row-1");
    fireEvent.click(screen.getByTestId("history-row-1"));
    await screen.findByTestId("batch-detail");
    fireEvent.change(screen.getByTestId("compare-reference-select"), {
      target: { value: "2" },
    });
    await screen.findByTestId("compare-table");

    fireEvent.click(screen.getByTestId("history-row-2"));
    await screen.findByText("窑次详情：K-2");
    // 新详情不再展示旧参照与旧对比结果
    expect(screen.getByTestId("compare-reference-select")).toHaveValue("");
    expect(screen.queryByTestId("compare-table")).not.toBeInTheDocument();
  });
});
