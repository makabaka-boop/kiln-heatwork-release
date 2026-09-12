import { expect, test } from "@playwright/test";

/**
 * 真实联调测试：浏览器 -> web(nginx) -> api(FastAPI) -> SQLite。
 * 运行前需启动整套服务（docker compose up，或本地 uvicorn + vite）。
 */

const SAMPLE_POINTS = [
  { time: "2026-09-11T08:00:00Z", temperature: 600 },
  { time: "2026-09-11T10:00:00Z", temperature: 700 },
  { time: "2026-09-11T12:00:00Z", temperature: 700 },
  { time: "2026-09-11T13:00:00Z", temperature: 600 },
];

test.describe("窑炉烧成判定台联调", () => {
  test("合法提交：判定合格并落库，刷新后仍可复查", async ({ page }) => {
    await page.goto("/");

    await page.getByTestId("sample-fill").click();
    await page.getByTestId("name-input").fill(`K-E2E-${Date.now()}`);
    await page.getByTestId("submit-batch").click();

    // 示例曲线积分恰为 21000.0 °C·min -> 合格
    await expect(page.getByTestId("result-verdict")).toHaveText("合格");
    await expect(page.getByTestId("result-integral")).toHaveText(
      "21000.0 °C·min",
    );
    await expect(page.getByTestId("result-integral-raw")).toHaveText("21000");

    // 提交成功后直接展示分段明细：3 段，贡献 6000 / 12000 / 3000
    await expect(page.getByTestId("segments-table")).toBeVisible();
    await expect(page.getByTestId("segment-0-contribution")).toHaveText("6000");
    await expect(page.getByTestId("segment-1-contribution")).toHaveText(
      "12000",
    );
    await expect(page.getByTestId("segment-2-contribution")).toHaveText("3000");

    // 历史记录出现该批次
    const history = page.getByTestId("history-table");
    await expect(history).toBeVisible();
    const name = await page.getByTestId("result-name").textContent();
    const row = history.locator("tr", { hasText: name ?? "" });
    await expect(row).toBeVisible();

    // 刷新后记录仍在，点击可复查原始点与未舍入积分
    await page.reload();
    const rowAfterReload = page
      .getByTestId("history-table")
      .locator("tr", { hasText: name ?? "" });
    await expect(rowAfterReload).toBeVisible();
    await rowAfterReload.click();
    await expect(page.getByTestId("detail-verdict")).toHaveText("合格");
    await expect(page.getByTestId("detail-integral-display")).toHaveText(
      "21000.0 °C·min",
    );
    await expect(page.getByTestId("detail-integral-raw")).toHaveText("21000");
    await expect(page.getByTestId("detail-row-0")).toContainText(
      "2026-09-11T08:00:00Z",
    );
    await expect(page.getByTestId("detail-row-3")).toContainText("600");

    // 历史详情中分段明细按时间顺序呈现
    const detailSegments = page.getByTestId("detail-segments");
    await expect(
      detailSegments.getByTestId("segment-row-0"),
    ).toContainText("2026-09-11T08:00:00Z");
    await expect(
      detailSegments.getByTestId("segment-2-contribution"),
    ).toHaveText("3000");
  });

  test("按当前规则复算：新记录落库并展示来源，刷新后可复查", async ({
    page,
  }) => {
    await page.goto("/");

    await page.getByTestId("sample-fill").click();
    const name = `K-E2E-RECOMPUTE-${Date.now()}`;
    await page.getByTestId("name-input").fill(name);
    await page.getByTestId("submit-batch").click();
    await expect(page.getByTestId("result-verdict")).toHaveText("合格");

    // 打开历史详情，点击「按当前规则复算」
    await page
      .getByTestId("history-table")
      .locator("tr", { hasText: name })
      .first()
      .click();
    await expect(page.getByTestId("batch-detail")).toBeVisible();
    await page.getByTestId("recompute-button").click();

    // 新窑次详情：展示「复算自某窑次」与复算时间
    await expect(page.getByTestId("detail-source")).toContainText("复算自窑次");
    await expect(page.getByTestId("detail-source")).toContainText(name);
    await expect(page.getByTestId("detail-recomputed-at")).toBeVisible();
    // 总积分与分段由当前算法重算：21000.0，分段 6000 / 12000 / 3000
    await expect(page.getByTestId("detail-integral-display")).toHaveText(
      "21000.0 °C·min",
    );
    const detailSegments = page.getByTestId("detail-segments");
    await expect(
      detailSegments.getByTestId("segment-0-contribution"),
    ).toHaveText("6000");
    await expect(
      detailSegments.getByTestId("segment-1-contribution"),
    ).toHaveText("12000");
    await expect(
      detailSegments.getByTestId("segment-2-contribution"),
    ).toHaveText("3000");
    // 历史列表标识「复算自某窑次」
    await expect(page.getByText(`复算自 ${name}`)).toBeVisible();

    // 刷新后复查：最新一条即复算记录，来源关系仍在
    await page.reload();
    await page
      .getByTestId("history-table")
      .locator("tbody tr")
      .first()
      .click();
    await expect(page.getByTestId("detail-source")).toContainText(name);
    await expect(page.getByTestId("detail-integral-display")).toHaveText(
      "21000.0 °C·min",
    );
  });

  test("边界提交：积分恰为 18000.0 判合格", async ({ page }) => {    await page.goto("/");
    await page.getByTestId("name-input").fill(`K-E2E-EDGE-${Date.now()}`);
    // 660°C 恒温 300 min -> (660-600)*300 = 18000.0，恰好落在合格下沿
    await page.getByTestId("json-toggle").click();
    await page.getByTestId("json-input").fill(
      JSON.stringify([
        { time: "2026-09-11T00:00:00Z", temperature: 660 },
        { time: "2026-09-11T05:00:00Z", temperature: 660 },
      ]),
    );
    await page.getByTestId("json-fill").click();
    await page.getByTestId("submit-batch").click();

    await expect(page.getByTestId("result-verdict")).toHaveText("合格");
    await expect(page.getByTestId("result-integral")).toHaveText(
      "18000.0 °C·min",
    );
  });

  test("轨迹对比：选择参照后展示对齐节点差值，切换参照立即重算", async ({
    page,
  }) => {
    // 局部升温偏差曲线：前 60 min 就升到 700°C，之后与示例曲线一致
    const DEVIATED_POINTS = [
      { time: "2026-09-11T08:00:00Z", temperature: 600 },
      { time: "2026-09-11T08:30:00Z", temperature: 650 },
      { time: "2026-09-11T09:00:00Z", temperature: 700 },
      { time: "2026-09-11T10:00:00Z", temperature: 700 },
      { time: "2026-09-11T12:00:00Z", temperature: 700 },
      { time: "2026-09-11T13:00:00Z", temperature: 600 },
    ];
    await page.goto("/");

    // 参照窑次：示例曲线（4 点）
    await page.getByTestId("sample-fill").click();
    const referenceName = `K-E2E-CMP-REF-${Date.now()}`;
    await page.getByTestId("name-input").fill(referenceName);
    await page.getByTestId("submit-batch").click();
    await expect(page.getByTestId("result-verdict")).toHaveText("合格");

    // 当前窑次：局部升温偏差曲线（6 点）
    await page.getByTestId("json-toggle").click();
    await page.getByTestId("json-input").fill(JSON.stringify(DEVIATED_POINTS));
    await page.getByTestId("json-fill").click();
    const currentName = `K-E2E-CMP-CUR-${Date.now()}`;
    await page.getByTestId("name-input").fill(currentName);
    await page.getByTestId("submit-batch").click();
    await expect(page.getByTestId("result-verdict")).toHaveText("合格");

    // 打开当前窑次详情，选择参照窑次
    await page
      .getByTestId("history-table")
      .locator("tr", { hasText: currentName })
      .first()
      .click();
    await expect(page.getByTestId("batch-detail")).toBeVisible();
    const select = page.getByTestId("compare-reference-select");
    const referenceValue = await select
      .locator("option", { hasText: referenceName })
      .getAttribute("value");
    await select.selectOption(referenceValue ?? "");

    // 共同持续区间 300 分钟，对齐节点为双方采样时刻的并集（6 个）
    await expect(page.getByTestId("compare-table")).toBeVisible();
    await expect(page.getByTestId("compare-summary")).toContainText(
      "共同持续区间为 300 分钟",
    );
    await expect(page.getByTestId("compare-summary")).toContainText(
      referenceName,
    );
    // 偏差段温度差为正，回归同一轨迹后为 0；累计计热差保持 +3000
    await expect(page.getByTestId("compare-1-elapsed")).toHaveText("30");
    await expect(page.getByTestId("compare-1-temperature-delta")).toHaveText(
      "+25",
    );
    await expect(page.getByTestId("compare-2-temperature-delta")).toHaveText(
      "+50",
    );
    await expect(page.getByTestId("compare-2-heatwork-delta")).toHaveText(
      "+1500",
    );
    await expect(page.getByTestId("compare-3-temperature-delta")).toHaveText(
      "0",
    );
    await expect(page.getByTestId("compare-5-heatwork-delta")).toHaveText(
      "+3000",
    );

    // 切换参照立即重算：换回空选择后对比结果消失
    await select.selectOption("");
    await expect(page.getByTestId("compare-table")).toHaveCount(0);
  });

  test("非法提交：错误定位到具体采样点，且整次不落库", async ({ page }) => {
    await page.goto("/");
    const before = await page
      .getByTestId("history-table")
      .locator("tbody tr")
      .count()
      .catch(() => 0);

    await page.getByTestId("name-input").fill(`K-E2E-BAD-${Date.now()}`);
    await page.getByTestId("add-row").click();
    // 第 1 点温度超上限，第 2 点时刻倒退
    await page.getByTestId("row-0-time").fill("2026-09-11T08:00:00Z");
    await page.getByTestId("row-0-temperature").fill("620");
    await page.getByTestId("row-1-time").fill("2026-09-11T09:00:00Z");
    await page.getByTestId("row-1-temperature").fill("1500");
    await page.getByTestId("row-2-time").fill("2026-09-11T08:30:00Z");
    await page.getByTestId("row-2-temperature").fill("640");
    await page.getByTestId("submit-batch").click();

    await expect(page.getByTestId("row-1-temperature-error")).toContainText(
      "温度须在 0 至 1400°C 之间",
    );
    await expect(page.getByTestId("row-2-time-error")).toContainText(
      "时刻必须严格递增",
    );
    // 不展示任何判定结果
    await expect(page.getByTestId("result")).toHaveCount(0);

    // 整次不落库：历史记录行数不变
    await page.reload();
    const after = await page
      .getByTestId("history-table")
      .locator("tbody tr")
      .count()
      .catch(() => 0);
    expect(after).toBe(before);
  });
});
