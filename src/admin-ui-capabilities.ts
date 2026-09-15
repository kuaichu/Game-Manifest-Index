export const adminUiCapabilities = Object.freeze({
  catalogMutations: true,
  retention: false,
});

export function supportsApkVersionEditor(platform: string | null | undefined): boolean {
  return (platform || "").trim().toLowerCase() === "android";
}

export function manualVersionSavedMessage(version: string, probeError?: string | null): string {
  const message = `新版本 ${version} 已成功录入。`;
  const probeNotice = probeError?.trim();
  return probeNotice
    ? `${message} 探活状态：${probeNotice}`
    : `${message} 尚未执行自动探活，请按需手动探活。`;
}

export const externalScheduleNotice =
  "这里只保存每日采集计划参数；实际触发、时区、漏跑策略及采集动作由外部计划任务决定。";

export const probeScheduleNotice =
  "服务运行时由内置计时器执行探活，覆盖 Android+PC 官方 URL；普通轮跳过 20 小时内已有有效证据的链接，全量轮忽略 TTL；启用或修改配置会启动新的间隔周期（下一周期生效），运行繁忙时顺延，服务停机后合并为一次补跑。";
