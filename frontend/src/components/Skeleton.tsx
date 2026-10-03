export default function Skeleton({ rows = 4 }: { rows?: number }) {
  return <>{Array.from({ length: rows }).map((_, i) => <div key={i} className="skeleton" />)}</>;
}
