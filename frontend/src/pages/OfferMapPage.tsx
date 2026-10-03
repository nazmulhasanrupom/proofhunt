import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { api } from "../api/client";
import { useToast } from "../components/Toast";
import Skeleton from "../components/Skeleton";
import Empty from "../components/Empty";

type Signal = { id?: string; name: string; description: string; detector_type: string; config: Record<string, unknown>; weight: number; active: boolean };
type Row = { id?: string; service: string; problems: string[]; proof: string[]; ideal_customer: { industry?: string; size?: string[] }; active: boolean; signals: Signal[] };
type MapData = { profile_id: string | null; rows: Row[] };

const KEY: Record<string, string> = { phrase: "phrases", tech_absent: "tech", tech_present: "tech", hiring_role: "roles", llm: "question" };

function cfgText(s: Signal): string {
  const v = s.config[KEY[s.detector_type]];
  return Array.isArray(v) ? v.join(", ") : String(v ?? "");
}
function cfgFrom(type: string, text: string): Record<string, unknown> {
  return type === "llm" ? { question: text } : { [KEY[type]]: text.split(",").map((x) => x.trim()).filter(Boolean) };
}
const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

export default function OfferMapPage() {
  const toast = useToast();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["offer-map"], queryFn: () => api<MapData>("/offer-map") });
  const [rows, setRows] = useState<Row[]>([]);
  useEffect(() => { if (data) setRows(data.rows); }, [data]);

  const save = useMutation({
    mutationFn: () => api<Row[]>("/offer-map", { method: "PUT", body: { profile_id: data!.profile_id, rows } }),
    onSuccess: () => { toast("Offer map saved"); qc.invalidateQueries({ queryKey: ["offer-map"] }); },
    onError: (e: Error) => toast(e.message, true),
  });

  const setRow = (i: number, patch: Partial<Row>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const setSig = (i: number, k: number, patch: Partial<Signal>) =>
    setRow(i, { signals: rows[i].signals.map((s, j) => (j === k ? { ...s, ...patch } : s)) });

  return (
    <div className="page">
      <div className="page-head">
        <span>Offer map</span>
        {rows.length > 0 && <button className="btn-primary" disabled={save.isPending} onClick={() => save.mutate()}>Save</button>}
      </div>
      <div className="page-body flex flex-col gap-4">
        {isLoading && <Skeleton />}
        {!isLoading && rows.length === 0 && <Empty text="No offer map yet. Upload a CV first, then generate it." />}
        {rows.map((r, i) => (
          <div key={r.id ?? i} className="card flex flex-col gap-3" style={{ opacity: r.active ? 1 : 0.5 }}>
            <div className="flex items-center gap-2">
              <input className="input font-semibold" value={r.service} onChange={(e) => setRow(i, { service: e.target.value })} />
              <label className="flex items-center gap-1 text-xs" style={{ whiteSpace: "nowrap" }}>
                <input type="checkbox" checked={r.active} onChange={(e) => setRow(i, { active: e.target.checked })} /> on
              </label>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><span className="label">Problems (one per line)</span>
                <textarea className="textarea" key={r.id ?? i} defaultValue={r.problems.join("\n")} onBlur={(e) => setRow(i, { problems: lines(e.target.value) })} /></div>
              <div><span className="label">Proof (one per line)</span>
                <textarea className="textarea" key={r.id ?? i} defaultValue={r.proof.join("\n")} onBlur={(e) => setRow(i, { proof: lines(e.target.value) })} /></div>
            </div>
            <div><span className="label">Ideal customer industry</span>
              <input className="input" value={r.ideal_customer.industry ?? ""} onChange={(e) => setRow(i, { ideal_customer: { ...r.ideal_customer, industry: e.target.value } })} /></div>
            <div>
              <span className="label">Signals</span>
              <div className="flex flex-col gap-2">
                {r.signals.map((s, k) => (
                  <div key={s.id ?? k} className="flex items-center gap-2" style={{ opacity: s.active ? 1 : 0.5 }}>
                    <input className="input" style={{ width: 200 }} placeholder="name" value={s.name} onChange={(e) => setSig(i, k, { name: e.target.value })} />
                    <select className="select" style={{ width: 130 }} value={s.detector_type}
                      onChange={(e) => setSig(i, k, { detector_type: e.target.value, config: {} })}>
                      {Object.keys(KEY).map((t) => <option key={t}>{t}</option>)}
                    </select>
                    <input className="input" placeholder={s.detector_type === "llm" ? "question for the LLM" : "comma separated"} key={`${s.id ?? k}-${s.detector_type}`} defaultValue={cfgText(s)}
                      onBlur={(e) => setSig(i, k, { config: cfgFrom(s.detector_type, e.target.value) })} />
                    <input type="checkbox" checked={s.active} onChange={(e) => setSig(i, k, { active: e.target.checked })} />
                    <button onClick={() => setRow(i, { signals: r.signals.filter((_, j) => j !== k) })} aria-label="remove signal"><Trash2 size={16} /></button>
                  </div>
                ))}
                <button className="btn" style={{ alignSelf: "flex-start" }}
                  onClick={() => setRow(i, { signals: [...r.signals, { name: "", description: "", detector_type: "phrase", config: {}, weight: 1, active: true }] })}>
                  <Plus size={14} className="inline" /> Add signal
                </button>
              </div>
            </div>
          </div>
        ))}
        {rows.length > 0 && (
          <button className="btn" style={{ alignSelf: "flex-start" }}
            onClick={() => setRows([...rows, { service: "New service", problems: [], proof: [], ideal_customer: {}, active: true, signals: [] }])}>
            <Plus size={14} className="inline" /> Add service
          </button>
        )}
      </div>
    </div>
  );
}
