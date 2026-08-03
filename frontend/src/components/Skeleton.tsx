export function SkeletonCards({ count = 4 }: { count?: number }) {
  return (
    <div className="widget-grid" aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="skeleton skeleton-card" />
      ))}
    </div>
  );
}

export function SkeletonRows({ count = 3 }: { count?: number }) {
  return (
    <div aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="skeleton skeleton-row" style={{ width: `${92 - i * 8}%` }} />
      ))}
    </div>
  );
}
