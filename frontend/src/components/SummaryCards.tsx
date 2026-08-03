import type { Statistics, DuplicateGroup, FolderMonitorStatus, VersionCleanupStatus } from "../api/client";
import { HardDriveDownload, Copy, ShieldCheck, History, Clock } from "lucide-react";
import { humanBytes, relativeTime } from "../utils/format";
import { SkeletonCards } from "./Skeleton";

interface Props {
  stats: Statistics | null;
  groups: DuplicateGroup[];
  folderMonitor: FolderMonitorStatus;
  versionCleanup: VersionCleanupStatus;
  vaultFileCount: number | null;
}

export function SummaryCards({ stats, groups, folderMonitor, versionCleanup, vaultFileCount }: Props) {
  if (!stats) {
    return <SkeletonCards count={5} />;
  }

  const duplicateFileCount = groups.reduce((sum, g) => sum + Math.max(g.file_count - 1, 0), 0);

  // Last/next scan: whichever active feature (Folder Monitor, Version
  // Cleanup) has run or is scheduled soonest — most people only run one
  // at a time, and this stays honest ("—") when neither is active rather
  // than inventing a number.
  const lastScanCandidates = [folderMonitor.last_scan_at, versionCleanup.last_scan_at].filter(Boolean) as string[];
  const nextScanCandidates = [folderMonitor.next_scan_at, versionCleanup.next_scan_at].filter(Boolean) as string[];
  const lastScan = lastScanCandidates.sort().at(-1) ?? null;
  const nextScan = nextScanCandidates.sort().at(0) ?? null;

  return (
    <div className="widget-grid fade-in">
      <div className="widget-card">
        <div className="widget-icon">
          <HardDriveDownload size={17} strokeWidth={2} />
        </div>
        <div>
          <div className="widget-value">{humanBytes(stats.vault_bytes)}</div>
          <div className="widget-label">AI Storage Recovered</div>
        </div>
      </div>

      <div className="widget-card">
        <div className="widget-icon warn">
          <Copy size={17} strokeWidth={2} />
        </div>
        <div>
          <div className="widget-value">{duplicateFileCount.toLocaleString()}</div>
          <div className="widget-label">AI Duplicate Insights</div>
        </div>
      </div>

      <div className="widget-card">
        <div className="widget-icon">
          <ShieldCheck size={17} strokeWidth={2} />
        </div>
        <div>
          <div className="widget-value">{vaultFileCount ?? "—"}</div>
          <div className="widget-label">AI Protected Files</div>
        </div>
      </div>

      <div className="widget-card">
        <div className="widget-icon neutral">
          <History size={17} strokeWidth={2} />
        </div>
        <div>
          <div className="widget-value" style={{ fontSize: 18 }}>{relativeTime(lastScan)}</div>
          <div className="widget-label">AI Last Analysis</div>
        </div>
      </div>

      <div className="widget-card">
        <div className="widget-icon neutral">
          <Clock size={17} strokeWidth={2} />
        </div>
        <div>
          <div className="widget-value" style={{ fontSize: 18 }}>
            {nextScan ? relativeTime(nextScan) : "Not scheduled"}
          </div>
          <div className="widget-label">Next AI Check</div>
        </div>
      </div>
    </div>
  );
}
