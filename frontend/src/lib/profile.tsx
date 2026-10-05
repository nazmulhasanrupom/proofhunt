import { createContext, useContext, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { api, setActiveProfile } from "../api/client";

export type ProfileKind = "freelancer" | "ima";
export const KIND_LABEL: Record<ProfileKind, string> = { freelancer: "Freelancer", ima: "IMA" };
export type Profile = { id: string; name: string; kind: ProfileKind; file_name: string | null; headline: string | null; created_at: string };
type Ctx = {
  profiles: Profile[]; current: Profile | null; select: (id: string) => void;
  isLoading: boolean; error: Error | null; reload: () => void;
};

const KEY = "profileId";
const read = () => { try { return localStorage.getItem(KEY) ?? ""; } catch { return ""; } };
const write = (id: string) => { try { localStorage.setItem(KEY, id); } catch { /* private mode: the pick is not remembered */ } };

const ProfileCtx = createContext<Ctx>({ profiles: [], current: null, select: () => {}, isLoading: true, error: null, reload: () => {} });
export const useProfiles = () => useContext(ProfileCtx);

/** The profile you picked in the top bar. Every call to the API carries it, and every query is cached per profile (see main.tsx). */
export function ProfileProvider({ children }: { children: ReactNode }) {
  const nav = useNavigate();
  const { pathname } = useLocation();
  const q = useQuery({ queryKey: ["profiles"], queryFn: () => api<Profile[]>("/profiles") });
  const [picked, setPicked] = useState(read);
  const profiles = q.data ?? [];
  // A pick that no longer exists (deleted, or another browser) falls back to the first profile.
  const current = profiles.find((p) => p.id === picked) ?? profiles[0] ?? null;
  // Set while rendering, not in an effect: the effects of the pages below run before ours, and their first calls must already carry this id.
  setActiveProfile(current?.id ?? "");

  const select = (id: string) => {
    if (id === current?.id) return;
    write(id);
    setActiveProfile(id);
    setPicked(id);
    nav(pathname, { replace: true });  // drop ?id= and ?run=: they point into the old profile
  };
  return (
    <ProfileCtx.Provider value={{ profiles, current, select, isLoading: q.isLoading, error: q.error, reload: () => { void q.refetch(); } }}>
      {children}
    </ProfileCtx.Provider>
  );
}
