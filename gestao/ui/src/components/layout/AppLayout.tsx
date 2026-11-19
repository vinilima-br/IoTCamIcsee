import type { ReactNode } from "react";
import { AlertTriangle, Check } from "lucide-react";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";
import { useOperacaoStore } from "../../store/useOperacaoStore";
import { formatDate } from "../../utils";

export function AppLayout({ title, children }: { title: string; children: ReactNode }) {
  const recadoTurno = useOperacaoStore((state) => state.recadoTurno);
  const dispensarRecadoTurno = useOperacaoStore((state) => state.dispensarRecadoTurno);
  return <div className="app-shell">
    <Sidebar />
    <main className="main-area">
      {recadoTurno && <aside className="turn-note-banner" role="status">
        <AlertTriangle size={19} />
        <div className="turn-note-content"><strong>Recado de passagem de turno</strong><p>{recadoTurno.mensagem}</p><small>De {recadoTurno.autor} · {formatDate(recadoTurno.dataHora)}</small></div>
        <button type="button" className="turn-note-dismiss" onClick={dispensarRecadoTurno}><Check size={15} /> Ciente</button>
      </aside>}
      <Header title={title} />
      <div className="page-content">{children}</div>
    </main>
  </div>;
}
