import type { DuplicateGroup } from "../api/client";
import { DuplicateGroups } from "../components/DuplicateGroups";

interface Props {
  groups: DuplicateGroup[];
  onPreview: (groupId: number) => void;
  cleaningId: number | null;
}

export function DuplicatesPage({ groups, onPreview, cleaningId }: Props) {
  return (
    <div className="fade-in">
      <div className="section-head" style={{ marginBottom: 18 }}>
        <div>
          <h2 style={{ fontSize: 20, margin: 0 }}>AI Findings</h2>
          <p className="section-sub" style={{ marginTop: 4 }}>
            grouped by file — reviewed within 24 hours, or AI cleans them up for you
          </p>
        </div>
      </div>
      <DuplicateGroups groups={groups} onPreview={onPreview} cleaningId={cleaningId} />
    </div>
  );
}
