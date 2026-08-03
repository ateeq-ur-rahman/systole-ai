import { SafeVaultPanel } from "../components/SafeVaultPanel";

export function VaultPage({ refreshSignal }: { refreshSignal: number }) {
  return (
    <div className="fade-in">
      <div className="section-head" style={{ marginBottom: 18 }}>
        <div>
          <h2 style={{ fontSize: 20, margin: 0 }}>AI Recovery Vault</h2>
          <p className="section-sub" style={{ marginTop: 4 }}>
            files protected by Systole AI for 24 hours before permanent deletion — restore any file with one click
          </p>
        </div>
      </div>
      <SafeVaultPanel refreshSignal={refreshSignal} />
    </div>
  );
}
