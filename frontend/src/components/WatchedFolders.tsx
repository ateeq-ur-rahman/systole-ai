import { useState } from "react";
import { FolderPlus, FolderClock, ScanLine } from "lucide-react";
import { api, type WatchedFolder } from "../api/client";
import { EmptyState } from "./EmptyState";

interface Props {
  folders: WatchedFolder[];
  onChange: () => void;
}

export function WatchedFolders({ folders, onChange }: Props) {
  const [path, setPath] = useState("");
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [scanningId, setScanningId] = useState<number | null>(null);

  async function addFolder() {
    if (!path.trim()) return;
    setAdding(true);
    setError(null);
    try {
      await api.addFolder(path.trim(), label.trim() || undefined);
      setPath("");
      setLabel("");
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't add that folder.");
    } finally {
      setAdding(false);
    }
  }

  async function scanNow(id: number) {
    setScanningId(id);
    try {
      await api.scanFolder(id);
      onChange();
    } finally {
      setScanningId(null);
    }
  }

  async function remove(id: number) {
    await api.removeFolder(id);
    onChange();
  }

  return (
    <div className="ask-panel">
      <div className="ask-input-row">
        <input
          placeholder={String.raw`e.g. C:\Users\alice\Projects  or  D:\Photos`}
          value={path}
          onChange={(e) => setPath(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addFolder()}
          style={{ flex: 2 }}
        />
        <input
          placeholder="Label (optional)"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addFolder()}
          style={{ flex: 1 }}
        />
        <button className="btn btn-primary" onClick={addFolder} disabled={adding}>
          <FolderPlus size={14} strokeWidth={2} />
          {adding ? "Adding…" : "Watch folder"}
        </button>
      </div>

      {error && (
        <div className="ask-answer" style={{ color: "var(--critical)", borderTop: "none", paddingTop: 0 }}>
          {error}
        </div>
      )}

      {folders.length === 0 ? (
        <EmptyState
          icon={<FolderClock size={20} strokeWidth={1.75} />}
          title="No folders being watched"
          detail="Add any folder path above — Systole AI will scan it for duplicates and monitor it for changes in real time."
        />
      ) : (
        <table className="dup-table" style={{ marginTop: 14 }}>
          <thead>
            <tr>
              <th>Folder</th>
              <th>Last scan</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {folders.map((f) => (
              <tr key={f.id}>
                <td>
                  <div>{f.label || f.path}</div>
                  {f.label && <div className="mono dup-hash">{f.path}</div>}
                </td>
                <td>
                  <span className={`pill ${f.last_scan_status === "completed" ? "cleaned" : ""}`}>
                    {f.last_scan_status ?? "pending"}
                  </span>
                </td>
                <td style={{ textAlign: "right" }}>
                  <button
                    className="link-btn"
                    onClick={() => scanNow(f.id)}
                    disabled={scanningId === f.id}
                    style={{ marginRight: 14 }}
                  >
                    <ScanLine size={12} strokeWidth={2} style={{ verticalAlign: -2, marginRight: 3 }} />
                    {scanningId === f.id ? "Scanning…" : "Scan now"}
                  </button>
                  <button className="link-btn danger" onClick={() => remove(f.id)}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
