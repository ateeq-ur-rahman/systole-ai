import { Sparkles, CheckCircle2 } from "lucide-react";
import type { Statistics, DuplicateGroup, FolderMonitorStatus } from "../api/client";
import { humanBytes } from "../utils/format";

interface Props {
  stats: Statistics | null;
  groups: DuplicateGroup[];
  folderMonitor: FolderMonitorStatus;
}

/** Plain-language, AI-voiced observations derived entirely from data the
 * app already has (statistics + duplicate groups) -- no backend changes,
 * no new data source, just narration on top of what's already fetched. */
export function AIInsights({ stats, groups, folderMonitor }: Props) {
  if (!stats) return null;

  const pending = groups.filter((g) => g.status === "pending");
  const reclaimable = stats.duplicate_reclaimable_bytes;

  const lines: string[] = [];

  if (!folderMonitor.active) {
    lines.push("AI Storage Agent isn't watching a folder yet — point it at Downloads to start protecting it automatically.");
  } else if (pending.length === 0) {
    lines.push(`Your ${folderMonitor.path?.split(/[\\/]/).filter(Boolean).pop() ?? "monitored"} folder is healthy — no duplicates detected right now.`);
  }

  if (pending.length > 0) {
    lines.push(
      `AI recommends cleaning ${pending.length} duplicate file group${pending.length !== 1 ? "s" : ""} to recover ${humanBytes(reclaimable)}.`
    );
  }

  if (reclaimable > 0) {
    lines.push(`AI predicts you can recover another ${humanBytes(reclaimable)} by cleaning up what's already been found.`);
  }

  if (lines.length === 0) {
    lines.push("Everything looks good — AI has nothing to flag right now.");
  }

  return (
    <div className="ask-panel fade-in">
      {lines.map((line, i) => (
        <div
          key={i}
          style={{
            display: "flex", alignItems: "flex-start", gap: 10,
            padding: "10px 0", borderBottom: i < lines.length - 1 ? "1px solid var(--border)" : "none",
            fontSize: 13.5,
          }}
        >
          {i === 0 && pending.length === 0 && folderMonitor.active ? (
            <CheckCircle2 size={16} strokeWidth={2} color="var(--success)" style={{ flexShrink: 0, marginTop: 1 }} />
          ) : (
            <Sparkles size={16} strokeWidth={2} color="var(--action)" style={{ flexShrink: 0, marginTop: 1 }} />
          )}
          <span>{line}</span>
        </div>
      ))}
    </div>
  );
}
