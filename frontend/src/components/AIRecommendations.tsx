import { useEffect, useState } from "react";
import { Archive, Package, Presentation, Sparkles, PartyPopper, X } from "lucide-react";
import { api, type DuplicateGroup, type Statistics } from "../api/client";
import { humanBytes, categoryOf } from "../utils/format";
import { EmptyState } from "./EmptyState";
import { SkeletonRows } from "./Skeleton";

interface Props {
  groups: DuplicateGroup[];
  stats: Statistics | null;
}

interface CategoryTotal {
  count: number;
  bytes: number;
}

const HIGHLIGHT_CATEGORIES: { key: string; label: string; icon: typeof Archive }[] = [
  { key: "archive", label: "Duplicate archive files", icon: Archive },
  { key: "installer", label: "Duplicate installers", icon: Package },
  { key: "presentation", label: "Duplicate presentations", icon: Presentation },
];

export function AIRecommendations({ groups, stats }: Props) {
  const [categoryTotals, setCategoryTotals] = useState<Record<string, CategoryTotal> | null>(null);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  useEffect(() => {
    api.getDismissedRecommendations()
      .then((r) => setDismissed(new Set(r.dismissed.map((d) => d.category))))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const pending = groups.filter((g) => g.status === "pending").slice(0, 30);
    if (pending.length === 0) {
      setCategoryTotals({});
      return;
    }
    let cancelled = false;
    Promise.all(pending.map((g) => api.getDuplicateGroup(g.id).catch(() => null))).then((results) => {
      if (cancelled) return;
      const totals: Record<string, CategoryTotal> = {};
      results.forEach((r) => {
        if (!r) return;
        const kept = r.members.find((m) => m.is_survivor);
        const moving = r.members.filter((m) => !m.is_survivor);
        const label = kept ? categoryOf(kept.full_path) : "file";
        const bytes = moving.reduce((sum, m) => sum + m.size_bytes, 0);
        totals[label] = totals[label] ?? { count: 0, bytes: 0 };
        totals[label].count += moving.length;
        totals[label].bytes += bytes;
      });
      setCategoryTotals(totals);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groups.map((g) => g.id).join(",")]);

  async function dismiss(category: string) {
    setDismissed((prev) => new Set(prev).add(category));
    try {
      // A 30-day snooze, not forever -- a category dismissed this month
      // may be exactly right to resurface next month (e.g. installers
      // pile up again), so this isn't a one-way "never show again."
      await api.dismissRecommendation(category, 30);
    } catch {
      setDismissed((prev) => {
        const next = new Set(prev);
        next.delete(category);
        return next;
      });
    }
  }

  const reclaimable = stats?.duplicate_reclaimable_bytes ?? 0;

  if (categoryTotals === null) {
    return (
      <div className="card">
        <SkeletonRows count={3} />
      </div>
    );
  }

  const highlightCards = HIGHLIGHT_CATEGORIES.filter((c) => !dismissed.has(c.key)).map((c) => {
    // Match category totals keyed by the friendly category (archive,
    // installer, presentation) computed above from each kept file's extension.
    const total = categoryTotals[c.key];
    return total && total.count > 0 ? { ...c, ...total } : null;
  }).filter(Boolean) as (typeof HIGHLIGHT_CATEGORIES[number] & CategoryTotal)[];

  if (highlightCards.length === 0 && (reclaimable === 0 || dismissed.has("__reclaimable__"))) {
    return (
      <EmptyState
        icon={<PartyPopper size={20} strokeWidth={1.75} />}
        title="You're all caught up"
        detail="No duplicate files detected right now — Systole AI will keep watching."
      />
    );
  }

  return (
    <div className="rec-grid fade-in">
      {highlightCards.map((c) => (
        <div className="rec-card" key={c.key} style={{ position: "relative" }}>
          <button
            className="icon-btn btn btn-ghost"
            style={{ position: "absolute", top: 8, right: 8, width: 24, height: 24 }}
            onClick={() => dismiss(c.key)}
            aria-label="Dismiss for 30 days"
            title="Not now — hide for 30 days"
          >
            <X size={13} strokeWidth={2} />
          </button>
          <div className="rec-card-icon">
            <c.icon size={16} strokeWidth={2} />
          </div>
          <div className="rec-card-title">{c.label}</div>
          <div className="rec-card-value">{humanBytes(c.bytes)}</div>
          <div className="rec-card-detail">{c.count} file{c.count !== 1 ? "s" : ""} could be cleaned up</div>
        </div>
      ))}

      {reclaimable > 0 && !dismissed.has("__reclaimable__") && (
        <div className="rec-card" style={{ position: "relative" }}>
          <button
            className="icon-btn btn btn-ghost"
            style={{ position: "absolute", top: 8, right: 8, width: 24, height: 24 }}
            onClick={() => dismiss("__reclaimable__")}
            aria-label="Dismiss for 30 days"
            title="Not now — hide for 30 days"
          >
            <X size={13} strokeWidth={2} />
          </button>
          <div className="rec-card-icon">
            <Sparkles size={16} strokeWidth={2} />
          </div>
          <div className="rec-card-title">Storage that can be recovered</div>
          <div className="rec-card-value">{humanBytes(reclaimable)}</div>
          <div className="rec-card-detail">across every duplicate found so far</div>
        </div>
      )}
    </div>
  );
}
