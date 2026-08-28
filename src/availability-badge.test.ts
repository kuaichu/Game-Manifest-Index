import { createApp } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import AvailabilityBadge from "./components/AvailabilityBadge.vue";
import type { AvailabilityCurrent, EvidenceStatus } from "./types";


function render(
  status: EvidenceStatus,
  state: AvailabilityCurrent["state"] = "unknown",
  overrides: Partial<AvailabilityCurrent> = {},
): HTMLElement {
  const root = document.createElement("div");
  document.body.appendChild(root);
  const value = status === "no_evidence" ? null : {
    state,
    reason: status === "expired" ? "expired" : "not_probed",
    confidence: "medium",
    retained: false,
    checked_at: "2026-07-11T00:00:00Z",
    source_kind: "live_probe",
    source_confidence: "medium",
    observed_at: "2026-07-11T00:00:00Z",
    expires_at: status === "expired" ? "2023-11-14T22:13:20Z" : null,
    evidence_status: status,
    ...overrides,
  } satisfies AvailabilityCurrent;
  createApp(AvailabilityBadge, { value }).mount(root);
  return root;
}


describe("AvailabilityBadge evidence freshness", () => {
  afterEach(() => { document.body.innerHTML = ""; });

  it.each([
    ["verified", "available", "可用"],
    ["stale", "unknown", "证据已陈旧"],
    ["expired", "unknown", "签名已过期"],
    ["unverified", "unknown", "未验证"],
    ["no_evidence", "unknown", "无证据"],
  ] as Array<[EvidenceStatus, AvailabilityCurrent["state"], string]>) (
    "renders %s distinctly",
    (status, state, label) => {
      const root = render(status, state);
      expect(root.textContent).toContain(label);
      expect(root.querySelector(".availability")?.getAttribute("data-evidence-status")).toBe(status);
    },
  );

  it("distinguishes a failed live probe from a URL that was never probed", () => {
    const root = render("verified", "unknown", { reason: "probe_failed" });
    expect(root.textContent).toContain("探测失败");
  });
});
