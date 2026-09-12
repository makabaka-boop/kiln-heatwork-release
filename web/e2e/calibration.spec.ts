import { expect, test } from "@playwright/test";

/**
 * 热电偶校准核验真实联调：浏览器 -> web(nginx) -> api(FastAPI) -> SQLite。
 */

test.describe("热电偶校准核验联调", () => {
  test("边界合格单提交后展示判定依据，刷新后按编号重新打开", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByTestId("tab-calibration").click();
    await expect(page.getByTestId("calibration-form")).toBeVisible();

    await page.getByTestId("cal-sample").click();
    // 唯一探头编号，保证联调可重复执行（同探头+同校准时间重复会被拦截）
    await page.getByTestId("cal-probe-id").fill(`TC-E2E-EDGE-${Date.now()}`);
    // 示例误差 +1/+2/-2/-1，允许偏差 2：最大绝对误差恰为 2 -> 边界合格
    await page.getByTestId("cal-submit").click();

    const detail = page.getByTestId("calibration-detail");
    await expect(detail).toBeVisible();
    await expect(page.getByTestId("cal-verdict")).toHaveText("合格");
    await expect(page.getByTestId("cal-max-abs-error")).toHaveText("2 °C");
    await expect(page.getByTestId("cal-tolerance-value")).toHaveText("±2 °C");
    await expect(page.getByTestId("cal-group-1-error-value")).toHaveText("+2");
    await expect(page.getByTestId("cal-group-2-error-value")).toHaveText("-2");
    await expect(page.getByTestId("cal-immutable-note")).toContainText("≤");

    // 记录编号：刷新后凭编号重新打开（闭环证据）
    const id = await page.getByTestId("cal-lookup-input").inputValue();
    expect(id).toMatch(/^\d+$/);
    const probeId = await page
      .getByTestId("cal-probe-id-value")
      .textContent();

    await page.reload();
    await page.getByTestId("tab-calibration").click();
    // 刷新后详情不在，需要按编号打开
    await expect(page.getByTestId("calibration-detail")).toHaveCount(0);
    await page.getByTestId("cal-lookup-input").fill(id);
    await page.getByTestId("cal-lookup-button").click();

    const reopened = page.getByTestId("calibration-detail");
    await expect(reopened).toBeVisible();
    await expect(page.getByTestId("cal-verdict")).toHaveText("合格");
    await expect(page.getByTestId("cal-probe-id-value")).toHaveText(
      probeId ?? "",
    );
    await expect(page.getByTestId("cal-group-1-error-value")).toHaveText("+2");
  });

  test("单点超差：判不合格并在该行标注超差", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("tab-calibration").click();
    await page.getByTestId("cal-sample").click();
    // 唯一探头编号，避免与其他用例的同探头+同校准时间落库记录冲突
    await page.getByTestId("cal-probe-id").fill(`TC-E2E-OVER-${Date.now()}`);
    // 把第 2 组仪表读数改成比标准器高 3°C（800 -> 803），超过允许偏差 2
    await page.getByTestId("cal-group-2-indicator").fill("803");
    await page.getByTestId("cal-submit").click();

    await expect(page.getByTestId("cal-verdict")).toHaveText("不合格");
    await expect(page.getByTestId("cal-max-abs-error")).toHaveText("3 °C");
    const exceededRow = page.getByTestId("cal-group-row-2");
    await expect(exceededRow).toHaveClass(/cal-exceeded/);
    await expect(page.getByTestId("cal-group-2-error-value")).toContainText(
      "+3",
    );
    await expect(page.getByTestId("cal-group-2-error-value")).toContainText(
      "超差",
    );
  });

  test("非法输入与重复提交被拦截：错误定位到输入处且不产生可打开记录", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByTestId("tab-calibration").click();

    // 唯一探头编号，先记录一次合法提交得到编号 N
    const unique = `TC-E2E-${Date.now()}`;
    await page.getByTestId("cal-probe-id").fill(unique);
    await page.getByTestId("cal-calibrated-at").fill("2026-09-12T10:00:00Z");
    await page.getByTestId("cal-tolerance").fill("2");
    await page.getByTestId("cal-group-0-set").fill("100");
    await page.getByTestId("cal-group-0-indicator").fill("101");
    await page.getByTestId("cal-group-0-standard").fill("100");
    await page.getByTestId("cal-group-1-set").fill("500");
    await page.getByTestId("cal-group-1-indicator").fill("502");
    await page.getByTestId("cal-group-1-standard").fill("500");
    await page.getByTestId("cal-group-2-set").fill("1000");
    await page.getByTestId("cal-group-2-indicator").fill("998");
    await page.getByTestId("cal-group-2-standard").fill("1000");
    await page.getByTestId("cal-submit").click();
    await expect(page.getByTestId("cal-verdict")).toHaveText("合格");
    const createdId = await page.getByTestId("cal-lookup-input").inputValue();

    // 非法输入：非正允许偏差 + 读数越界 + 非递增设定温度，错误定位到输入处
    await page.getByTestId("cal-probe-id").fill(`TC-E2E-BAD-${Date.now()}`);
    await page.getByTestId("cal-tolerance").fill("0");
    await page.getByTestId("cal-group-0-indicator").fill("1500");
    await page.getByTestId("cal-group-1-set").fill("100"); // 与第 0 组设定温度相同
    await page.getByTestId("cal-submit").click();
    await expect(page.getByTestId("cal-tolerance-error")).toContainText(
      "正数",
    );
    await expect(page.getByTestId("cal-group-0-indicator-error")).toContainText(
      "0 至 1400",
    );
    await expect(page.getByTestId("cal-group-1-set-error")).toContainText(
      "严格递增",
    );
    // 非法提交不打开新详情（仍显示上一张）
    await expect(page.getByTestId("cal-lookup-input")).toHaveValue(createdId);

    // 重复提交：同探头编号与校准时间
    await page.getByTestId("cal-probe-id").fill(unique);
    await page.getByTestId("cal-calibrated-at").fill("2026-09-12T10:00:00Z");
    await page.getByTestId("cal-tolerance").fill("2");
    await page.getByTestId("cal-group-0-set").fill("100");
    await page.getByTestId("cal-group-0-indicator").fill("100");
    await page.getByTestId("cal-group-0-standard").fill("100");
    await page.getByTestId("cal-group-1-set").fill("500");
    await page.getByTestId("cal-group-1-indicator").fill("500");
    await page.getByTestId("cal-group-1-standard").fill("500");
    await page.getByTestId("cal-group-2-set").fill("1000");
    await page.getByTestId("cal-group-2-indicator").fill("1000");
    await page.getByTestId("cal-group-2-standard").fill("1000");
    await page.getByTestId("cal-submit").click();
    await expect(page.getByTestId("cal-probe-id-error")).toContainText(
      "不能重复提交",
    );

    // 重复与非法均未新增：不存在的大编号打不开（记录仍停留在 createdId）
    await page.getByTestId("cal-lookup-input").fill("99999999");
    await page.getByTestId("cal-lookup-button").click();
    await expect(page.getByTestId("cal-lookup-error")).toContainText("不存在");

    // 已创建的记录仍可按编号重新打开，数据未被失败尝试污染
    await page.getByTestId("cal-lookup-input").fill(createdId);
    await page.getByTestId("cal-lookup-button").click();
    const reopened = page.getByTestId("calibration-detail");
    await expect(reopened).toBeVisible();
    await expect(page.getByTestId("cal-probe-id-value")).toHaveText(unique);
    await expect(page.getByTestId("cal-verdict")).toHaveText("合格");
  });
});
