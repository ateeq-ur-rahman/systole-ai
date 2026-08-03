import { useState } from "react";
import {
  Sparkles, CheckCircle2, Bot, History as VersionHistory,
  Lightbulb, Activity, HardDrive, FolderClock, ChevronDown, ChevronRight,
} from "lucide-react";
import type {
  Statistics, DuplicateGroup, WatchedFolder, FolderMonitorStatus, VersionCleanupStatus,
} from "../api/client";
import { SummaryCards } from "../components/SummaryCards";
import { FolderMonitorPanel } from "../components/FolderMonitorPanel";
import { VersionCleanupPanel } from "../components/VersionCleanupPanel";
import { AIRecommendations } from "../components/AIRecommendations";
import { AIInsights } from "../components/AIInsights";
import { ActivityTimeline } from "../components/ActivityTimeline";
import { DriveCard } from "../components/DriveCard";
import { WatchedFolders } from "../components/WatchedFolders";
import { EmptyState } from "../components/EmptyState";

interface Props {
  stats: Statistics | null;
  groups: DuplicateGroup[];
  folders: WatchedFolder[];
  folderMonitor: FolderMonitorStatus;
  versionCleanup: VersionCleanupStatus;
  vaultFileCount: number | null;
  activityTick: number;
  scanning: boolean;
  onScanNow: () => void;
  onCleanNow: () => void;
  onChange: () => void;
}

function SectionHead({ icon, title, sub }: { icon: React.ReactNode; title: string; sub?: string }) {
  return (
    <div className="section-head">
      <div className="section-head-title">
        <div className="section-icon">{icon}</div>
        <h2>{title}</h2>
      </div>
      {sub && <span className="section-sub">{sub}</span>}
    </div>
  );
}

export function DashboardPage({
  stats, groups, folders, folderMonitor, versionCleanup, vaultFileCount, activityTick,
  scanning, onScanNow, onCleanNow, onChange,
}: Props) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const pendingCount = groups.filter((g) => g.status === "pending").length;

  return (
    <div className="fade-in">
      <div className="ask-input-row" style={{ marginBottom: 24 }}>
        <button className="btn btn-primary" onClick={onScanNow} disabled={scanning} style={{ flex: 1, justifyContent: "center", padding: "13px 20px" }}>
          <Sparkles size={16} strokeWidth={2} />
          {scanning ? "AI is analyzing…" : "Ask AI to Scan"}
        </button>
        <button
          className="btn"
          onClick={onCleanNow}
          disabled={pendingCount === 0}
          style={{ flex: 1, justifyContent: "center", padding: "13px 20px" }}
        >
          <CheckCircle2 size={16} strokeWidth={2} />
          Clean Now{pendingCount > 0 ? ` (${pendingCount})` : ""}
        </button>
      </div>

      <SummaryCards
        stats={stats}
        groups={groups}
        folderMonitor={folderMonitor}
        versionCleanup={versionCleanup}
        vaultFileCount={vaultFileCount}
      />

      <section className="section">
        <SectionHead
          icon={<Lightbulb size={15} strokeWidth={2} />}
          title="AI Insights"
          sub="what Systole AI is noticing right now"
        />
        <AIInsights stats={stats} groups={groups} folderMonitor={folderMonitor} />
      </section>

      <section className="section">
        <SectionHead
          icon={<Bot size={15} strokeWidth={2} />}
          title="AI Storage Agent"
          sub="continuously watching your Downloads folder using AI"
        />
        <FolderMonitorPanel status={folderMonitor} onChange={onChange} />
      </section>

      <section className="section">
        <SectionHead
          icon={<VersionHistory size={15} strokeWidth={2} />}
          title="Version Cleanup"
          sub={'"Project", "Project (1)"..."Project (7)" → keeps only the newest'}
        />
        <VersionCleanupPanel status={versionCleanup} onChange={onChange} />
      </section>

      <section className="section">
        <SectionHead
          icon={<Lightbulb size={15} strokeWidth={2} />}
          title="AI Recommendations"
          sub="things worth cleaning up, spotted automatically"
        />
        <AIRecommendations groups={groups} stats={stats} />
      </section>

      <section className="section">
        <SectionHead icon={<Activity size={15} strokeWidth={2} />} title="AI Activity" />
        <ActivityTimeline refreshSignal={activityTick} />
      </section>

      <section className="section">
        <button
          className="advanced-toggle"
          onClick={() => setAdvancedOpen((v) => !v)}
          style={{ fontSize: 13, marginBottom: advancedOpen ? 14 : 0 }}
        >
          {advancedOpen ? <ChevronDown size={13} strokeWidth={2.5} /> : <ChevronRight size={13} strokeWidth={2.5} />}
          Developer Tools
        </button>

        {advancedOpen && (
          <div className="dashboard-advanced fade-in">
            <section className="section">
              <SectionHead icon={<HardDrive size={15} strokeWidth={2} />} title="Drives" sub={`${stats?.drives.length ?? 0} detected`} />
              {stats && stats.drives.length > 0 ? (
                <div className="drive-grid">
                  {stats.drives.map((d) => (
                    <DriveCard key={d.id} drive={d} />
                  ))}
                </div>
              ) : (
                <EmptyState
                  icon={<HardDrive size={20} strokeWidth={1.75} />}
                  title="No drives discovered yet"
                  detail="Run a scan to detect connected storage."
                />
              )}
            </section>

            <section className="section">
              <SectionHead
                icon={<FolderClock size={15} strokeWidth={2} />}
                title="Watched folders"
                sub="point Systole AI at any specific folder to scan & monitor"
              />
              <WatchedFolders folders={folders} onChange={onChange} />
            </section>
          </div>
        )}
      </section>
    </div>
  );
}
