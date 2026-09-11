import { useState } from "react";
import { createBatch, SubmissionError } from "../api";
import { EMPTY_ERRORS, mapApiErrors, rowErrors, type FormErrors } from "../errors";
import type { BatchSummary } from "../types";

interface Row {
  time: string;
  temperature: string;
}

const MIN_ROWS = 2;
const MAX_ROWS = 200;

/** README 同款示例：积分恰为 21000.0 °C·min，判合格 */
const SAMPLE_ROWS: Row[] = [
  { time: "2026-09-11T08:00:00Z", temperature: "600" },
  { time: "2026-09-11T10:00:00Z", temperature: "700" },
  { time: "2026-09-11T12:00:00Z", temperature: "700" },
  { time: "2026-09-11T13:00:00Z", temperature: "600" },
];

function emptyRows(): Row[] {
  return [
    { time: "", temperature: "" },
    { time: "", temperature: "" },
  ];
}

/** 把输入框文本转成提交值；无法解析时原样上送，由后端给出精确错误 */
function parseTemperature(text: string): unknown {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  const value = Number(trimmed);
  return Number.isNaN(value) ? trimmed : value;
}

interface Props {
  onCreated: (batch: BatchSummary) => void;
}

export function BatchForm({ onCreated }: Props) {
  const [name, setName] = useState("");
  const [rows, setRows] = useState<Row[]>(emptyRows);
  const [errors, setErrors] = useState<FormErrors>(EMPTY_ERRORS);
  const [submitting, setSubmitting] = useState(false);
  const [jsonText, setJsonText] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);

  const resetErrors = () => setErrors(EMPTY_ERRORS);

  const updateRow = (index: number, patch: Partial<Row>) => {
    resetErrors();
    setRows((prev) =>
      prev.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    );
  };

  const addRow = () => {
    resetErrors();
    setRows((prev) =>
      prev.length >= MAX_ROWS ? prev : [...prev, { time: "", temperature: "" }],
    );
  };

  const removeRow = (index: number) => {
    resetErrors();
    setRows((prev) =>
      prev.length <= MIN_ROWS ? prev : prev.filter((_, i) => i !== index),
    );
  };

  const fillSample = () => {
    resetErrors();
    setJsonError(null);
    setName("K-2026-0911-A");
    setRows(SAMPLE_ROWS.map((row) => ({ ...row })));
  };

  const fillFromJson = () => {
    resetErrors();
    setJsonError(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(jsonText);
    } catch {
      setJsonError("JSON 解析失败：请检查格式");
      return;
    }
    if (!Array.isArray(parsed)) {
      setJsonError("JSON 须为采样点数组");
      return;
    }
    if (parsed.length < MIN_ROWS || parsed.length > MAX_ROWS) {
      setJsonError(`采样点数量须在 ${MIN_ROWS} 至 ${MAX_ROWS} 个之间`);
      return;
    }
    const next: Row[] = [];
    for (let i = 0; i < parsed.length; i += 1) {
      const item = parsed[i] as { time?: unknown; temperature?: unknown };
      if (item === null || typeof item !== "object") {
        setJsonError(`第 ${i} 个采样点不是 JSON 对象`);
        return;
      }
      next.push({
        time: typeof item.time === "string" ? item.time : String(item.time ?? ""),
        temperature:
          item.temperature === undefined || item.temperature === null
            ? ""
            : String(item.temperature),
      });
    }
    setRows(next);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    resetErrors();
    setSubmitting(true);
    try {
      const batch = await createBatch({
        name,
        points: rows.map((row) => ({
          time: row.time.trim(),
          temperature: parseTemperature(row.temperature),
        })),
      });
      onCreated(batch);
    } catch (error) {
      if (error instanceof SubmissionError) {
        setErrors(mapApiErrors(error.errors));
      } else {
        setErrors({
          global: [error instanceof Error ? error.message : "提交失败"],
          rows: new Map(),
        });
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="card" onSubmit={submit} data-testid="batch-form">
      <h2>提交窑次</h2>

      <label className="field">
        <span>窑次名称</span>
        <input
          data-testid="name-input"
          value={name}
          onChange={(event) => {
            resetErrors();
            setName(event.target.value);
          }}
          placeholder="例如 K-2026-0911-A"
        />
        {errors.name && (
          <em className="field-error" data-testid="name-error">
            {errors.name}
          </em>
        )}
      </label>

      <div className="row-header">
        <h3>采样点（{rows.length} 个，2–200）</h3>
        <div className="row-actions">
          <button type="button" onClick={fillSample} data-testid="sample-fill">
            填入示例
          </button>
          <button
            type="button"
            onClick={addRow}
            disabled={rows.length >= MAX_ROWS}
            data-testid="add-row"
          >
            添加采样点
          </button>
        </div>
      </div>

      {errors.global.length > 0 && (
        <ul className="form-errors" data-testid="form-errors">
          {errors.global.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      )}

      <table className="points-table">
        <thead>
          <tr>
            <th>#</th>
            <th>时刻（ISO 8601）</th>
            <th>温度（°C）</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const rowErr = rowErrors(errors, index);
            return (
              <tr key={index} data-testid={`row-${index}`}>
                <td className="row-index">{index}</td>
                <td>
                  <input
                    data-testid={`row-${index}-time`}
                    value={row.time}
                    onChange={(event) =>
                      updateRow(index, { time: event.target.value })
                    }
                    placeholder="2026-09-11T08:00:00Z"
                  />
                  {rowErr.time && (
                    <em
                      className="field-error"
                      data-testid={`row-${index}-time-error`}
                    >
                      {rowErr.time}
                    </em>
                  )}
                  {rowErr.point && (
                    <em
                      className="field-error"
                      data-testid={`row-${index}-point-error`}
                    >
                      {rowErr.point}
                    </em>
                  )}
                </td>
                <td>
                  <input
                    data-testid={`row-${index}-temperature`}
                    value={row.temperature}
                    onChange={(event) =>
                      updateRow(index, { temperature: event.target.value })
                    }
                    placeholder="650"
                  />
                  {rowErr.temperature && (
                    <em
                      className="field-error"
                      data-testid={`row-${index}-temperature-error`}
                    >
                      {rowErr.temperature}
                    </em>
                  )}
                </td>
                <td>
                  <button
                    type="button"
                    onClick={() => removeRow(index)}
                    disabled={rows.length <= MIN_ROWS}
                    data-testid={`row-${index}-remove`}
                  >
                    删除
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <details className="json-fill">
        <summary data-testid="json-toggle">从控制器导出的 JSON 填充</summary>
        <textarea
          data-testid="json-input"
          value={jsonText}
          onChange={(event) => setJsonText(event.target.value)}
          placeholder='[{"time":"2026-09-11T08:00:00Z","temperature":600}, …]'
          rows={4}
        />
        <button type="button" onClick={fillFromJson} data-testid="json-fill">
          解析并填充表单
        </button>
        {jsonError && (
          <em className="field-error" data-testid="json-error">
            {jsonError}
          </em>
        )}
      </details>

      <button
        type="submit"
        className="primary"
        disabled={submitting}
        data-testid="submit-batch"
      >
        {submitting ? "判定中…" : "提交判定"}
      </button>
    </form>
  );
}
