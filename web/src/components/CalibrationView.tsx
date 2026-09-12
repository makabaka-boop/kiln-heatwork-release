import { useRef, useState } from "react";
import { fetchCalibration } from "../api";
import { CalibrationDetailView } from "./CalibrationDetailView";
import { CalibrationForm } from "./CalibrationForm";
import type { CalibrationRecord } from "../types";

/**
 * 热电偶校准核验台：左侧录入核验单，右侧按核验单编号重新打开不可变详情。
 * 提交成功后转入详情展示判定依据；刷新后可凭编号（详情中显著标注）重新打开。
 */
export function CalibrationView() {
  const [record, setRecord] = useState<CalibrationRecord | null>(null);
  const [lookupId, setLookupId] = useState("");
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  /** 单调递增的查询序号，只接受最后一次查询的响应 */
  const requestSeq = useRef(0);

  const openRecord = async (id: number) => {
    const seq = requestSeq.current + 1;
    requestSeq.current = seq;
    setRecord(null);
    setLookupError(null);
    setLoading(true);
    try {
      const next = await fetchCalibration(id);
      if (requestSeq.current !== seq) return;
      setRecord(next);
      setLookupId(String(id));
    } catch (error) {
      if (requestSeq.current !== seq) return;
      setLookupError(
        error instanceof Error ? error.message : "打开核验单失败",
      );
    } finally {
      if (requestSeq.current === seq) setLoading(false);
    }
  };

  const handleLookup = async (event: React.FormEvent) => {
    event.preventDefault();
    const id = Number(lookupId.trim());
    if (!Number.isInteger(id) || id <= 0) {
      setLookupError("请输入核验单编号（正整数）");
      return;
    }
    await openRecord(id);
  };

  return (
    <main>
      <div className="column">
        <CalibrationForm
          onCreated={(created) => {
            // 提交成功：作废旧查询，转入详情展示判定依据
            requestSeq.current += 1;
            setLoading(false);
            setLookupError(null);
            setRecord(created);
            setLookupId(created.id != null ? String(created.id) : "");
          }}
          onDirty={() => {
            // 再次编辑时上一张的结论已与当前输入不符，立即隐藏
            requestSeq.current += 1;
            setRecord(null);
            setLoading(false);
            setLookupError(null);
          }}
        />
      </div>
      <div className="column">
        <form className="card" onSubmit={handleLookup} data-testid="cal-lookup">
          <h2>按编号打开核验单</h2>
          <label className="field">
            <span>核验单编号（刷新后可凭此重新打开）</span>
            <input
              data-testid="cal-lookup-input"
              value={lookupId}
              onChange={(event) => setLookupId(event.target.value)}
              placeholder="例如 1"
              inputMode="numeric"
            />
          </label>
          <button type="submit" data-testid="cal-lookup-button">
            打开
          </button>
          {loading && (
            <p className="compare-status" data-testid="cal-lookup-loading">
              核验单加载中…
            </p>
          )}
          {lookupError && (
            <em className="field-error" data-testid="cal-lookup-error">
              {lookupError}
            </em>
          )}
        </form>
        {record && (
          <CalibrationDetailView
            record={record}
            testId="calibration-detail"
          />
        )}
      </div>
    </main>
  );
}
