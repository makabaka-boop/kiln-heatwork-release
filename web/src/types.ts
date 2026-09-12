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

/** 复算记录响应中携带的来源窑次摘要 */
export interface BatchSourceSummary {
  id: number;
  name: string;
  integral_display: string;
  verdict: Verdict;
  verdict_label: string;
  created_at: string;
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
  /** 复算记录指向的来源窑次 id；普通提交与旧记录为 null */
  source_batch_id?: number | null;
  /** 来源窑次名称（历史列表响应携带） */
  source_name?: string | null;
  /** 复算时间；普通提交与旧记录为 null */
  recomputed_at?: string | null;
  /** 来源窑次摘要（创建/详情响应携带） */
  source?: BatchSourceSummary | null;
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
