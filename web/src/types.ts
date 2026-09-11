export type Verdict = "underfired" | "qualified" | "overfired";

export interface SamplePoint {
  time: string;
  temperature: number;
}

export interface BatchSummary {
  id: number;
  name: string;
  point_count: number;
  integral_raw: number;
  integral_display: string;
  verdict: Verdict;
  verdict_label: string;
  created_at: string;
}

export interface BatchDetail extends BatchSummary {
  points: SamplePoint[];
}

/** 后端返回的可定位校验错误 */
export interface ApiFieldError {
  index: number | null;
  field: string;
  message: string;
}

export interface ApiErrorDetail {
  message: string;
  errors: ApiFieldError[];
}
