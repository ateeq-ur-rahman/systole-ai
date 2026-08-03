export function humanBytes(num: number): string {
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let value = num;
  let unitIndex = 0;
  while (Math.abs(value) >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const formatted = unitIndex === 0 ? value.toFixed(0) : value.toFixed(1);
  return `${formatted} ${units[unitIndex]}`;
}

/** Parses timestamps from the backend, which arrive either as SQLite's
 * 'YYYY-MM-DD HH:MM:SS' (naive UTC) or full ISO strings. Normalizes both
 * to a real Date. */
export function parseServerTime(value: string): Date {
  const isoish = value.includes("T") ? value : value.replace(" ", "T");
  const hasZone = /[zZ]|[+-]\d\d:\d\d$/.test(isoish);
  return new Date(hasZone ? isoish : `${isoish}Z`);
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "—";
  const then = parseServerTime(value).getTime();
  if (Number.isNaN(then)) return "—";
  const diffSec = Math.round((then - Date.now()) / 1000);
  const abs = Math.abs(diffSec);
  const future = diffSec > 0;

  let text: string;
  if (abs < 10) text = "just now";
  else if (abs < 60) text = `${abs}s`;
  else if (abs < 3600) text = `${Math.round(abs / 60)}m`;
  else if (abs < 86400) text = `${Math.round(abs / 3600)}h`;
  else text = `${Math.round(abs / 86400)}d`;

  if (text === "just now") return text;
  return future ? `in ${text}` : `${text} ago`;
}

export function baseName(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] || path;
}

export function folderName(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  parts.pop();
  return parts[parts.length - 1] || parts.join("\\") || "—";
}

export function extensionOf(filename: string): string {
  const idx = filename.lastIndexOf(".");
  return idx > 0 ? filename.slice(idx).toLowerCase() : "";
}

const CATEGORY_BY_EXTENSION: Record<string, string> = {
  ".pdf": "pdf",
  ".doc": "document", ".docx": "document", ".rtf": "document", ".odt": "document",
  ".txt": "document", ".md": "document",
  ".xls": "spreadsheet", ".xlsx": "spreadsheet", ".csv": "spreadsheet", ".ods": "spreadsheet",
  ".ppt": "presentation", ".pptx": "presentation", ".odp": "presentation",
  ".jpg": "image", ".jpeg": "image", ".png": "image", ".gif": "image", ".bmp": "image",
  ".webp": "image", ".heic": "image", ".svg": "image", ".tiff": "image", ".tif": "image",
  ".mp4": "video", ".mov": "video", ".avi": "video", ".mkv": "video", ".webm": "video",
  ".zip": "archive", ".rar": "archive", ".7z": "archive", ".tar": "archive", ".gz": "archive",
  ".exe": "installer", ".msi": "installer", ".iso": "installer",
};

export function categoryOf(filename: string): string {
  return CATEGORY_BY_EXTENSION[extensionOf(filename)] ?? "file";
}

export function friendlySelectionReason(reason: string | null | undefined): string {
  if (!reason) return "AI determined this was the best copy to keep.";
  if (reason === "only_copy") return "Only copy found.";
  if (reason === "latest_modified") return "Newest version detected.";
  if (reason === "latest_created") return "Created most recently.";
  if (reason === "latest_accessed") return "Used most recently.";
  if (reason.startsWith("preferred_folder")) {
    const folder = reason.split(":")[1];
    return folder ? `Kept the copy in your ${folder} folder.` : "Kept the copy in the preferred folder.";
  }
  if (reason === "shortest_path") return "Kept the copy with the shortest path.";
  return "AI determined this was the best copy to keep.";
}
