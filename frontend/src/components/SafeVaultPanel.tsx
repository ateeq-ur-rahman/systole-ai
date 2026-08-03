import { useEffect, useState } from "react";
import { ShieldCheck, RotateCcw } from "lucide-react";
import { api, type CleanupHistoryEntry } from "../api/client";
import { humanBytes, baseName, folderName, relativeTime } from "../utils/format";
import { FileIcon } from "./FileIcon";
import { EmptyState } from "./EmptyState";
import { Advanced } from "./Advanced";
import { SkeletonRows } from "./Skeleton";

const REASON_LABELS: Record<string, string> = {
  redundant_copy: "Duplicate copy",
  hardlink_of_survivor: "Linked to the kept file",
  user_confirmed: "You chose to remove this version",
};

function friendlyReason(reason: string | null): string {
  if (!reason) return "Redundant copy";
  if (REASON_LABELS[reason]) return REASON_LABELS[reason];
  if (reason.startsWith("older_version")) return "Older version";
  if (reason.startsWith("latest_") || reason.startsWith("preferred_") || reason.startsWith("shortest_")) {
    return "Duplicate copy";
  }
  return "Redundant copy";
}

export function SafeVaultPanel({ refreshSignal }: { refreshSignal: number }) {
  const [entries, setEntries] = useState<CleanupHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [restoringId, setRestoringId] = useState<number | "all" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const rows = await api.getCleanupHistory(200);
      const stillInVault = rows.filter((r) => r.action === "moved_to_vault" && !r.restored_at);
      setEntries(stillInVault);
      setError(null);
    } catch {
      setError("Couldn't reach Systole AI.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal]);

  async function restoreOne(entry: CleanupHistoryEntry) {
    setRestoringId(entry.id);
    try {
      await api.restore(entry.id);
      await load();
    } catch {
      setError(`Couldn't restore "${baseName(entry.original_path)}" — it may already be restored, or the vault copy is missing.`);
    } finally {
      setRestoringId(null);
    }
  }

  async function restoreAll() {
    setRestoringId("all");
    try {
      await api.restore();
      await load();
    } finally {
      setRestoringId(null);
    }
  }

  if (loading) {
    return (
      <div className="card">
        <SkeletonRows count={3} />
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <EmptyState
        icon={<ShieldCheck size={20} strokeWidth={1.75} />}
        title="AI Recovery Vault is empty"
        detail="AI protects redundant copies here before anything is permanently removed — always restorable, never deleted outright."
      />
    );
  }

  const totalBytes = entries.reduce((sum, e) => sum + e.size_bytes, 0);

  return (
    <div className="ask-panel fade-in">
      <div className="ask-input-row" style={{ justifyContent: "space-between" }}>
        <span className="section-sub">
          {entries.length} file{entries.length !== 1 ? "s" : ""} · {humanBytes(totalBytes)} total
        </span>
        <button className="btn btn-primary" onClick={restoreAll} disabled={restoringId !== null}>
          <RotateCcw size={14} strokeWidth={2} />
          {restoringId === "all" ? "Restoring with AI…" : "Restore all with AI"}
        </button>
      </div>

      {error && (
        <div className="ask-answer" style={{ color: "var(--critical)", borderTop: "none", paddingTop: 0 }}>
          {error}
        </div>
      )}

      {entries.map((entry) => (
        <div className="item-card" key={entry.id}>
          <div className="item-card-head">
            <div className="item-icon-row">
              <FileIcon filename={baseName(entry.original_path)} />
              <div style={{ minWidth: 0 }}>
                <div className="item-title">{baseName(entry.original_path)}</div>
                <div className="item-subtitle">
                  {folderName(entry.original_path)} · {friendlyReason(entry.reason)} · {relativeTime(entry.performed_at)}
                </div>
              </div>
            </div>
            <div className="item-actions">
              <span className="section-sub mono">{humanBytes(entry.size_bytes)}</span>
              <button
                className="link-btn"
                onClick={() => restoreOne(entry)}
                disabled={restoringId !== null}
              >
                {restoringId === entry.id ? "Restoring…" : "Restore with AI"}
              </button>
            </div>
          </div>
          <Advanced>
            <div><span className="k">Original path</span> {entry.original_path}</div>
            <div><span className="k">Vault path</span> {entry.vault_path ?? "—"}</div>
            <div><span className="k">Deleted time</span> {entry.performed_at}</div>
          </Advanced>
        </div>
      ))}
    </div>
  );
}
