const MINOR_FAMILY_ADAPTERS = new Set(["endfield", "endfield-resources", "patchersdk"]);
const MINOR_FAMILY_GAMES = new Set(["endfield", "nte"]);

/**
 * Return the release family shown by the version picker.
 *
 * HoYo and WuWa, along with older/less structured Android catalogs, use the
 * first segment as their useful major version (9.x, 8.x, 3.x). NTE and
 * Endfield publish meaningful release families in the first two segments
 * (1.3.x, 1.2.x), as do their PC/resource adapters and PatcherSDK. Keeping
 * this small rule here avoids making the component know about every version
 * format while leaving the raw version and ordering untouched.
 */
export function versionFamily(version: string, adapter = "", gameId = ""): string {
  const parts = version.split(".").map((part) => part.trim()).filter(Boolean);
  if (!parts.length) return "未知版本";
  const useMinorFamily = MINOR_FAMILY_ADAPTERS.has(adapter) || MINOR_FAMILY_GAMES.has(gameId);
  const prefix = useMinorFamily && parts.length > 1 ? parts.slice(0, 2) : parts.slice(0, 1);
  return `${prefix.join(".")}.x`;
}
