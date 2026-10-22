const pad = (value: number): string => String(value).padStart(2, "0");

/**
 * 把后端存的时间字符串（ISO 8601）转换成 `<input type="datetime-local">` 需要的本地时间值。
 * 无法解析时返回空串，调用方应保留原始值，避免静默丢数据。
 */
export function isoToLocalInput(value: string | null | undefined): string {
  if (!value || !value.trim()) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const datePart = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  const timePart = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  return `${datePart}T${timePart}`;
}

/**
 * 把 `<input type="datetime-local">` 的本地时间值转换回后端使用的 UTC ISO 字符串。
 */
export function localInputToIso(value: string): string {
  if (!value || !value.trim()) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString();
}

/**
 * 生成可读的时间提示，例如「2026-08-03 15:53（UTC 07:53）」。
 */
export function formatFileTimeLabel(value: string | null | undefined): string {
  if (!value || !value.trim()) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const localDate = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  const localTime = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  const utcTime = `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
  return `${localDate} ${localTime}（UTC ${utcTime}）`;
}
