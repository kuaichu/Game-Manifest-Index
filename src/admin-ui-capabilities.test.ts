import { describe, expect, it } from "vitest";

import {
  adminUiCapabilities,
  externalScheduleNotice,
  manualVersionSavedMessage,
  probeScheduleNotice,
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

  it("keeps the daily collection schedule explicitly external", () => {
    expect(externalScheduleNotice).toContain("只保存每日采集计划参数");
    expect(externalScheduleNotice).toContain("外部计划任务");
    expect(externalScheduleNotice).toContain("时区");
    expect(externalScheduleNotice).toContain("漏跑");
    expect(externalScheduleNotice).toContain("采集动作");
    expect(externalScheduleNotice).not.toContain("内置计时器");
  });

  it("describes the built-in probe timer behavior", () => {
    expect(probeScheduleNotice).toContain("服务运行时由内置计时器先从官方来源采集新 URL");
    expect(probeScheduleNotice).toContain("Android+PC 新发现或上次探活可用的官方与历史 URL");
    expect(probeScheduleNotice).toContain("失效、未判定、镜像和来源未知链接不再自动探活");
    expect(probeScheduleNotice).toContain("证据过期提示只对仍在定时轮换的 URL 显示");
    expect(probeScheduleNotice).toContain("普通轮跳过 20 小时内已有有效证据");
    expect(probeScheduleNotice).toContain("全量轮忽略 TTL");
    expect(probeScheduleNotice).toContain("下一周期生效");
    expect(probeScheduleNotice).toContain("运行繁忙时顺延");
    expect(probeScheduleNotice).toContain("合并为一次补跑");
  });
});
