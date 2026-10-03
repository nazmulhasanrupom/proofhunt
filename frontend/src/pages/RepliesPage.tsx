import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import Empty from "../components/Empty";
import Skeleton from "../components/Skeleton";
import { markRepliesSeen } from "../lib/unread";

type Reply = {
  id: string; from_email: string; received_at: string; snippet: string; body: string; classification: string | null;
  leads: { id: string; stage: string; companies: { domain: string; name: string }; people: { name: string; email: string } };
};

const HOT = "interested";

export default function RepliesPage() {
  const { data, isLoading } = useQuery({ queryKey: ["replies"], queryFn: () => api<Reply[]>("/replies"), refetchInterval: 30000 });
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => { markRepliesSeen(data?.[0]?.received_at); }, [data]);
  return (
    <div className="page">
      <div className="page-head"><span>Replies</span></div>
      <div className="page-body">
        {isLoading && <Skeleton />}
        {!isLoading && !data?.length && <Empty text="No replies yet." />}
        <div className="flex flex-col gap-2">
          {data?.map((r) => (
            <div key={r.id} className="card" style={{ padding: 12, cursor: "pointer" }} onClick={() => setOpen(open === r.id ? null : r.id)}>
              <div className="flex items-center gap-3">
                <span className="dot" style={{ background: r.classification === HOT ? "var(--ok)" : "var(--text-faint)", marginRight: 0 }} />
                <span className="font-medium">{r.leads.companies.name || r.leads.companies.domain}</span>
                <span style={{ color: "var(--text-muted)" }}>{r.from_email}</span>
                <span className="chip">{r.classification ?? "not classified"}</span>
                <span className="flex-1" />
                <span style={{ color: "var(--text-faint)", fontSize: 12 }}>{new Date(r.received_at).toLocaleString()}</span>
              </div>
              {open === r.id ? (
                <pre className="mt-3" style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: 13 }}>{r.body}</pre>
              ) : (
                <div className="mt-1" style={{ color: "var(--text-muted)", fontSize: 13 }}>{r.snippet}</div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
