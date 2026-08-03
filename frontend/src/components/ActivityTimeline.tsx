import { useEffect, useState } from "react";
import { Info, CheckCircle2, AlertTriangle, XCircle, History } from "lucide-react";
import { api, type AppNotification } from "../api/client";
import { relativeTime } from "../utils/format";
import { EmptyState } from "./EmptyState";
import { SkeletonRows } from "./Skeleton";

const LEVEL_META: Record<string, { color: string; icon: typeof Info }> = {
  info: { color: "var(--ink-dim)", icon: Info },
  success: { color: "var(--pulse)", icon: CheckCircle2 },
  warning: { color: "var(--warn)", icon: AlertTriangle },
  error: { color: "var(--critical)", icon: XCircle },
};

export function ActivityTimeline({ refreshSignal }: { refreshSignal: number }) {
  const [notifications, setNotifications] = useState<AppNotification[] | null>(null);

  useEffect(() => {
    api.getNotifications(20).then((res) => setNotifications(res.notifications)).catch(() => setNotifications([]));
  }, [refreshSignal]);

  if (notifications === null) {
    return (
      <div className="card">
        <SkeletonRows count={4} />
      </div>
    );
  }

  if (notifications.length === 0) {
    return (
      <EmptyState
        icon={<History size={20} strokeWidth={1.75} />}
        title="No AI activity yet"
        detail="AI actions — scans, cleanups, and restores — will show up here as they happen."
      />
    );
  }

  return (
    <div className="ask-panel fade-in">
      {notifications.map((n) => {
        const meta = LEVEL_META[n.level] ?? LEVEL_META.info;
        const Icon = meta.icon;
        return (
          <div
            key={n.id}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              justifyContent: "space-between",
              padding: "10px 0",
              borderBottom: "1px solid var(--border)",
              fontSize: 13.5,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
              <Icon size={15} strokeWidth={2} color={meta.color} style={{ flexShrink: 0 }} />
              <span style={{ color: "var(--ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {n.message}
              </span>
            </div>
            <span className="mono dup-hash" style={{ flexShrink: 0, marginLeft: 12 }}>
              {relativeTime(n.created_at)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
