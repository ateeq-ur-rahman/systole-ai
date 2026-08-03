import { useMemo } from "react";

interface PulseTraceProps {
  health: "ok" | "warning" | "critical" | "unknown";
  width?: number;
  height?: number;
}

/**
 * The brand signature: a live EKG-style trace representing drive health.
 * A calm sine-ish baseline with a single "systole" spike — literal to the
 * product name. Amplitude/color respond to health so the one animated
 * element in the UI also carries real information, not just decoration.
 */
export function PulseTrace({ health, width = 220, height = 48 }: PulseTraceProps) {
  const color =
    health === "critical" ? "var(--critical)" : health === "warning" ? "var(--warn)" : "var(--pulse)";

  const path = useMemo(() => {
    const w = width;
    const h = height;
    const mid = h / 2;
    const spike = health === "critical" ? h * 0.85 : health === "warning" ? h * 0.6 : h * 0.42;
    return `M0,${mid}
      L${w * 0.28},${mid}
      L${w * 0.34},${mid - spike * 0.15}
      L${w * 0.39},${mid + spike * 0.5}
      L${w * 0.44},${mid - spike}
      L${w * 0.49},${mid + spike * 0.35}
      L${w * 0.54},${mid}
      L${w},${mid}`;
  }, [health, width, height]);

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`Drive health: ${health}`}
      style={{ overflow: "visible" }}
    >
      <path
        d={path}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
        pathLength={1}
        style={{
          strokeDasharray: 1,
          strokeDashoffset: 1,
          animation: "pulse-draw 2.6s ease-in-out infinite",
        }}
      />
      <style>{`
        @keyframes pulse-draw {
          0% { stroke-dashoffset: 1; }
          45% { stroke-dashoffset: 0; }
          100% { stroke-dashoffset: -1; }
        }
      `}</style>
    </svg>
  );
}
