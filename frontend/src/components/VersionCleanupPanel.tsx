import { useEffect, useState } from "react";
import { FolderSearch, ScanLine, Pause, Play, X, Sparkles } from "lucide-react";
import {
  api,
  type VersionCleanupStatus,
  type VersionGroup,
  type VersionGroupMember,
} from "../api/client";
import { humanBytes, baseName } from "../utils/format";
import { PulseTrace } from "./PulseTrace";
import { EmptyState } from "./EmptyState";

interface Props {
  status: VersionCleanupStatus;
  onChange: () => void;
}

function GroupConfirmRow({ groupId, onResolved }: { groupId: number; onResolved: () => void }) {
  const [members, setMembers] = useState<VersionGroupMember[] | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getVersionGroupDetail(groupId).then((r) => setMembers(r.members));
  }, [groupId]);

  async function choose(fullPath: string) {
    setBusy(true);
    try {
      await api.confirmVersionGroup(groupId, fullPath);
      onResolved();
    } finally {
      setBusy(false);
    }
  }

  if (!members) return null;

  return (
    <div style={{ padding: "10px 0", borderBottom: "1px solid var(--border)" }}>
      <div style={{ fontSize: 12.5, color: "var(--warn)", marginBottom: 6 }}>
        Multiple versions detected — pick which one to keep:
      </div>
      {members.map((m) => (
        <div
          key={m.id}
          style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "4px 0" }}
        >
          <span className="mono" style={{ fontSize: 12 }}>
            {baseName(m.full_path)} · {humanBytes(m.size_bytes)}
          </span>
          <button className="link-btn" onClick={() => choose(m.full_path)} disabled={busy}>
            Keep this one
          </button>
        </div>
      ))}
    </div>
  );
}

export function VersionCleanupPanel({ status, onChange }: Props) {
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmGroups, setConfirmGroups] = useState<VersionGroup[]>([]);

  useEffect(() => {
    if (status.active && (status.version_groups_needing_confirmation ?? 0) > 0) {
      api.getVersionGroups("needs_confirmation").then(setConfirmGroups).catch(() => {});
    } else {
      setConfirmGroups([]);
    }
  }, [status.active, status.version_groups_needing_confirmation]);

  async function start() {
    if (!path.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.setVersionCleanupFolder(path.trim());
      setPath("");
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't watch that folder.");
    } finally {
      setBusy(false);
    }
  }

  async function scanNow() {
    setBusy(true);
    try {
      await api.scanVersionCleanupNow();
      onChange();
    } finally {
      setBusy(false);
    }
  }

  async function togglePause() {
    setBusy(true);
    try {
      if (status.paused) await api.resumeVersionCleanup();
      else await api.pauseVersionCleanup();
      onChange();
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    setBusy(true);
    try {
      await api.removeVersionCleanupFolder();
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
            placeholder={String.raw`e.g. C:\Users\alice\Downloads`}
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && start()}
          />
          <button className="btn btn-primary" onClick={start} disabled={busy}>
            {busy ? "Starting…" : "Watch for versions"}
          </button>
        </div>
        {error && (
          <div className="ask-answer" style={{ color: "var(--critical)", borderTop: "none", paddingTop: 0 }}>
            {error}
          </div>
        )}
        <EmptyState
          icon={<FolderSearch size={20} strokeWidth={1.75} />}
          title="No folder is being watched for versions"
          detail={'Detects things like "Project", "Project (1)"..."Project (7)" and keeps only the newest — older versions move to the Safe Vault, never deleted outright.'}
        />
      </div>
    );
  }

  return (
    <div className="ask-panel fade-in">
      <div className="drive-card-top" style={{ marginBottom: 4 }}>
        <div style={{ minWidth: 0 }}>
          <div className="badge on" style={{ marginBottom: 8 }}>
            <span className="badge-dot" />
            {status.paused ? "Paused" : "Watching"}
          </div>
          <div className="drive-name" title={status.path} style={{ wordBreak: "break-all" }}>
            {baseName(status.path ?? "")}
          </div>
          <div className="drive-type" style={{ textTransform: "none", letterSpacing: 0 }}>
            {status.path}
          </div>
        </div>
        <PulseTrace health={status.paused ? "warning" : "ok"} width={120} height={34} />
      </div>

      <div className="stat-grid">
        <div className="stat-cell">
          <div className="stat-cell-label">Cleaned groups</div>
          <div className="stat-cell-value">{status.version_groups_cleaned ?? 0}</div>
        </div>
        <div className="stat-cell">
          <div className="stat-cell-label">Needs your input</div>
          <div className="stat-cell-value warn">{status.version_groups_needing_confirmation ?? 0}</div>
        </div>
        <div className="stat-cell">
          <div className="stat-cell-label"><Sparkles size={13} /> AI Storage Saved</div>
          <div className="stat-cell-value accent">{humanBytes(status.storage_saved_bytes ?? 0)}</div>
        </div>
      </div>

      {confirmGroups.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          {confirmGroups.map((g) => (
            <GroupConfirmRow key={g.id} groupId={g.id} onResolved={onChange} />
          ))}
        </div>
      )}

      <div className="ask-input-row" style={{ marginBottom: 0 }}>
        <button className="btn btn-primary" onClick={scanNow} disabled={busy}>
          <ScanLine size={14} strokeWidth={2} />
          {busy ? "Working…" : "Scan now"}
        </button>
        <button className="btn" onClick={togglePause} disabled={busy}>
          {status.paused ? <Play size={14} strokeWidth={2} /> : <Pause size={14} strokeWidth={2} />}
          {status.paused ? "Resume" : "Pause"}
        </button>
        <button className="btn" onClick={stop} disabled={busy}>
          <X size={14} strokeWidth={2} />
          Stop watching
        </button>
      </div>
    </div>
  );
}
