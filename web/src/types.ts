export type Verdict = "underfired" | "qualified" | "overfired";

export interface SamplePoint {
  time: string;
  temperature: number;
}

/** 单个相邻采样段的计热贡献明细 */
export interface SegmentContribution {
  index: number;
  start_time: string;
  end_time: string;
  /** 段内温度高于 600°C 起点的有效计热分钟数 */
  heating_minutes: number;
  /** 未舍入贡献值（°C·min） */
  contribution: number;
  /** 占总积分的比例（0–1） */
  share: number;
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
  /** 逐段贡献明细；升级前的旧记录可能为 null（无法补算时） */
  segments?: SegmentContribution[] | null;
  /** segments 为 null 时的原因说明 */
  segments_note?: string | null;
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
