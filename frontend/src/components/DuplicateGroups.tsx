import { useEffect, useState } from "react";
import { CheckCircle2, ArrowRight, Copy, Sparkles } from "lucide-react";
import { api, type DuplicateGroup, type DuplicateMember } from "../api/client";
import { humanBytes, baseName, folderName, friendlySelectionReason } from "../utils/format";
import { FileIcon } from "./FileIcon";
import { EmptyState } from "./EmptyState";
import { Advanced } from "./Advanced";
import { SkeletonRows } from "./Skeleton";

interface Props {
  groups: DuplicateGroup[];
  onPreview: (groupId: number) => void;
  cleaningId: number | null;
}

interface GroupDetail {
  group: DuplicateGroup;
  members: DuplicateMember[];
}

export function DuplicateGroups({ groups, onPreview, cleaningId }: Props) {
  const [details, setDetails] = useState<Record<number, GroupDetail>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (groups.length === 0) {
      setDetails({});
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    Promise.all(groups.map((g) => api.getDuplicateGroup(g.id).catch(() => null)))
      .then((results) => {
        if (cancelled) return;
        const next: Record<number, GroupDetail> = {};
        results.forEach((r) => {
          if (r) next[r.group.id] = r;
        });
        setDetails(next);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // groups.length + first id is enough to know the set changed; full
    // array identity changes every refresh() poll otherwise.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groups.map((g) => g.id).join(",")]);

  if (groups.length === 0) {
    return (
      <EmptyState
        icon={<Copy size={20} strokeWidth={1.75} />}
        title="No duplicates found"
        detail="Ask AI to scan and Systole AI will find files that are byte-for-byte identical, wherever they're named differently."
      />
    );
  }

  if (loading && Object.keys(details).length === 0) {
    return (
      <div className="card">
        <SkeletonRows count={4} />
      </div>
    );
  }

  return (
    <div className="fade-in">
      {groups.map((g) => {
        const detail = details[g.id];
        const members = detail?.members ?? [];
        const kept = members.find((m) => m.is_survivor);
        const moving = members.filter((m) => !m.is_survivor);
        const title = kept ? baseName(kept.full_path) : `${g.file_count} identical files`;

        return (
          <div className="item-card" key={g.id}>
            <div className="item-card-head">
              <div className="item-icon-row">
                <FileIcon filename={title} />
                <div style={{ minWidth: 0 }}>
                  <div className="item-title">{title}</div>
                  <div className="item-subtitle">
                    {g.file_count} copies found · {humanBytes(g.reclaimable_bytes)} can be freed
                  </div>
                </div>
              </div>
              <div className="item-actions">
                <span className={`pill ${g.status}`}>{g.status === "cleaned" ? "Cleaned up" : "Needs cleanup"}</span>
                {g.status === "pending" && (
                  <button
                    className="btn btn-primary"
                    onClick={() => onPreview(g.id)}
                    disabled={cleaningId === g.id}
                  >
                    {cleaningId === g.id ? "Cleaning…" : "Clean"}
                  </button>
                )}
              </div>
            </div>

            {kept && (
              <>
                <div className="item-subtitle" style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 12, marginBottom: 6, fontWeight: 600, color: "var(--action)" }}>
                  <Sparkles size={12} strokeWidth={2.5} />
                  AI Recommendation
                </div>
                <div className="keep-move-row keep">
                  <CheckCircle2 size={15} strokeWidth={2} />
                  <span>
                    Keep <strong>{baseName(kept.full_path)}</strong> in {folderName(kept.full_path)}
                  </span>
                </div>
                {moving.length > 0 && (
                  <div className="keep-move-row move">
                    <ArrowRight size={15} strokeWidth={2} />
                    <span>
                      Move {moving.length} older cop{moving.length === 1 ? "y" : "ies"} to the AI Recovery Vault
                    </span>
                  </div>
                )}
                <div className="item-subtitle" style={{ marginTop: 8 }}>
                  Reason: {friendlySelectionReason(kept.selection_reason)}
                </div>
              </>
            )}

            <Advanced>
              <div><span className="k">Content hash</span> {g.sha256}</div>
              {members.map((m) => (
                <div key={m.id}>
                  <span className="k">{m.is_survivor ? "Kept" : "Moving"}</span> {m.full_path}
                </div>
              ))}
            </Advanced>
          </div>
        );
      })}
    </div>
  );
}
