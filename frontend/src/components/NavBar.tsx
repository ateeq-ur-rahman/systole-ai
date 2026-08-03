import { LayoutGrid, Copy, ShieldCheck, SlidersHorizontal } from "lucide-react";

export type Tab = "dashboard" | "duplicates" | "vault" | "settings";

interface Props {
  active: Tab;
  onChange: (tab: Tab) => void;
  duplicateCount?: number;
  vaultCount?: number;
}

const TABS: { id: Tab; label: string; icon: typeof LayoutGrid }[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutGrid },
  { id: "duplicates", label: "AI Findings", icon: Copy },
  { id: "vault", label: "AI Vault", icon: ShieldCheck },
  { id: "settings", label: "AI Preferences", icon: SlidersHorizontal },
];

export function NavBar({ active, onChange, duplicateCount, vaultCount }: Props) {
  const badgeFor = (id: Tab): number | undefined => {
    if (id === "duplicates") return duplicateCount;
    if (id === "vault") return vaultCount;
    return undefined;
  };

  return (
    <nav className="nav-bar">
      {TABS.map((tab) => {
        const Icon = tab.icon;
        const isActive = active === tab.id;
        const badge = badgeFor(tab.id);
        return (
          <button
            key={tab.id}
            className={`nav-tab${isActive ? " active" : ""}`}
            onClick={() => onChange(tab.id)}
            aria-current={isActive ? "page" : undefined}
          >
            <Icon size={16} strokeWidth={2} />
            {tab.label}
            {!!badge && <span className="nav-tab-badge">{badge > 99 ? "99+" : badge}</span>}
          </button>
        );
      })}
    </nav>
  );
}
