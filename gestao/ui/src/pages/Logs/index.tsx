import { useCallback, useEffect, useState } from "react";
import { FileClock, Search, ShieldCheck } from "lucide-react";
import { api, fileUrl, type Page } from "../../api";
import { ErrorBanner, EmptyState } from "../../components/common/Feedback";
import { displayValue, errorMessage, formatDate } from "../../utils";
import type { Row } from "../../types";

export default function LogsPage() {
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [eventType, setEventType] = useState("");
  const [method, setMethod] = useState("");
  const [unit, setUnit] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({ page: String(page), page_size: "25" });
      if (q) params.set("q", q); if (eventType) params.set("tipo_evento", eventType); if (method) params.set("metodo", method);
      if (unit) params.set("unidade_id", unit);
      if (start) params.set("inicio", new Date(start).toISOString());
      if (end) params.set("fim", new Date(end).toISOString());
      const result = await api<Page<Row>>(`/api/logs?${params}`);
      setRows(result.items); setTotal(result.total); setError("");
    } catch (loadError) { setError(errorMessage(loadError)); }
  }, [end, eventType, method, page, q, start, unit]);
  useEffect(() => { void load(); window.addEventListener("portaria:data-changed", load); return () => window.removeEventListener("portaria:data-changed", load); }, [load]);
  return <div className="stack-lg"><section className="page-intro"><div><div className="eyebrow">RASTREABILIDADE</div><h2>Logs de acesso</h2><p>Consulte entradas, saídas e alertas com snapshot e método de identificação.</p></div><div className="audit-stamp"><ShieldCheck size={16} /> REGISTROS LOCAIS</div></section>
    <section className="resource-card"><div className="filter-grid">
      <label className="search-field"><Search size={16} /><input data-quick-search value={q} onChange={(event) => { setQ(event.target.value); setPage(1); }} placeholder="Nome da pessoa" /></label>
      <input className="filter-select" value={unit} onChange={(event) => setUnit(event.target.value)} placeholder="ID da unidade" type="number" min="1" />
      <select className="filter-select" value={eventType} onChange={(event) => setEventType(event.target.value)}><option value="">Todos os eventos</option><option value="entrada">Entrada</option><option value="saida">Saída</option><option value="reconhecimento_facial">Reconhecimento facial</option><option value="alerta_desconhecido">Alerta desconhecido</option><option value="alerta_camera">Alerta da câmera</option></select>
      <select className="filter-select" value={method} onChange={(event) => setMethod(event.target.value)}><option value="">Todos os métodos</option><option value="facial">Facial</option><option value="manual">Manual</option><option value="placa">Placa</option></select>
      <input className="filter-select" type="datetime-local" value={start} onChange={(event) => setStart(event.target.value)} aria-label="Data inicial" />
      <input className="filter-select" type="datetime-local" value={end} onChange={(event) => setEnd(event.target.value)} aria-label="Data final" />
    </div>{error && <ErrorBanner message={error} />}<LogTable rows={rows} />
      <div className="pagination"><span>{total} eventos encontrados</span><div><button className="button-quiet small" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Anterior</button><span className="page-number">{page}</span><button className="button-quiet small" disabled={page * 25 >= total} onClick={() => setPage((value) => value + 1)}>Próxima</button></div></div>
    </section>
  </div>;
}

export function LogTable({ rows, compact = false }: { rows: Row[]; compact?: boolean }) {
  return <div className="table-wrap"><table><thead><tr><th>Momento</th><th>Pessoa / visitante</th><th>Unidade</th><th>Evento</th><th>Método</th><th>Snapshot</th></tr></thead><tbody>{rows.map((row) => {
    const details = typeof row.detalhes === "object" && row.detalhes ? row.detalhes as Record<string, unknown> : {};
    const name = row.pessoa_id ? `Pessoa #${row.pessoa_id}` : row.visitante_id ? `Visitante #${row.visitante_id}` : String(details.nome_reconhecido ?? "Desconhecido");
    return <tr key={row.id}><td><span className="log-time">{formatDate(row.timestamp)}</span></td><td><strong className="table-primary">{name}</strong></td><td>{String(details.unidade_id ?? "—")}</td><td><span className={`event-pill ${row.tipo_evento === "entrada" ? "entry" : row.tipo_evento === "saida" ? "exit" : "alert"}`}>{displayValue(row.tipo_evento)}</span></td><td><span className="method-chip">{displayValue(row.metodo)}</span></td><td>{row.snapshot_path ? <a href={fileUrl(String(row.snapshot_path))} target="_blank" rel="noreferrer" className="snapshot-link"><img src={fileUrl(String(row.snapshot_path))} alt="Snapshot" /><span>Ver captura</span></a> : <span className="dim">—</span>}</td></tr>;
  })}{!rows.length && <tr><td colSpan={6}><EmptyState icon={FileClock} title="Nenhum log encontrado" text={compact ? "Os acessos registrados aparecerão aqui." : "Ajuste os filtros ou aguarde novos registros."} /></td></tr>}</tbody></table></div>;
}
