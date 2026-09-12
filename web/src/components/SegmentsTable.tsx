import type { SegmentContribution } from "../types";

interface Props {
  segments?: SegmentContribution[] | null;
  note?: string | null;
}

/** 有效计热分钟数：整数直显，否则保留两位小数 */
function formatMinutes(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

/** 占比：0–1 比例格式化为一位小数的百分比 */
function formatShare(share: number): string {
  return `${(share * 100).toFixed(1)}%`;
}

/**
 * 逐相邻采样段的计热贡献明细表。
 * 段按时间顺序呈现；低于 600°C 起点的零贡献段同样保留展示。
 * 升级前的旧记录无法补算明细时，展示后端给出的原因说明。
 */
export function SegmentsTable({ segments, note }: Props) {
  if (segments == null) {
    return (
      <p className="segments-note" data-testid="segments-note">
        {note ?? "本次记录没有分段计热明细。"}
      </p>
    );
  }
  return (
    <table
      className="points-table segments-table"
      data-testid="segments-table"
    >
      <thead>
        <tr>
          <th>段</th>
          <th>起始时刻</th>
          <th>结束时刻</th>
          <th>有效计热（min）</th>
          <th>贡献（°C·min）</th>
          <th>占比</th>
        </tr>
      </thead>
      <tbody>
        {segments.map((segment) => (
          <tr
            key={segment.index}
            data-testid={`segment-row-${segment.index}`}
            className={
              segment.contribution === 0 ? "segment-zero" : undefined
            }
          >
            <td className="row-index">{segment.index}</td>
            <td>{segment.start_time}</td>
            <td>{segment.end_time}</td>
            <td data-testid={`segment-${segment.index}-minutes`}>
              {formatMinutes(segment.heating_minutes)}
            </td>
            <td data-testid={`segment-${segment.index}-contribution`}>
              {segment.contribution}
            </td>
            <td>{formatShare(segment.share)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
