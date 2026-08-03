import { useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";

interface Props {
  label?: string;
  children: ReactNode;
}

/** Hides technical details (hashes, full paths, internal IDs) behind a
 * quiet toggle, per "hide technical information by default." */
export function Advanced({ label = "Developer Tools", children }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        className={`advanced-toggle${open ? " open" : ""}`}
        onClick={() => setOpen((v) => !v)}
      >
        <ChevronRight size={12} strokeWidth={2.5} />
        {label}
      </button>
      {open && <div className="advanced-body fade-in">{children}</div>}
    </div>
  );
}
