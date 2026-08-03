import { useEffect, useState } from "react";
import { X, Eye, CheckCircle2 } from "lucide-react";
import { api, type DuplicateMember } from "../api/client";
import { humanBytes, baseName, folderName } from "../utils/format";

interface Props {
  groupIds: number[];
  onCancel: () => void;
  onConfirm: (groupIds: number[]) => Promise<void> | void;
}

interface Aggregate {
  folders: Set<string>;
  kept: DuplicateMember[];
  moved: DuplicateMember[];
  bytes: number;
}

export function CleanupPreviewModal({ groupIds, onCancel, onConfirm }: Props) {
  const [aggregate, setAggregate] = useState<Aggregate | null>(null);
  const [showFiles, setShowFiles] = useState(false);
  const [cleaning, setCleaning] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all(groupIds.map((id) => api.getDuplicateGroup(id).catch(() => null))).then((results) => {
      if (cancelled) return;
      const folders = new Set<string>();
      const kept: DuplicateMember[] = [];
      const moved: DuplicateMember[] = [];
      let bytes = 0;
      results.forEach((r) => {
        if (!r) return;
        r.members.forEach((m) => {
          folders.add(folderName(m.full_path));
          if (m.is_survivor) kept.push(m);
          else {
            moved.push(m);
            bytes += m.size_bytes;
          }
        });
      });
      setAggregate({ folders, kept, moved, bytes });
    });
    return () => {
      cancelled = true;
    };
  }, [groupIds]);

  async function handleConfirm() {
    setCleaning(true);
    try {
      await onConfirm(groupIds);
    } finally {
      setCleaning(false);
    }
  }

  const folderLabel = aggregate
    ? aggregate.folders.size === 1
      ? [...aggregate.folders][0]
      : `${aggregate.folders.size} folders`
    : "—";

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal fade-in" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>You're about to clean up</h3>
          <button className="icon-btn btn btn-ghost" onClick={onCancel} aria-label="Cancel">
            <X size={16} strokeWidth={2} />
          </button>
        </div>

        {!aggregate ? (
          <div className="modal-body">
            <div className="skeleton skeleton-row" style={{ width: "80%" }} />
            <div className="skeleton skeleton-row" style={{ width: "60%" }} />
          </div>
        ) : (
          <div className="modal-body">
            <div className="stat-grid" style={{ margin: "4px 0 16px" }}>
              <div className="stat-cell">
                <div className="stat-cell-label">Folder</div>
                <div className="stat-cell-value" style={{ fontSize: 14 }} title={folderLabel}>
                  {folderLabel}
                </div>
              </div>
              <div className="stat-cell">
                <div className="stat-cell-label">Files kept</div>
                <div className="stat-cell-value">{aggregate.kept.length}</div>
              </div>
              <div className="stat-cell">
                <div className="stat-cell-label">Files moved</div>
                <div className="stat-cell-value warn">{aggregate.moved.length}</div>
              </div>
              <div className="stat-cell">
                <div className="stat-cell-label">Storage recovered</div>
                <div className="stat-cell-value accent">{humanBytes(aggregate.bytes)}</div>
              </div>
            </div>

            <button className="advanced-toggle" onClick={() => setShowFiles((v) => !v)} style={{ marginBottom: showFiles ? 10 : 0 }}>
              <Eye size={12} strokeWidth={2.5} />
              {showFiles ? "Hide files" : "Preview files"}
            </button>

            {showFiles && (
              <div className="advanced-body fade-in" style={{ maxHeight: 220, overflowY: "auto" }}>
                {aggregate.kept.map((m) => (
                  <div key={`kept-${m.id}`}>
                    <span className="k" style={{ color: "var(--success)" }}>Keep</span>
                    {baseName(m.full_path)}
                  </div>
                ))}
                {aggregate.moved.map((m) => (
                  <div key={`moved-${m.id}`}>
                    <span className="k" style={{ color: "var(--warn)" }}>Move</span>
                    {baseName(m.full_path)}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="modal-actions">
          <button className="btn" onClick={onCancel} disabled={cleaning}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={handleConfirm} disabled={cleaning || !aggregate}>
            <CheckCircle2 size={14} strokeWidth={2} />
            {cleaning ? "Cleaning…" : "Clean now"}
          </button>
        </div>
      </div>
    </div>
  );
}
