import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useToast } from "../components/Toast";
import Empty from "../components/Empty";
import Skeleton from "../components/Skeleton";
import { dayTime } from "../lib/fmt";

type Row = { id: string; value: string; kind: string; reason: string | null; created_at: string };

export default function DncPage() {
  const toast = useToast();
  const qc = useQueryClient();
  const [value, setValue] = useState("");
  const { data, isLoading } = useQuery({ queryKey: ["dnc"], queryFn: () => api<Row[]>("/do-not-contact") });
  const done = () => qc.invalidateQueries({ queryKey: ["dnc"] });
  const add = useMutation({
    mutationFn: () => api("/do-not-contact", { method: "POST", body: { value } }),
    onSuccess: () => { toast("Added"); setValue(""); done(); }, onError: (e: Error) => toast(e.message, true),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/do-not-contact/${id}`, { method: "DELETE" }),
    onSuccess: () => { toast("Removed"); done(); }, onError: (e: Error) => toast(e.message, true),
  });
  return (
    <div className="page">
      <div className="page-head">
        <span>Do not contact</span>
        <form className="flex gap-2" style={{ width: 380 }} onSubmit={(e) => { e.preventDefault(); if (value.trim()) add.mutate(); }}>
          <input className="input" placeholder="email or domain" value={value} onChange={(e) => setValue(e.target.value)} />
          <button className="btn-primary" type="submit">Add</button>
        </form>
      </div>
      <div className="page-body">
        {isLoading && <Skeleton />}
        {data?.length === 0 && <Empty text="The block list is empty." />}
        {!!data?.length && (
          <table className="table">
            <thead><tr><th>Value</th><th>Kind</th><th>Reason</th><th>Added</th><th /></tr></thead>
            <tbody>
              {data.map((r) => (
                <tr key={r.id}>
                  <td>{r.value}</td><td>{r.kind}</td><td>{r.reason ?? "—"}</td><td>{dayTime(r.created_at)}</td>
                  <td className="text-right"><button className="btn btn-danger" onClick={() => { if (confirm(`Remove ${r.value}? It can be emailed again.`)) remove.mutate(r.id); }}>Remove</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
