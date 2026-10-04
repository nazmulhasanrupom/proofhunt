import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useToast } from "./Toast";

type Result = { runs: { run_id: string; count: number; campaign: string }[]; companies: number; estimated_credits: number; still_filtered: { domain: string; reason: string; campaign: string }[] };

/** Confirm box for Qualify. You choose whose filters decide (size, country, keywords). */
export default function QualifyDialog({ ids, onClose, onDone }: { ids: string[]; onClose: () => void; onDone?: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const nav = useNavigate();
  const [campaign, setCampaign] = useState("");
  const { data: camps } = useQuery({ queryKey: ["campaigns"], queryFn: () => api<{ id: string; name: string }[]>("/campaigns") });
  const go = useMutation({
    mutationFn: () => api<Result>("/companies/qualify", { body: { ids, campaign_id: campaign || undefined } }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["companies"] }); qc.invalidateQueries({ queryKey: ["runs"] }); qc.invalidateQueries({ queryKey: ["company"] });
      onDone?.(); onClose();
      if (r.still_filtered.length) {
        const f = r.still_filtered[0];
        toast(`${r.still_filtered.length} still filtered out by '${f.campaign}': ${f.domain} — ${f.reason}`, true);
      }
      if (r.runs.length) { toast(`Qualifying ${r.runs.reduce((n, x) => n + x.count, 0)} compan${r.companies === 1 ? "y" : "ies"}. Watch it in Activity`); nav(`/activity?run=${r.runs[0].run_id}`); }
      else if (!r.still_filtered.length) toast("Nothing to do");
    },
    onError: (e: Error) => toast(e.message, true),
  });
  return (
    <>
      <div className="fixed inset-0" style={{ background: "rgba(0,0,0,.5)", zIndex: 70 }} onClick={onClose} />
      <div className="card fixed flex flex-col gap-3" style={{ zIndex: 71, left: "50%", top: "20vh", transform: "translateX(-50%)", width: 460, maxWidth: "92vw", background: "var(--bg-2)" }}>
        <div className="font-semibold">Qualify {ids.length} compan{ids.length === 1 ? "y" : "ies"}?</div>
        <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
          It reads their sites (pages already saved are reused), finds the contact, scores the fit, and writes the emails.
          Companies that were only filtered out are checked against the filters again, with no AI call. Pages cost no Firecrawl credit when Crawl4AI reads them.
        </div>
        <div>
          <span className="label">Whose filters decide?</span>
          <select className="select" value={campaign} onChange={(e) => setCampaign(e.target.value)}>
            <option value="">The campaign that found each company</option>
            {camps?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <div style={{ color: "var(--text-faint)", fontSize: 12, marginTop: 4 }}>Size ranges, countries and keywords come from this campaign. Edit a campaign on the Campaigns page.</div>
        </div>
        <div className="flex justify-end gap-2">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={go.isPending} onClick={() => go.mutate()}>{go.isPending ? "Starting…" : "Qualify"}</button>
        </div>
      </div>
    </>
  );
}
