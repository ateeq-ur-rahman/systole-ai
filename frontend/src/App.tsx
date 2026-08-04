import { useEffect, useState, useCallback } from "react";
import {
  api, type Statistics, type DuplicateGroup, type WatchedFolder,
  type FolderMonitorStatus, type VersionCleanupStatus,
} from "./api/client";
import { PulseTrace } from "./components/PulseTrace";
import { NavBar, type Tab } from "./components/NavBar";
import { CleanupPreviewModal } from "./components/CleanupPreviewModal";
import { AskPanel } from "./components/AskPanel";
import { DashboardPage } from "./pages/DashboardPage";
import { DuplicatesPage } from "./pages/DuplicatesPage";
import { VaultPage } from "./pages/VaultPage";
import { SettingsPage } from "./pages/SettingsPage";
import "./styles/theme.css";
import "./styles/app.css";

export default function App() {
  const [tab, setTab] = useState<Tab>("dashboard");
  const [stats, setStats] = useState<Statistics | null>(null);
  const [groups, setGroups] = useState<DuplicateGroup[]>([]);
  const [folders, setFolders] = useState<WatchedFolder[]>([]);
  const [folderMonitor, setFolderMonitor] = useState<FolderMonitorStatus>({ active: false });
  const [versionCleanup, setVersionCleanup] = useState<VersionCleanupStatus>({ active: false });
  const [vaultFileCount, setVaultFileCount] = useState<number | null>(null);
  const [activityTick, setActivityTick] = useState(0);
  const [scanning, setScanning] = useState(false);
  const [cleaningId, setCleaningId] = useState<number | null>(null);
  const [connectionError, setConnectionError] = useState(false);
  const [previewGroupIds, setPreviewGroupIds] = useState<number[] | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, g, f, fm, vc, vault] = await Promise.all([
        api.getStatistics(),
        api.getDuplicateGroups("pending"),
        api.getFolders(),
        api.getFolderMonitorStatus(),
        api.getVersionCleanupStatus(),
        api.getVault(),
      ]);
      setStats(s);
      setGroups(g);
      setFolders(f);
      setFolderMonitor(fm);
      setVersionCleanup(vc);
      setVaultFileCount(vault.length);
      setActivityTick((t) => t + 1);
      setConnectionError(false);
    } catch {
      setConnectionError(true);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 15000);
    return () => clearInterval(interval);
  }, [refresh]);

  async function runScan() {
    setScanning(true);
    try {
      await api.triggerScan("full");
      await refresh();
    } finally {
      setScanning(false);
    }
  }

  function openCleanNow() {
    const pending = groups.filter((g) => g.status === "pending").map((g) => g.id);
    if (pending.length === 0) return;
    setPreviewGroupIds(pending);
  }

  function openPreviewForGroup(groupId: number) {
    setPreviewGroupIds([groupId]);
  }

  async function confirmCleanup(groupIds: number[]) {
    setCleaningId(groupIds.length === 1 ? groupIds[0] : -1);
    try {
      await api.cleanupGroups(groupIds);
      await refresh();
    } finally {
      setCleaningId(null);
      setPreviewGroupIds(null);
    }
  }

  const overallHealth =
    stats?.drives.some((d) => d.health === "critical") ? "critical" :
    stats?.drives.some((d) => d.health === "warning") ? "warning" :
    stats ? "ok" : "unknown";

  const pendingDuplicateFileCount = groups.reduce((sum, g) => sum + Math.max(g.file_count - 1, 0), 0);

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <div className="brand-mark">S</div>
          <div className="brand-text">
            <h1>Systole AI</h1>
            <p>AI Operating System for Windows</p>
          </div>
        </div>
        <div className="header-actions">
          <PulseTrace health={overallHealth} />
        </div>
      </header>

      {connectionError && (
        <div className="empty-state" style={{ marginBottom: 28 }}>
          Can't reach the Systole AI background service at <span className="mono">127.0.0.1:8731</span>.
          If you're running from source, make sure <span className="mono">run.py</span> is running.
          If you installed Systole AI, open <span className="mono">%TEMP%\systole-startup-diagnostic.log</span>{" "}
          — it explains exactly what happened when the app last launched.
        </div>
      )}

      <NavBar
        active={tab}
        onChange={setTab}
        duplicateCount={pendingDuplicateFileCount}
        vaultCount={vaultFileCount ?? undefined}
      />

      {tab === "dashboard" && (
        <DashboardPage
          stats={stats}
          groups={groups}
          folders={folders}
          folderMonitor={folderMonitor}
          versionCleanup={versionCleanup}
          vaultFileCount={vaultFileCount}
          activityTick={activityTick}
          scanning={scanning}
          onScanNow={runScan}
          onCleanNow={openCleanNow}
          onChange={refresh}
        />
      )}

      {tab === "duplicates" && (
        <DuplicatesPage groups={groups} onPreview={openPreviewForGroup} cleaningId={cleaningId} />
      )}

      {tab === "vault" && <VaultPage refreshSignal={activityTick} />}

      {tab === "settings" && <SettingsPage />}

      {tab === "dashboard" && (
        <section className="section" style={{ marginTop: 8 }}>
          <div className="section-head">
            <div className="section-head-title">
              <h2 style={{ fontSize: 14 }}>Ask Systole AI</h2>
            </div>
          </div>
          <AskPanel />
        </section>
      )}

      {previewGroupIds && (
        <CleanupPreviewModal
          groupIds={previewGroupIds}
          onCancel={() => setPreviewGroupIds(null)}
          onConfirm={confirmCleanup}
        />
      )}

      <p className="footnote">
        Redundant copies are moved to the AI Recovery Vault, never deleted outright — restore anytime.
      </p>
    </div>
  );
}
