export const adminUiCapabilities = Object.freeze({
  catalogMutations: false,
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
  "这里只保存计划参数；服务不会启动内置计时器，实际触发、时区、漏跑策略及采集动作由外部计划任务决定。";
