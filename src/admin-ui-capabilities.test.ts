import { describe, expect, it } from "vitest";

import {
  adminUiCapabilities,
  externalScheduleNotice,
  manualVersionSavedMessage,
  supportsApkVersionEditor,
} from "./admin-ui-capabilities";

describe("admin UI capability gates", () => {
  it("exposes catalog mutations while keeping retention unavailable", () => {
    expect(adminUiCapabilities.catalogMutations).toBe(true);
    expect(adminUiCapabilities.retention).toBe(false);
  });

  it("exposes the single-APK version editor only for Android domains", () => {
    expect(supportsApkVersionEditor("android")).toBe(true);
    expect(supportsApkVersionEditor("Android")).toBe(true);
    expect(supportsApkVersionEditor("windows")).toBe(false);
    expect(supportsApkVersionEditor("PC")).toBe(false);
    expect(supportsApkVersionEditor(undefined)).toBe(false);
  });

  it("reports manual-version probe status without inventing automatic success", () => {
    expect(manualVersionSavedMessage("2.0.0", "未自动探活；请手动执行版本探活"))
      .toContain("未自动探活；请手动执行版本探活");
    expect(manualVersionSavedMessage("2.0.0", null)).toContain("尚未执行自动探活");
    expect(manualVersionSavedMessage("2.0.0", null)).not.toContain("自动探活成功");
  });

  it("states that schedule values need an external trigger with undefined semantics", () => {
    expect(externalScheduleNotice).toContain("只保存计划参数");
    expect(externalScheduleNotice).toContain("外部计划任务");
    expect(externalScheduleNotice).toContain("时区");
    expect(externalScheduleNotice).toContain("漏跑");
    expect(externalScheduleNotice).toContain("采集动作");
  });
});
