import type { BatchDetail } from "../types";
import { verdictMeta } from "../verdict";

export function BatchDetailView({ detail }: { detail: BatchDetail }) {
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
      </dl>
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
