import { useCallback, useEffect, useRef, useState } from "react";
import { compareBatches, fetchBatch, fetchBatches, recomputeBatch } from "./api";
import { BatchDetailView } from "./components/BatchDetail";
import { BatchForm } from "./components/BatchForm";
import { HistoryList } from "./components/HistoryList";
import { ResultBanner } from "./components/ResultBanner";
import type { BatchDetail, BatchSummary, CompareResult } from "./types";

export default function App() {
  const [batches, setBatches] = useState<BatchSummary[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const [lastCreated, setLastCreated] = useState<BatchSummary | null>(null);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<BatchDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [recomputing, setRecomputing] = useState(false);
  const [recomputeError, setRecomputeError] = useState<string | null>(null);
  const [referenceId, setReferenceId] = useState<number | null>(null);
  const [compare, setCompare] = useState<CompareResult | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);
  /** 单调递增的详情请求序号，只接受最后一次选择的响应，杜绝乱序覆盖 */
  const detailRequestSeq = useRef(0);
  /** 对比请求序号：切换参照时作废旧请求，只接受最近一次的结果 */
  const compareRequestSeq = useRef(0);

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

  /** 轨迹对比状态随详情一起作废：新详情不再展示旧参照与旧结果 */
  const resetCompare = () => {
    compareRequestSeq.current += 1;
    setReferenceId(null);
    setCompare(null);
    setCompareError(null);
    setCompareLoading(false);
  };

  const handleCreated = (batch: BatchSummary) => {
    setLastCreated(batch);
    // 新窑次提交后，旧详情与其在途请求全部作废
    detailRequestSeq.current += 1;
    setSelectedId(null);
    setDetail(null);
    setDetailLoading(false);
    setDetailError(null);
    setRecomputeError(null);
    resetCompare();
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
    setRecomputeError(null);
    resetCompare();
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

  /**
   * 按当前规则复算：成功则刷新列表并打开新窑次详情（展示来源关系）；
   * 失败则停留在原详情，仅显示原因提示，不新增记录也不清除当前选择。
   * 复算在途期间用户改选其他窑次的，迟到的结果不强制跳转：
   * 新记录照常入列，页面保持最后选择的窑次详情。
   */
  const handleRecompute = async (id: number) => {
    const seqAtStart = detailRequestSeq.current;
    setRecomputing(true);
    setRecomputeError(null);
    try {
      const created = await recomputeBatch(id);
      await refresh();
      if (detailRequestSeq.current !== seqAtStart) return; // 已改选其他窑次
      void handleSelect(created.id);
    } catch (error) {
      if (detailRequestSeq.current !== seqAtStart) return; // 已改选其他窑次
      setRecomputeError(error instanceof Error ? error.message : "复算失败");
    } finally {
      setRecomputing(false);
    }
  };

  /**
   * 选择/切换参照窑次：立即请求两条记录的对比结果。
   * 失败时保留当前详情与已选参照，仅在对比区域就地提示。
   */
  const handleSelectReference = async (nextReferenceId: number | null) => {
    const seq = compareRequestSeq.current + 1;
    compareRequestSeq.current = seq;
    setReferenceId(nextReferenceId);
    setCompare(null);
    setCompareError(null);
    if (nextReferenceId === null || detail === null) {
      setCompareLoading(false);
      return;
    }
    setCompareLoading(true);
    try {
      const result = await compareBatches(detail.id, nextReferenceId);
      if (compareRequestSeq.current !== seq) return; // 已被更新的参照取代
      setCompare(result);
    } catch (error) {
      if (compareRequestSeq.current !== seq) return;
      setCompareError(error instanceof Error ? error.message : "对比失败");
    } finally {
      if (compareRequestSeq.current === seq) setCompareLoading(false);
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
          {detail && (
            <BatchDetailView
              detail={detail}
              recomputing={recomputing}
              recomputeError={recomputeError}
              onRecompute={(id) => void handleRecompute(id)}
              batches={batches}
              referenceId={referenceId}
              compare={compare}
              compareError={compareError}
              compareLoading={compareLoading}
              onSelectReference={(id) => void handleSelectReference(id)}
            />
          )}
        </div>
      </main>
    </div>
  );
}
