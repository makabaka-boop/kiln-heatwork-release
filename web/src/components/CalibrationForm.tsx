import { useState } from "react";
import { createCalibration, SubmissionError } from "../api";
import {
  calibrationGroupErrors,
  EMPTY_CALIBRATION_ERRORS,
  mapCalibrationErrors,
  type CalibrationFormErrors,
} from "../calibrationErrors";
import type { CalibrationRecord } from "../types";

interface GroupRow {
  setTemperature: string;
  indicator: string;
  standard: string;
}

const MIN_GROUPS = 3;
const MAX_GROUPS = 12;

/** 边界示例：最大绝对误差恰为 2.0°C，允许偏差 2.0 -> 恰好合格 */
const SAMPLE_GROUPS: GroupRow[] = [
  { setTemperature: "100", indicator: "101", standard: "100" },
  { setTemperature: "500", indicator: "502", standard: "500" },
  { setTemperature: "800", indicator: "798", standard: "800" },
  { setTemperature: "1200", indicator: "1201", standard: "1200" },
];

function emptyGroups(): GroupRow[] {
  return [
    { setTemperature: "", indicator: "", standard: "" },
    { setTemperature: "", indicator: "", standard: "" },
    { setTemperature: "", indicator: "", standard: "" },
  ];
}

/** 文本转提交值；无法解析时原样上送，由后端给出精确错误 */
function parseNumber(text: string): unknown {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  const value = Number(trimmed);
  return Number.isNaN(value) ? trimmed : value;
}

interface Props {
  onCreated: (record: CalibrationRecord) => void;
  /** 表单被再次编辑时回调：上一张核验单的结论已失效，由父组件隐藏 */
  onDirty?: () => void;
}

export function CalibrationForm({ onCreated, onDirty }: Props) {
  const [probeId, setProbeId] = useState("");
  const [calibratedAt, setCalibratedAt] = useState("");
  const [tolerance, setTolerance] = useState("");
  const [rows, setRows] = useState<GroupRow[]>(emptyGroups);
  const [errors, setErrors] = useState<CalibrationFormErrors>(
    EMPTY_CALIBRATION_ERRORS,
  );
  const [submitting, setSubmitting] = useState(false);

  const resetErrors = () => setErrors(EMPTY_CALIBRATION_ERRORS);

  const updateRow = (index: number, patch: Partial<GroupRow>) => {
    resetErrors();
    onDirty?.();
    setRows((prev) =>
      prev.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    );
  };

  const addRow = () => {
    resetErrors();
    onDirty?.();
    setRows((prev) =>
      prev.length >= MAX_GROUPS
        ? prev
        : [...prev, { setTemperature: "", indicator: "", standard: "" }],
    );
  };

  const removeRow = (index: number) => {
    resetErrors();
    onDirty?.();
    setRows((prev) =>
      prev.length <= MIN_GROUPS ? prev : prev.filter((_, i) => i !== index),
    );
  };

  const fillSample = () => {
    resetErrors();
    onDirty?.();
    setProbeId("TC-K-2026-0912-01");
    setCalibratedAt("2026-09-12T10:00:00Z");
    setTolerance("2");
    setRows(SAMPLE_GROUPS.map((row) => ({ ...row })));
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    resetErrors();
    setSubmitting(true);
    try {
      const record = await createCalibration({
        probe_id: probeId.trim(),
        calibrated_at: calibratedAt.trim(),
        tolerance: parseNumber(tolerance),
        groups: rows.map((row) => ({
          set_temperature: parseNumber(row.setTemperature),
          indicator_reading: parseNumber(row.indicator),
          standard_reading: parseNumber(row.standard),
        })),
      });
      onCreated(record);
    } catch (error) {
      if (error instanceof SubmissionError) {
        setErrors(mapCalibrationErrors(error.errors));
      } else {
        setErrors({
          global: [error instanceof Error ? error.message : "提交失败"],
          groups: new Map(),
        });
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="card" onSubmit={submit} data-testid="calibration-form">
      <h2>热电偶校准核验</h2>

      <label className="field">
        <span>探头编号</span>
        <input
          data-testid="cal-probe-id"
          value={probeId}
          onChange={(event) => {
            resetErrors();
            onDirty?.();
            setProbeId(event.target.value);
          }}
          placeholder="例如 TC-K-2026-0912-01"
        />
        {errors.probe_id && (
          <em className="field-error" data-testid="cal-probe-id-error">
            {errors.probe_id}
          </em>
        )}
      </label>

      <label className="field">
        <span>校准时间（ISO 8601）</span>
        <input
          data-testid="cal-calibrated-at"
          value={calibratedAt}
          onChange={(event) => {
            resetErrors();
            onDirty?.();
            setCalibratedAt(event.target.value);
          }}
          placeholder="2026-09-12T10:00:00Z"
        />
        {errors.calibrated_at && (
          <em className="field-error" data-testid="cal-calibrated-at-error">
            {errors.calibrated_at}
          </em>
        )}
      </label>

      <label className="field">
        <span>允许偏差（°C，正数）</span>
        <input
          data-testid="cal-tolerance"
          value={tolerance}
          onChange={(event) => {
            resetErrors();
            onDirty?.();
            setTolerance(event.target.value);
          }}
          placeholder="2"
        />
        {errors.tolerance && (
          <em className="field-error" data-testid="cal-tolerance-error">
            {errors.tolerance}
          </em>
        )}
      </label>

      <div className="row-header">
        <h3>校准组（{rows.length} 组，3–12，设定温度递增）</h3>
        <div className="row-actions">
          <button type="button" onClick={fillSample} data-testid="cal-sample">
            填入示例
          </button>
          <button
            type="button"
            onClick={addRow}
            disabled={rows.length >= MAX_GROUPS}
            data-testid="cal-add-group"
          >
            添加校准组
          </button>
        </div>
      </div>

      {errors.global.length > 0 && (
        <ul className="form-errors" data-testid="cal-form-errors">
          {errors.global.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      )}

      <table className="points-table calibration-table">
        <thead>
          <tr>
            <th>#</th>
            <th>设定温度（°C）</th>
            <th>仪表读数（°C）</th>
            <th>标准器读数（°C）</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const groupErr = calibrationGroupErrors(errors, index);
            return (
              <tr key={index} data-testid={`cal-group-${index}`}>
                <td className="row-index">{index}</td>
                <td>
                  <input
                    data-testid={`cal-group-${index}-set`}
                    value={row.setTemperature}
                    onChange={(event) =>
                      updateRow(index, { setTemperature: event.target.value })
                    }
                    placeholder="100"
                  />
                  {groupErr.set_temperature && (
                    <em
                      className="field-error"
                      data-testid={`cal-group-${index}-set-error`}
                    >
                      {groupErr.set_temperature}
                    </em>
                  )}
                </td>
                <td>
                  <input
                    data-testid={`cal-group-${index}-indicator`}
                    value={row.indicator}
                    onChange={(event) =>
                      updateRow(index, { indicator: event.target.value })
                    }
                    placeholder="101"
                  />
                  {groupErr.indicator_reading && (
                    <em
                      className="field-error"
                      data-testid={`cal-group-${index}-indicator-error`}
                    >
                      {groupErr.indicator_reading}
                    </em>
                  )}
                </td>
                <td>
                  <input
                    data-testid={`cal-group-${index}-standard`}
                    value={row.standard}
                    onChange={(event) =>
                      updateRow(index, { standard: event.target.value })
                    }
                    placeholder="100"
                  />
                  {groupErr.standard_reading && (
                    <em
                      className="field-error"
                      data-testid={`cal-group-${index}-standard-error`}
                    >
                      {groupErr.standard_reading}
                    </em>
                  )}
                  {groupErr.group && (
                    <em
                      className="field-error"
                      data-testid={`cal-group-${index}-group-error`}
                    >
                      {groupErr.group}
                    </em>
                  )}
                </td>
                <td>
                  <button
                    type="button"
                    onClick={() => removeRow(index)}
                    disabled={rows.length <= MIN_GROUPS}
                    data-testid={`cal-group-${index}-remove`}
                  >
                    删除
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <button
        type="submit"
        className="primary"
        disabled={submitting}
        data-testid="cal-submit"
      >
        {submitting ? "核验中…" : "提交核验单"}
      </button>
    </form>
  );
}
