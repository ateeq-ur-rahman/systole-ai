import type { ReactNode } from "react";
import { Inbox } from "lucide-react";

interface Props {
  icon?: ReactNode;
  title: string;
  detail?: string;
}

export function EmptyState({ icon, title, detail }: Props) {
  return (
    <div className="empty-state">
      <div className="empty-state-icon">{icon ?? <Inbox size={20} strokeWidth={1.75} />}</div>
      <div className="empty-state-title">{title}</div>
      {detail && <div>{detail}</div>}
    </div>
  );
}
