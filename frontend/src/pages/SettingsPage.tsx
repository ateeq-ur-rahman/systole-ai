import { SettingsPanel } from "../components/SettingsPanel";

export function SettingsPage() {
  return (
    <div className="fade-in">
      <div className="section-head" style={{ marginBottom: 18 }}>
        <div>
          <h2 style={{ fontSize: 20, margin: 0 }}>AI Preferences</h2>
          <p className="section-sub" style={{ marginTop: 4 }}>
            control what Systole AI scans, everywhere in the app
          </p>
        </div>
      </div>
      <SettingsPanel />
    </div>
  );
}
