export default function Empty({ text, action, onAction }: { text: string; action?: string; onAction?: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 py-16" style={{ color: "var(--text-muted)" }}>
      <p>{text}</p>
      {action && <button className="btn-primary" onClick={onAction}>{action}</button>}
    </div>
  );
}
