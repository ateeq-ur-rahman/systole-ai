import { useEffect, useState } from "react";
import { api, type ScanFilterSettings } from "../api/client";

const CATEGORY_LABELS: Record<string, string> = {
  documents: "Documents",
  pdfs: "PDFs",
  images: "Images",
  videos: "Videos",
  office: "Office files",
  archives: "Archives (ZIP/RAR/7Z)",
  installers: "Installers (EXE/MSI/ISO)",
  source_code: "Source Code",
  system_files: "System Files",
};

const CATEGORY_ORDER = [
  "documents", "pdfs", "images", "videos", "office",
  "archives", "installers", "source_code", "system_files",
];

function bytesToKb(bytes: number): number {
  return Math.round(bytes / 1024);
}

export function SettingsPanel() {
  const [settings, setSettings] = useState<ScanFilterSettings | null>(null);
  const [ignoredFoldersText, setIgnoredFoldersText] = useState("");
  const [minSizeKb, setMinSizeKb] = useState(4);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.getScanFilterSettings().then((s) => {
      setSettings(s);
      setIgnoredFoldersText(s.ignored_folder_names.join(", "));
      setMinSizeKb(bytesToKb(s.minimum_file_size_bytes));
    });
  }, []);

  if (!settings) {
    return <div className="empty-state">Loading settings…</div>;
  }

  const orderedCategories = [
    ...CATEGORY_ORDER.filter((c) => settings.available_categories.some((a) => a.id === c)),
    ...settings.available_categories.map((a) => a.id).filter((id) => !CATEGORY_ORDER.includes(id)),
  ];

  async function toggleCategory(categoryId: string) {
    if (!settings) return;
    const isEnabled = settings.enabled_categories.includes(categoryId);
    const next = isEnabled
      ? settings.enabled_categories.filter((c) => c !== categoryId)
      : [...settings.enabled_categories, categoryId];

    setSettings({ ...settings, enabled_categories: next });
    setSaving(true);
    try {
      const updated = await api.updateScanFilterSettings({ enabled_categories: next });
      setSettings(updated);
      flashSaved();
    } finally {
      setSaving(false);
    }
  }

  function flashSaved() {
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  }

  async function saveIgnoredFolders() {
    const list = ignoredFoldersText
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    setSaving(true);
    try {
      const updated = await api.updateScanFilterSettings({ ignored_folder_names: list });
      setSettings(updated);
      setIgnoredFoldersText(updated.ignored_folder_names.join(", "));
      flashSaved();
    } finally {
      setSaving(false);
    }
  }

  async function saveMinSize() {
    setSaving(true);
    try {
      const updated = await api.updateScanFilterSettings({
        minimum_file_size_bytes: Math.max(0, minSizeKb) * 1024,
      });
      setSettings(updated);
      flashSaved();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="ask-panel">
      <div style={{ marginBottom: 20 }}>
        <div className="field-label" style={{ marginBottom: 10 }}>
          File categories to scan
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 8 }}>
          {orderedCategories.map((categoryId) => {
            const enabled = settings.enabled_categories.includes(categoryId);
            const category = settings.available_categories.find((c) => c.id === categoryId);
            return (
              <label
                key={categoryId}
                style={{
                  display: "flex", alignItems: "center", gap: 8,
                  padding: "9px 12px", borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--border)",
                  background: enabled ? "var(--surface-raised)" : "var(--bg)",
                  cursor: "pointer",
                }}
              >
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={() => toggleCategory(categoryId)}
                  disabled={saving}
                />
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>
                    {CATEGORY_LABELS[categoryId] ?? categoryId}
                  </div>
                  <div className="mono dup-hash" style={{ fontSize: 10.5 }}>
                    {category?.extensions.slice(0, 5).join(" ")}
                    {category && category.extensions.length > 5 ? "…" : ""}
                  </div>
                </div>
              </label>
            );
          })}
        </div>
      </div>

      <div style={{ marginBottom: 20 }}>
        <div className="field-label" style={{ marginBottom: 8 }}>
          Folders to always skip
        </div>
        <div className="ask-input-row">
          <input
            value={ignoredFoldersText}
            onChange={(e) => setIgnoredFoldersText(e.target.value)}
            placeholder="node_modules, .git, build, ..."
          />
          <button className="btn" onClick={saveIgnoredFolders} disabled={saving}>
            Save
          </button>
        </div>
        <div className="section-sub" style={{ marginTop: 6 }}>
          Comma-separated folder names, matched anywhere in the tree. Windows, Program Files,
          AppData, and ProgramData are always protected regardless of this list.
        </div>
      </div>

      <div>
        <div className="field-label" style={{ marginBottom: 8 }}>
          Minimum file size to scan
        </div>
        <div className="ask-input-row" style={{ maxWidth: 280 }}>
          <input
            type="number"
            min={0}
            value={minSizeKb}
            onChange={(e) => setMinSizeKb(Number(e.target.value))}
          />
          <span className="section-sub" style={{ flexShrink: 0 }}>
            KB
          </span>
          <button className="btn" onClick={saveMinSize} disabled={saving}>
            Save
          </button>
        </div>
        <div className="section-sub" style={{ marginTop: 6 }}>
          Files smaller than this are skipped entirely — never scanned, never hashed.
        </div>
      </div>

      {saved && (
        <div className="ask-answer" style={{ color: "var(--pulse)", borderTop: "none", paddingTop: 12 }}>
          Saved — takes effect on the next scan, no restart needed.
        </div>
      )}
    </div>
  );
}
