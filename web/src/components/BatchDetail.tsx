import type { BatchDetail, BatchSummary, CompareResult } from "../types";
import { verdictMeta } from "../verdict";
import { ComparePanel } from "./ComparePanel";
import { SegmentsTable } from "./SegmentsTable";

interface Props {
  detail: BatchDetail;
  /** 复算请求进行中：按钮禁用，防止重复触发 */
  recomputing: boolean;
  /** 复算失败的原因提示；为 null 时不展示 */
  recomputeError: string | null;
  onRecompute: (id: number) => void;
  /** 历史记录（轨迹对比的参照候选来源） */
  batches: BatchSummary[];
  /** 已选参照窑次 id；未选择为 null */
  referenceId: number | null;
  /** 对比结果；未选择或请求失败时为 null */
  compare: CompareResult | null;
  /** 对比失败的原因提示；为 null 时不展示 */
  compareError: string | null;
  /** 对比请求进行中 */
  compareLoading: boolean;
  /** 切换参照窑次：立即重新对比 */
  onSelectReference: (referenceId: number | null) => void;
}

export function BatchDetailView({
  detail,
  recomputing,
  recomputeError,
  onRecompute,
  batches,
  referenceId,
  compare,
  compareError,
  compareLoading,
  onSelectReference,
}: Props) {
  const meta = verdictMeta(detail.verdict);
  return (
    <section className="card" data-testid="batch-detail">
      <h2>窑次详情：{detail.name}</h2>
      <dl className="meta">
        <dt>结论</dt>
        <dd data-testid="detail-verdict">
          <span className={`tag tag-${meta.tone}`}>{meta.label}</span>
        </dd>
        <dt>展示值</dt>
        <dd data-testid="detail-integral-display">
          {detail.integral_display} °C·min
        </dd>
        <dt>未舍入积分</dt>
        <dd data-testid="detail-integral-raw">{detail.integral_raw}</dd>
        <dt>提交时间</dt>
        <dd>{new Date(detail.created_at).toLocaleString()}</dd>
        {detail.source && (
          <>
            <dt>来源</dt>
            <dd data-testid="detail-source">
              复算自窑次 #{detail.source.id}「{detail.source.name}」（原判定{" "}
              {detail.source.verdict_label}，{detail.source.integral_display}{" "}
              °C·min）
            </dd>
            <dt>复算时间</dt>
            <dd data-testid="detail-recomputed-at">
              {detail.recomputed_at
                ? new Date(detail.recomputed_at).toLocaleString()
                : "—"}
            </dd>
          </>
        )}
      </dl>
      <div className="recompute-actions">
        <button
          type="button"
          onClick={() => onRecompute(detail.id)}
          disabled={recomputing}
          data-testid="recompute-button"
        >
          {recomputing ? "复算中…" : "按当前规则复算"}
        </button>
        {recomputeError && (
          <em className="field-error" data-testid="recompute-error">
            {recomputeError}
          </em>
        )}
      </div>
      <ComparePanel
        currentId={detail.id}
        batches={batches}
        referenceId={referenceId}
        result={compare}
        error={compareError}
        loading={compareLoading}
        onSelectReference={onSelectReference}
      />
      <h3 className="segments-title">分段计热明细</h3>
      <div data-testid="detail-segments">
        <SegmentsTable segments={detail.segments} note={detail.segments_note} />
      </div>
      <h3 className="segments-title">原始采样点</h3>
      <table className="points-table" data-testid="detail-points">
        <thead>
          <tr>
            <th>#</th>
            <th>时刻</th>
            <th>温度（°C）</th>
          </tr>
        </thead>
        <tbody>
          {detail.points.map((point, index) => (
            <tr key={index} data-testid={`detail-row-${index}`}>
              <td className="row-index">{index}</td>
              <td>{point.time}</td>
              <td>{point.temperature}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
