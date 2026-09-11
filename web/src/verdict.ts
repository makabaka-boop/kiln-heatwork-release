import type { Verdict } from "./types";

export interface VerdictMeta {
  label: string;
  tone: "warn" | "ok" | "bad";
  hint: string;
}

export const VERDICT_META: Record<Verdict, VerdictMeta> = {
  underfired: {
    label: "欠烧",
    tone: "warn",
    hint: "计热值低于 18000.0 °C·min，烧成不足",
  },
  qualified: {
    label: "合格",
    tone: "ok",
    hint: "计热值处于 18000.0 至 24000.0 °C·min（含两端）",
  },
  overfired: {
    label: "过烧",
    tone: "bad",
    hint: "计热值高于 24000.0 °C·min，烧成过度",
  },
};

export function verdictMeta(verdict: Verdict): VerdictMeta {
  return VERDICT_META[verdict];
}
