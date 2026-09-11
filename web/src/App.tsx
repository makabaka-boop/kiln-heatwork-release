import { useCallback, useEffect, useState } from "react";
import { fetchBatch, fetchBatches } from "./api";
import { BatchDetailView } from "./components/BatchDetail";
import { BatchForm } from "./components/BatchForm";
import { HistoryList } from "./components/HistoryList";
import { ResultBanner } from "./components/ResultBanner";
import type { BatchDetail, BatchSummary } from "./types";

export default function App() {
  const [batches, setBatches] = useState<BatchSummary[]>([]);
  const [lastCreated, setLastCreated] = useState<BatchSummary | null>(null);
  const [detail, setDetail] = useState<BatchDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setBatches(await fetchBatches());
      setLoadError(null);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "加载历史记录失败");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleCreated = (batch: BatchSummary) => {
    setLastCreated(batch);
    setDetail(null);
    void refresh();
  };

  const handleSelect = async (id: number) => {
    try {
      setDetail(await fetchBatch(id));
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "加载详情失败");
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
      {loadError && (
        <p className="field-error" data-testid="load-error">
          {loadError}
        </p>
      )}
      <main>
        <div className="column">
          <BatchForm onCreated={handleCreated} />
          {lastCreated && <ResultBanner batch={lastCreated} />}
        </div>
        <div className="column">
          <HistoryList
            batches={batches}
            selectedId={detail?.id ?? null}
            onSelect={(id) => void handleSelect(id)}
          />
          {detail && <BatchDetailView detail={detail} />}
        </div>
      </main>
    </div>
  );
}
