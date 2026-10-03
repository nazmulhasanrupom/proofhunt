import {
  LayoutDashboard, Activity, FileText, Map, Megaphone, Play, Building2,
  Users, ClipboardCheck, Send, MessageSquare, BarChart3, Ban, Settings,
  type LucideIcon,
} from "lucide-react";

export type NavItem = { path: string; label: string; icon: LucideIcon; hint: string; action?: string };
export type NavGroup = { label: string; items: NavItem[] };

export const nav: NavGroup[] = [
  { label: "Overview", items: [
    { path: "/", label: "Dashboard", icon: LayoutDashboard, hint: "No data yet." },
    { path: "/activity", label: "Activity", icon: Activity, hint: "No run is active." },
  ]},
  { label: "Setup", items: [
    { path: "/profile", label: "Profile & CV", icon: FileText, hint: "No CV yet.", action: "Upload CV" },
    { path: "/offer-map", label: "Offer map", icon: Map, hint: "No offer map yet.", action: "Generate offer map" },
  ]},
  { label: "Hunt", items: [
    { path: "/campaigns", label: "Campaigns", icon: Megaphone, hint: "No campaigns yet.", action: "New campaign" },
    { path: "/runs", label: "Runs", icon: Play, hint: "No runs yet." },
  ]},
  { label: "CRM", items: [
    { path: "/companies", label: "Companies", icon: Building2, hint: "No companies yet." },
    { path: "/leads", label: "Leads", icon: Users, hint: "No leads yet." },
    { path: "/review", label: "Review queue", icon: ClipboardCheck, hint: "No drafts to review." },
    { path: "/outbox", label: "Outbox", icon: Send, hint: "No messages yet." },
    { path: "/replies", label: "Replies", icon: MessageSquare, hint: "No replies yet." },
  ]},
  { label: "System", items: [
    { path: "/usage", label: "Usage & credits", icon: BarChart3, hint: "No usage yet." },
    { path: "/do-not-contact", label: "Do not contact", icon: Ban, hint: "The block list is empty.", action: "Add entry" },
    { path: "/settings", label: "Settings", icon: Settings, hint: "Settings." },
  ]},
];
