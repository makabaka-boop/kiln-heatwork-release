import type { BatchSummary } from "../types";
import { verdictMeta } from "../verdict";

export function ResultBanner({ batch }: { batch: BatchSummary }) {
  const meta = verdictMeta(batch.verdict);
  return (
    <section className={`card result result-${meta.tone}`} data-testid="result">
      <h2>判定结果</h2>
      <p className="verdict" data-testid="result-verdict">
        {meta.label}
      </p>
      <p className="integral" data-testid="result-integral">
        {batch.integral_display} °C·min
      </p>
      <p className="hint">{meta.hint}</p>
      <dl className="meta">
        <dt>窑次</dt>
        <dd data-testid="result-name">{batch.name}</dd>
        <dt>未舍入积分</dt>
        <dd data-testid="result-integral-raw">{batch.integral_raw}</dd>
        <dt>采样点数</dt>
        <dd>{batch.point_count}</dd>
      </dl>
    </section>
  );
}
