import { useNavigate } from "react-router-dom";
import Empty from "./Empty";

/** Shown instead of a page that needs a profile, before the first one exists. */
export default function NoProfile({ title }: { title: string }) {
  const go = useNavigate();
  return (
    <div className="page">
      <div className="page-head"><span>{title}</span></div>
      <Empty text="Create a profile first. A profile is one CV, and every section shows the data of the profile you pick."
        action="Create profile" onAction={() => go("/profile?new=1")} />
    </div>
  );
}
