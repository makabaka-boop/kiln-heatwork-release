import type { BatchSummary, CompareResult } from "../types";

interface Props {
  /** 当前详情窑次 id（从参照候选中排除） */
  currentId: number;
  /** 历史记录（参照候选来源） */
  batches: BatchSummary[];
  /** 已选参照窑次 id；未选择为 null（失败时也保留选择） */
  referenceId: number | null;
  /** 对比结果；未选择或请求失败时为 null */
  result: CompareResult | null;
  /** 对比失败的原因提示；为 null 时不展示 */
  error: string | null;
  /** 对比请求进行中 */
  loading: boolean;
  /** 切换参照：立即重新请求对比 */
  onSelectReference: (referenceId: number | null) => void;
}

/** 经过分钟：整数直显，否则保留两位小数 */
function formatMinutes(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

/** 差值：带正负号，整数直显，否则保留两位小数 */
function formatDelta(value: number): string {
  const text = Number.isInteger(value) ? String(value) : value.toFixed(2);
  return value > 0 ? `+${text}` : text;
}

/**
 * 轨迹对比面板：在历史详情中选择另一窑次作为参照，
 * 以各自首个采样时刻对齐经过分钟，在共同持续区间展示
 * 温度差与累计计热差（当前 − 参照）；切换参照立即重算。
 */
export function ComparePanel({
  currentId,
  batches,
  referenceId,
  result,
  error,
  loading,
  onSelectReference,
}: Props) {
  const candidates = batches.filter((batch) => batch.id !== currentId);
  return (
    <div className="compare-panel" data-testid="compare-panel">
      <h3 className="segments-title">轨迹对比</h3>
      <label className="field">
        <span>参照窑次（差值 = 当前 − 参照）</span>
        <select
          data-testid="compare-reference-select"
          value={referenceId === null ? "" : String(referenceId)}
          onChange={(event) =>
            onSelectReference(
              event.target.value === "" ? null : Number(event.target.value),
            )
          }
        >
          <option value="">选择参照窑次…</option>
          {candidates.map((batch) => (
            <option key={batch.id} value={batch.id}>
              #{batch.id} {batch.name}（{batch.verdict_label}，
              {batch.integral_display} °C·min）
            </option>
          ))}
        </select>
      </label>
      {candidates.length === 0 && (
        <p className="empty" data-testid="compare-empty">
          暂无其他窑次可作为参照
        </p>
      )}
      {loading && (
        <p className="compare-status" data-testid="compare-loading">
          对比计算中…
        </p>
      )}
      {error && (
        <em className="field-error" data-testid="compare-error">
          {error}
        </em>
      )}
      {result && (
        <>
          <p className="compare-summary" data-testid="compare-summary">
            当前 #{result.batch.id}「{result.batch.name}」 与参照 #
            {result.reference.id}「{result.reference.name}」 的共同持续区间为{" "}
            {formatMinutes(result.common_minutes)} 分钟
          </p>
          <table
            className="points-table compare-table"
            data-testid="compare-table"
          >
            <thead>
              <tr>
                <th>经过分钟</th>
                <th>温度差（°C）</th>
                <th>累计计热差（°C·min）</th>
              </tr>
            </thead>
            <tbody>
              {result.nodes.map((node, index) => (
                <tr key={index} data-testid={`compare-row-${index}`}>
                  <td data-testid={`compare-${index}-elapsed`}>
                    {formatMinutes(node.elapsed_minutes)}
                  </td>
                  <td data-testid={`compare-${index}-temperature-delta`}>
                    {formatDelta(node.temperature_delta)}
                  </td>
                  <td data-testid={`compare-${index}-heatwork-delta`}>
                    {formatDelta(node.heatwork_delta)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
