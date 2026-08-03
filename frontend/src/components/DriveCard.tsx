import type { Drive } from "../api/client";
import { humanBytes } from "../utils/format";

export function DriveCard({ drive }: { drive: Drive }) {
  const pctUsed = drive.capacity_bytes > 0 ? (drive.used_bytes / drive.capacity_bytes) * 100 : 0;
  const fillClass =
    drive.health === "critical" ? "critical" : drive.health === "warning" ? "warn" : "";

  return (
    <div className="drive-card">
      <div className="drive-card-top">
        <div>
          <div className="drive-name">{drive.volume_name || drive.letter}</div>
          <div className="drive-type">
            {drive.drive_type} · {drive.letter}
          </div>
        </div>
        <span className="pill">{drive.health}</span>
      </div>
      <div className="usage-bar">
        <div
          className={`usage-bar-fill ${fillClass}`}
          style={{ width: `${Math.min(pctUsed, 100)}%` }}
        />
      </div>
      <div className="drive-meta">
        <span>{humanBytes(drive.used_bytes)} used</span>
        <span>{humanBytes(drive.free_bytes)} free</span>
      </div>
    </div>
  );
}
