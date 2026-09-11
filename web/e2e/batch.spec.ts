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
  });

  test("边界提交：积分恰为 18000.0 判合格", async ({ page }) => {
    await page.goto("/");
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
