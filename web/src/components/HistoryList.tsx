import type { BatchSummary } from "../types";
import { verdictMeta } from "../verdict";

interface Props {
  batches: BatchSummary[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

export function HistoryList({ batches, selectedId, onSelect }: Props) {
  return (
    <section className="card" data-testid="history">
      <h2>历史记录</h2>
      {batches.length === 0 ? (
        <p className="empty" data-testid="history-empty">
          暂无合法提交记录
        </p>
      ) : (
        <table className="history-table" data-testid="history-table">
          <thead>
            <tr>
              <th>窑次</th>
              <th>点数</th>
              <th>计热值（°C·min）</th>
              <th>结论</th>
              <th>提交时间</th>
            </tr>
          </thead>
          <tbody>
            {batches.map((batch) => {
              const meta = verdictMeta(batch.verdict);
              return (
                <tr
                  key={batch.id}
                  data-testid={`history-row-${batch.id}`}
                  className={batch.id === selectedId ? "selected" : ""}
                  onClick={() => onSelect(batch.id)}
                >
                  <td>{batch.name}</td>
                  <td>{batch.point_count}</td>
                  <td>{batch.integral_display}</td>
                  <td>
                    <span className={`tag tag-${meta.tone}`}>{meta.label}</span>
                  </td>
                  <td>{new Date(batch.created_at).toLocaleString()}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
