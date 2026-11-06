"use client";
import { ParityScatter } from "./charts";
import type { CalBin } from "@/lib/types";

/** Predicted probability (x) vs observed frequency (y). Points on the dashed diagonal are calibrated. */
export function CalibrationChart({ bins, label = "Probability bins" }: { bins: CalBin[]; label?: string }) {
  return (
    <ParityScatter
      domain={[0, 1]} xLabel="predicted" yLabel="observed" primaryLabel={label}
      primary={bins.map((b) => ({
        x: b.mean_pred, y: b.obs_rate, label: `Bin ${b.bin}`,
        detail: `predicted ${(b.mean_pred * 100).toFixed(1)}% · observed ${(b.obs_rate * 100).toFixed(1)}% · n=${b.n.toLocaleString("en-US")}`,
      }))}
    />
  );
}
