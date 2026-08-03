import type { DuplicateGroup } from "../api/client";
import { humanBytes } from "../utils/format";

interface Props {
  groups: DuplicateGroup[];
  onSelect: (id: number) => void;
  onClean: (id: number) => void;
  cleaningId: number | null;
}

export function DuplicatesTable({ groups, onSelect, onClean, cleaningId }: Props) {
  if (groups.length === 0) {
    return (
      <div className="empty-state">
        No confirmed duplicates yet. Run a scan to check for identical files across your drives.
      </div>
    );
  }

  return (
    <table className="dup-table">
      <thead>
        <tr>
          <th>Content hash</th>
          <th>Copies</th>
          <th>Reclaimable</th>
          <th>Status</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {groups.map((g) => (
          <tr key={g.id}>
            <td>
              <span className="mono dup-hash">{g.sha256.slice(0, 16)}…</span>
            </td>
            <td>{g.file_count} identical files</td>
            <td className="mono">{humanBytes(g.reclaimable_bytes)}</td>
            <td>
              <span className={`pill ${g.status}`}>{g.status}</span>
            </td>
            <td style={{ textAlign: "right" }}>
              <button className="link-btn" onClick={() => onSelect(g.id)} style={{ marginRight: 14 }}>
                View
              </button>
              {g.status === "pending" && (
                <button
                  className="link-btn"
                  onClick={() => onClean(g.id)}
                  disabled={cleaningId === g.id}
                >
                  {cleaningId === g.id ? "Moving…" : "Clean up"}
                </button>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
