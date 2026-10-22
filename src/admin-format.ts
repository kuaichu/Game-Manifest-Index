const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB"] as const;

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return "—";
  if (bytes === 0) return "0 B";
  const k = 1024;
  const index = Math.min(
    Math.floor(Math.log(bytes) / Math.log(k)),
    BYTE_UNITS.length - 1,
  );
  return `${(bytes / Math.pow(k, index)).toFixed(2)} ${BYTE_UNITS[index]}`;
}

export function formatSyncTime(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function getFileTimeSourceDescription(timeStr: string, rawUrl: string): string {
  if (!timeStr?.trim()) return "留空（保存后由后端自动识别）";
  const cleanTime = timeStr.trim();
  const cleanUrl = rawUrl || "";

  // 1. URL 中带完整时间戳，例如 20260803155301
  const timestampMatch = cleanUrl.match(/(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})/);
  if (timestampMatch) {
    const compactTimestamp = timestampMatch[0];
    const compactTime = cleanTime.replace(/[-:T Z+]/g, "");
    if (compactTime.startsWith(compactTimestamp.slice(0, 8))) {
      return "URL 时间";
    }
  }

  // 2. URL 中带日期戳，例如 20260803 或 2026-08-03
  const dateMatch = cleanUrl.match(/(\d{4})[-_]?(\d{2})[-_]?(\d{2})/);
  if (dateMatch) {
    const datePrefix = `${dateMatch[1]}-${dateMatch[2]}-${dateMatch[3]}`;
    if (cleanTime.startsWith(datePrefix)) {
      return "URL 时间";
    }
  }

  return "人工填写";
}
