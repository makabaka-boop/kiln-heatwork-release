import { useCallback, useEffect, useRef, useState } from "react";
import { fetchBatch, fetchBatches } from "./api";
import { BatchDetailView } from "./components/BatchDetail";
import { BatchForm } from "./components/BatchForm";
import { HistoryList } from "./components/HistoryList";
import { ResultBanner } from "./components/ResultBanner";
import type { BatchDetail, BatchSummary } from "./types";

export default function App() {
  const [batches, setBatches] = useState<BatchSummary[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const [lastCreated, setLastCreated] = useState<BatchSummary | null>(null);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<BatchDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  /** 单调递增的详情请求序号，只接受最后一次选择的响应，杜绝乱序覆盖 */
  const detailRequestSeq = useRef(0);

  const refresh = useCallback(async () => {
    try {
      setBatches(await fetchBatches());
      setListError(null);
    } catch (error) {
      setListError(error instanceof Error ? error.message : "加载历史记录失败");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleCreated = (batch: BatchSummary) => {
    setLastCreated(batch);
    // 新窑次提交后，旧详情与其在途请求全部作废
    detailRequestSeq.current += 1;
    setSelectedId(null);
    setDetail(null);
    setDetailLoading(false);
    setDetailError(null);
    void refresh();
  };

  /** 表单被再次编辑时，上一窑次的判定结果已失效，立即隐藏 */
  const handleFormDirty = () => {
    setLastCreated(null);
  };

  const handleSelect = async (id: number) => {
    const seq = detailRequestSeq.current + 1;
    detailRequestSeq.current = seq;
    // 同步反映新选择：高亮立即切换，旧详情/旧失败提示不再停留
    setSelectedId(id);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      const next = await fetchBatch(id);
      if (detailRequestSeq.current !== seq) return; // 已被更新的选择取代
      setDetail(next);
      setDetailError(null);
    } catch (error) {
      if (detailRequestSeq.current !== seq) return;
      setDetailError(error instanceof Error ? error.message : "加载详情失败");
    } finally {
      if (detailRequestSeq.current === seq) setDetailLoading(false);
    }
  };

  return (
    <div className="page">
      <header>
        <h1>窑炉烧成判定台</h1>
        <p>
          只累计高于 600°C 的计热值；低于 18000.0 °C·min 判欠烧，
          18000.0–24000.0（含两端）判合格，高于 24000.0 判过烧。
        </p>
      </header>
      {listError && (
        <p className="field-error" data-testid="load-error">
          {listError}
        </p>
      )}
      <main>
        <div className="column">
          <BatchForm onCreated={handleCreated} onDirty={handleFormDirty} />
          {lastCreated && <ResultBanner batch={lastCreated} />}
        </div>
        <div className="column">
          <HistoryList
            batches={batches}
            selectedId={selectedId}
            onSelect={(id) => void handleSelect(id)}
          />
          {detailLoading && (
            <p className="card detail-status" data-testid="detail-loading">
              窑次详情加载中…
            </p>
          )}
          {detailError && (
            <p className="field-error card detail-status" data-testid="detail-error">
              {detailError}
            </p>
          )}
          {detail && <BatchDetailView detail={detail} />}
        </div>
      </main>
    </div>
  );
}
