import { Bell } from "lucide-react";

export function Header({ title }: { title: string }) {
  return <header className="topbar">
    <div><div className="eyebrow">CONDOMÍNIO • GUARITA</div><h1>{title}</h1></div>
    <div className="topbar-right">
      <div className="local-badge"><span /> Sistema local</div>
      <div className="clock">{new Date().toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "short" })}</div>
      <button className="icon-button" title="Alertas ativos" onClick={() => document.getElementById("alert-feed")?.scrollIntoView({ behavior: "smooth" })}><Bell size={19} /><span className="notification-dot" /></button>
    </div>
  </header>;
}
