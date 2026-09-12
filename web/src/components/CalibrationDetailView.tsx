import { calibrationVerdictMeta } from "../calibrationVerdict";
import type { CalibrationRecord } from "../types";

/** 带符号的误差展示：0 不冠符号，其余保留正负号 */
function formatSigned(value: number): string {
  if (value === 0) return "0";
  return value > 0 ? `+${value}` : `${value}`;
}

interface Props {
  record: CalibrationRecord;
  /** 容器 testid：创建后结果与历史详情复用同一组件 */
  testId: string;
}

/**
 * 校准核验单详情：不可变记录的判定依据——逐组（设定温度 / 仪表读数 /
 * 标准器读数 / 示值误差）与最大绝对误差、允许偏差、合格性结论。
 */
export function CalibrationDetailView({ record, testId }: Props) {
  const meta = calibrationVerdictMeta(record.verdict);
  return (
    <section
      className={`card calibration-detail calibration-${meta.tone}`}
      data-testid={testId}
    >
      <h2>
        校准核验单 {record.id != null && <>#{record.id}</>}：{record.probe_id}
      </h2>
      <p className="verdict-line">
        结论：
        <span className={`tag tag-${meta.tone}`} data-testid="cal-verdict">
          {meta.label}
        </span>
      </p>
      <p className="cal-hint">{meta.hint}</p>
      <dl className="meta">
        <dt>探头编号</dt>
        <dd data-testid="cal-probe-id-value">{record.probe_id}</dd>
        <dt>校准时间</dt>
        <dd data-testid="cal-calibrated-at-value">{record.calibrated_at}</dd>
        <dt>允许偏差</dt>
        <dd data-testid="cal-tolerance-value">±{record.tolerance} °C</dd>
        <dt>最大绝对误差</dt>
        <dd data-testid="cal-max-abs-error">
          {record.max_abs_error} °C
        </dd>
        {record.created_at && (
          <>
            <dt>提交时间</dt>
            <dd>{new Date(record.created_at).toLocaleString()}</dd>
          </>
        )}
      </dl>

      <h3 className="segments-title">判定依据：逐组示值误差</h3>
      <table className="points-table calibration-table" data-testid="cal-groups">
        <thead>
          <tr>
            <th>#</th>
            <th>设定温度（°C）</th>
            <th>仪表读数（°C）</th>
            <th>标准器读数（°C）</th>
            <th>示值误差（°C）</th>
          </tr>
        </thead>
        <tbody>
          {record.groups.map((group) => {
            const exceeded =
              Math.abs(group.indication_error) > record.tolerance;
            return (
              <tr
                key={group.index}
                data-testid={`cal-group-row-${group.index}`}
                className={exceeded ? "cal-exceeded" : undefined}
              >
                <td className="row-index">{group.index}</td>
                <td data-testid={`cal-group-${group.index}-set-value`}>
                  {group.set_temperature}
                </td>
                <td data-testid={`cal-group-${group.index}-indicator-value`}>
                  {group.indicator_reading}
                </td>
                <td data-testid={`cal-group-${group.index}-standard-value`}>
                  {group.standard_reading}
                </td>
                <td data-testid={`cal-group-${group.index}-error-value`}>
                  {formatSigned(group.indication_error)}
                  {exceeded && <span className="cal-overmark"> 超差</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="cal-immutable-note" data-testid="cal-immutable-note">
        核验单提交后为不可变记录：最大绝对误差 {record.max_abs_error}°C
        {record.verdict === "qualified" ? " ≤ " : " > "}允许偏差{" "}
        {record.tolerance}°C，据此判定{meta.label}。
      </p>
    </section>
  );
}
