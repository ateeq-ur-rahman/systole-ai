import { useState } from "react";
import { Sparkles, Pause, Play, X, Files, Bot } from "lucide-react";
import { api, type FolderMonitorStatus } from "../api/client";
import { humanBytes, relativeTime, baseName } from "../utils/format";
import { PulseTrace } from "./PulseTrace";
import { EmptyState } from "./EmptyState";

interface Props {
  status: FolderMonitorStatus;
  onChange: () => void;
}

export function FolderMonitorPanel({ status, onChange }: Props) {
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function selectFolder() {
    if (!path.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.setMonitoredFolder(path.trim());
      setPath("");
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't monitor that folder.");
    } finally {
      setBusy(false);
    }
  }

  async function analyzeNow() {
    setBusy(true);
    try {
      await api.scanMonitoredFolderNow();
      onChange();
    } finally {
      setBusy(false);
    }
  }

  async function togglePause() {
    setBusy(true);
    try {
      if (status.paused) await api.resumeFolderMonitor();
      else await api.pauseFolderMonitor();
      onChange();
    } finally {
      setBusy(false);
    }
  }

  async function stopAgent() {
    setBusy(true);
    try {
      await api.removeMonitoredFolder();
      onChange();
    } finally {
      setBusy(false);
    }
  }

  if (!status.active) {
    return (
      <div className="ask-panel">
        <div className="ask-input-row">
          <input
            placeholder={String.raw`Select a folder for AI to protect, e.g. C:\Users\alice\Downloads`}
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && selectFolder()}
          />
          <button className="btn btn-primary" onClick={selectFolder} disabled={busy}>
            {busy ? "Starting AI…" : "Activate AI Agent"}
          </button>
        </div>
        {error && (
          <div className="ask-answer" style={{ color: "var(--critical)", borderTop: "none", paddingTop: 0 }}>
            {error}
          </div>
        )}
        <EmptyState
          icon={<Bot size={20} strokeWidth={1.75} />}
          title="AI Storage Agent isn't watching anything yet"
          detail="Once activated, AI will continuously watch this folder, keep it free of exact duplicates automatically, and protect anything it moves — nothing else on your drive is touched."
        />
      </div>
    );
  }

  const health = status.status === "paused" ? "warning" : "ok";

  return (
    <div className="ask-panel fade-in">
      <div className="drive-card-top" style={{ marginBottom: 4 }}>
        <div style={{ minWidth: 0 }}>
          <div className="badge on" style={{ marginBottom: 8 }}>
            <span className="badge-dot" />
            {status.paused ? "AI Paused" : "AI Active"}
          </div>
          <div className="drive-name" title={status.path} style={{ wordBreak: "break-all" }}>
            {baseName(status.path ?? "")}
          </div>
          <div className="drive-type" style={{ textTransform: "none", letterSpacing: 0 }}>
            {status.path} · AI checks every {Math.round((status.scan_interval_seconds ?? 120) / 60) || "<1"} min
          </div>
        </div>
        <PulseTrace health={health} width={120} height={34} />
      </div>

      <div className="stat-grid">
        <div className="stat-cell">
          <div className="stat-cell-label"><Files size={13} /> Files Analyzed</div>
          <div className="stat-cell-value">{status.total_files?.toLocaleString() ?? "—"}</div>
        </div>
        <div className="stat-cell">
          <div className="stat-cell-label">Duplicate Files Found</div>
          <div className="stat-cell-value">{status.duplicate_files ?? 0}</div>
        </div>
        <div className="stat-cell">
          <div className="stat-cell-label"><Sparkles size={13} /> Recoverable Storage</div>
          <div className="stat-cell-value accent">{humanBytes(status.reclaimable_bytes ?? 0)}</div>
        </div>
        <div className="stat-cell">
          <div className="stat-cell-label">Files Protected</div>
          <div className="stat-cell-value warn">{status.vault_entries ?? 0}</div>
        </div>
      </div>

      <div className="drive-meta" style={{ marginBottom: 16 }}>
        <span>AI last analysis: {relativeTime(status.last_scan_at)}</span>
        <span>Next AI check: {status.paused ? "paused" : relativeTime(status.next_scan_at)}</span>
      </div>

      <div className="ask-input-row" style={{ marginBottom: 0 }}>
        <button className="btn btn-primary" onClick={analyzeNow} disabled={busy}>
          <Sparkles size={14} strokeWidth={2} />
          {busy ? "AI is analyzing…" : "Analyze Folder"}
        </button>
        <button className="btn" onClick={togglePause} disabled={busy}>
          {status.paused ? <Play size={14} strokeWidth={2} /> : <Pause size={14} strokeWidth={2} />}
          {status.paused ? "Resume AI" : "Pause AI"}
        </button>
        <button className="btn" onClick={stopAgent} disabled={busy}>
          <X size={14} strokeWidth={2} />
          Stop Agent
        </button>
      </div>
    </div>
  );
}
