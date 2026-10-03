/** Small grey bar chart. One series, hover shows the exact number. */
export default function BarChart({ data, unit }: { data: { label: string; value: number }[]; unit: string }) {
  const peak = Math.max(0, ...data.map((d) => d.value));
  const max = Math.max(1, peak);
  return (
    <div>
      <div className="flex items-end gap-px" style={{ height: 96 }}>
        {data.map((d) => (
          <div key={d.label} title={`${d.label}: ${d.value} ${unit}`} className="flex-1"
            style={{ height: `${Math.max(d.value ? 4 : 1, (d.value / max) * 100)}%`, background: d.value ? "var(--text-muted)" : "var(--bg-4)", borderRadius: 1 }} />
        ))}
      </div>
      <div className="mt-1 flex justify-between" style={{ fontSize: 11, color: "var(--text-faint)" }}>
        <span>{data[0]?.label.slice(5)}</span><span>peak {peak} {unit}</span><span>{data[data.length - 1]?.label.slice(5)}</span>
      </div>
    </div>
  );
}
