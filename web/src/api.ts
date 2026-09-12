import type {
  ApiErrorDetail,
  ApiFieldError,
  BatchDetail,
  BatchSummary,
  CalibrationRecord,
  CompareResult,
} from "./types";

const BASE = "/api";

/** 提交被后端判定为非法时抛出，携带全部可定位错误 */
export class SubmissionError extends Error {
  readonly errors: ApiFieldError[];

  constructor(detail: ApiErrorDetail) {
    super(detail.message);
    this.errors = detail.errors;
  }
}

async function parseError(response: Response): Promise<never> {
  const body = (await response.json().catch(() => null)) as {
    detail?: (Partial<ApiErrorDetail> & { reason?: string }) | string;
  } | null;
  // 携带逐点定位错误的 422（提交/复算）或 409（核验单重复）按可定位错误抛出
  if (
    (response.status === 422 || response.status === 409) &&
    typeof body?.detail === "object" &&
    Array.isArray(body.detail.errors)
  ) {
    throw new SubmissionError(body.detail as ApiErrorDetail);
  }
  const message =
    typeof body?.detail === "string"
      ? body.detail
      : body?.detail?.message ?? `请求失败（HTTP ${response.status}）`;
  throw new Error(message);
}

export async function createBatch(payload: {
  name: string;
  points: Array<{ time: string; temperature: unknown }>;
}): Promise<BatchSummary> {
  const response = await fetch(`${BASE}/batches`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) await parseError(response);
  return (await response.json()) as BatchSummary;
}

export async function fetchBatches(): Promise<BatchSummary[]> {
  const response = await fetch(`${BASE}/batches`);
  if (!response.ok) await parseError(response);
  const body = (await response.json()) as { batches: BatchSummary[] };
  return body.batches;
}

export async function fetchBatch(id: number): Promise<BatchDetail> {
  const response = await fetch(`${BASE}/batches/${id}`);
  if (!response.ok) await parseError(response);
  return (await response.json()) as BatchDetail;
}

/** 按当前规则复算历史窑次：成功返回新窑次，失败抛出携带原因的错误 */
export async function recomputeBatch(id: number): Promise<BatchSummary> {
  const response = await fetch(`${BASE}/batches/${id}/recompute`, {
    method: "POST",
  });
  if (!response.ok) await parseError(response);
  return (await response.json()) as BatchSummary;
}

/** 对比两条窑次记录的升温轨迹与累计计热（只读，失败抛出携带原因的错误） */
export async function compareBatches(
  id: number,
  referenceId: number,
): Promise<CompareResult> {
  const response = await fetch(`${BASE}/batches/${id}/compare/${referenceId}`);
  if (!response.ok) await parseError(response);
  return (await response.json()) as CompareResult;
}

/** 提交热电偶校准核验单；成功返回不可变记录，非法/重复抛出携带定位错误的异常 */
export async function createCalibration(payload: {
  probe_id: string;
  calibrated_at: string;
  tolerance: unknown;
  groups: Array<{
    set_temperature: unknown;
    indicator_reading: unknown;
    standard_reading: unknown;
  }>;
}): Promise<CalibrationRecord> {
  const response = await fetch(`${BASE}/calibrations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) await parseError(response);
  return (await response.json()) as CalibrationRecord;
}

/** 按核验单编号读取不可变详情（刷新后据此重新打开） */
export async function fetchCalibration(id: number): Promise<CalibrationRecord> {
  const response = await fetch(`${BASE}/calibrations/${id}`);
  if (!response.ok) await parseError(response);
  return (await response.json()) as CalibrationRecord;
}
