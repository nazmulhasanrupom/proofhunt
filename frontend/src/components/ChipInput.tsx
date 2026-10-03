import { useState } from "react";
import { X } from "lucide-react";

export default function ChipInput({ value, onChange, placeholder }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string }) {
  const [text, setText] = useState("");
  const add = () => {
    const t = text.trim();
    if (t && !value.includes(t)) onChange([...value, t]);
    setText("");
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {value.map((v) => (
        <span key={v} className="chip">
          {v}
          <button onClick={() => onChange(value.filter((x) => x !== v))} aria-label={`remove ${v}`}><X size={12} /></button>
        </span>
      ))}
      <input
        className="input" style={{ width: 180 }} value={text} placeholder={placeholder ?? "type, press Enter"}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
        onBlur={add}
      />
    </div>
  );
}
