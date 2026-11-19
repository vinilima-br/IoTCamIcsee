import { useCallback, useEffect, useMemo, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Check, ChevronDown, DoorOpen, LogOut, Plus, Search, Trash2 } from "lucide-react";
import { api, fileUrl, type Page } from "../../api";
import { ErrorBanner, EmptyState } from "../../components/common/Feedback";
import { ResourceModal } from "../../components/forms/ResourceModal";
import { errorMessage, formatDate, relationshipOptions, displayValue, toast } from "../../utils";
import type { ResourceConfig, Row } from "../../types";
import { usePortariaStore } from "../../store";
import { useModoAdmin } from "../../store/useOperacaoStore";

export function ResourcePage({ config }: { config: ResourceConfig }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [editing, setEditing] = useState<Row | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [dynamicFields, setDynamicFields] = useState(config.fields);
  const draft = usePortariaStore((state) => state.quickVisitorDraft);
  const setDraft = usePortariaStore((state) => state.setQuickVisitorDraft);
  const modoAdmin = useModoAdmin();
  const isVisitor = config.endpoint === "/api/visitantes";
  const requiresAdminForDelete = ["/api/unidades", "/api/pessoas", "/api/veiculos"].includes(config.endpoint);
  const defaultValues = useMemo(() => Object.fromEntries(dynamicFields.map((field) => [field.name, field.kind === "checkbox" ? true : ""])), [dynamicFields]);
  const shape = useMemo(() => Object.fromEntries(dynamicFields.map((field) => {
    if (field.kind === "checkbox") return [field.name, z.boolean().optional()];
    const value = field.kind === "number" ? z.coerce.number().optional() : z.string().trim();
    return [field.name, field.required ? (field.kind === "number" ? z.coerce.number({ message: `${field.label} é obrigatório` }) : z.string().trim().min(1, `${field.label} é obrigatório`)) : value.optional()];
  })), [dynamicFields]);
  const formSchema = useMemo(() => z.object(shape), [shape]);
  const form = useForm<Record<string, unknown>>({ resolver: zodResolver(formSchema), defaultValues });

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({ page: String(page), page_size: "25" });
      if (query.trim()) params.set("q", query.trim());
      if (statusFilter) params.set("status", statusFilter);
      if (isVisitor && statusFilter) { params.delete("status"); params.set("status_atual", statusFilter); }
      const response = await api<Page<Row>>(`${config.endpoint}?${params}`);
      setRows(response.items);
      setTotal(response.total);
      setError("");
    } catch (loadError) {
      setError(errorMessage(loadError));
    }
  }, [config.endpoint, isVisitor, page, query, statusFilter]);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), query ? 220 : 0);
    window.addEventListener("portaria:data-changed", load);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("portaria:data-changed", load);
    };
  }, [load, query]);
  useEffect(() => {
    let live = true;
    const hydrate = async () => {
      const fields = await Promise.all(config.fields.map(async (field) => {
        if (!["unidade_id", "unidade_destino_id", "pessoa_id", "autorizado_por_id"].includes(field.name)) return field;
        try {
          const endpoint = field.name === "pessoa_id" || field.name === "autorizado_por_id" ? "/api/pessoas" : "/api/unidades";
          const options = await relationshipOptions(endpoint, (row) => field.name === "unidade_id" || field.name === "unidade_destino_id" ? `${row.bloco} · ${row.numero}` : String(row.nome));
          return { ...field, options: field.name === "pessoa_id" || field.name === "autorizado_por_id" ? [{ value: "", label: "Não informado" }, ...options] : options };
        } catch (error) {
          if (live) setError(errorMessage(error));
          return field;
        }
      }));
      if (live) setDynamicFields(fields);
    };
    void hydrate();
    return () => { live = false; };
  }, [config.fields]);

  useEffect(() => {
    if (!isVisitor || !draft) return;
    setEditing(null);
    form.reset({ ...defaultValues, ...draft });
    setDraft(null);
    setModalOpen(true);
  }, [defaultValues, draft, form, isVisitor, setDraft]);

  const openNew = () => {
    setEditing(null);
    form.reset(defaultValues);
    setError("");
    setModalOpen(true);
  };
  const openEdit = (row: Row) => {
    setEditing(row);
    const values = Object.fromEntries(dynamicFields.map((field) => {
      const value = row[field.name];
      if (field.kind === "datetime-local" && typeof value === "string") return [field.name, value.slice(0, 16)];
      if (field.kind === "checkbox") return [field.name, Boolean(value)];
      return [field.name, value ?? ""];
    }));
    form.reset(values);
    setError("");
    setModalOpen(true);
  };
  const onSubmit = async (values: Record<string, unknown>) => {
    setSaving(true);
    setError("");
    try {
      const payload: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(values)) {
        if (value === "" || value === undefined) payload[key] = null;
        else if (["unidade_id", "pessoa_id", "unidade_destino_id", "autorizado_por_id"].includes(key)) payload[key] = Number(value) || null;
        else if (key === "validade_inicio" || key === "validade_fim") payload[key] = value ? new Date(String(value)).toISOString() : null;
        else payload[key] = value;
      }
      const endpoint = editing ? `${config.endpoint}/${editing.id}` : config.endpoint;
      await api(endpoint, { method: editing ? "PUT" : "POST", body: JSON.stringify(payload) });
      setEditing(null);
      setModalOpen(false);
      await load();
      toast(editing ? "Cadastro atualizado." : "Cadastro salvo.", "success");
    } catch (submitError) {
      setError(errorMessage(submitError));
    } finally {
      setSaving(false);
    }
  };
  const remove = async (row: Row) => {
    if (requiresAdminForDelete && !modoAdmin) return;
    if (!window.confirm(`Excluir o cadastro #${row.id}?`)) return;
    try {
      await api(`${config.endpoint}/${row.id}`, { method: "DELETE" });
      await load();
      toast("Cadastro excluído.", "success");
    } catch (deleteError) {
      setError(errorMessage(deleteError));
    }
  };
  const markExit = async (row: Row) => {
    try {
      await api(`/api/visitantes/${row.id}/saida`, { method: "POST" });
      await load();
      toast("Saída registrada.", "success");
    } catch (exitError) {
      setError(errorMessage(exitError));
    }
  };
  const markEntry = async (row: Row) => {
    try {
      await api(`/api/visitantes/${row.id}/entrada`, { method: "POST" });
      await load();
      toast("Entrada registrada.", "success");
    } catch (entryError) {
      setError(errorMessage(entryError));
    }
  };
  const pickup = async (row: Row) => {
    const name = window.prompt("Nome de quem retirou a encomenda:");
    if (!name?.trim()) return;
    try {
      await api(`/api/encomendas/${row.id}/retirada`, { method: "POST", body: JSON.stringify({ retirado_por: name.trim() }) });
      await load();
      toast("Retirada registrada.", "success");
    } catch (pickupError) {
      setError(errorMessage(pickupError));
    }
  };

  return <section className="resource-card">
    <div className="resource-heading"><div><h2>{config.title}</h2><p>{config.description}</p></div><button className="button-primary" onClick={openNew}><Plus size={17} /> Novo cadastro</button></div>
    <div className="resource-toolbar"><label className="search-field"><Search size={16} /><input data-quick-search value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder={config.search ?? "Buscar cadastro"} /></label>
      {(isVisitor || config.endpoint === "/api/encomendas") && <select className="filter-select" value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(1); }}><option value="">Todos os status</option>{isVisitor ? <><option value="no_condominio">No condomínio</option><option value="saiu">Saiu</option></> : <><option value="pendente">Pendente</option><option value="retirada">Retirada</option></>}</select>}
      <span className="result-count">{total} registros</span>
    </div>
    {error && <ErrorBanner message={error} />}
    <div className="table-wrap"><table><thead><tr>{config.columns.map((column) => <th key={column.key}>{column.label}</th>)}<th className="actions-heading">Ações</th></tr></thead><tbody>
      {rows.map((row) => <tr key={row.id}>{config.columns.map((column) => <td key={column.key}><Cell value={row[column.key]} row={row} field={column.key} /></td>)}<td><div className="row-actions">
        {isVisitor && row.status_atual === "no_condominio" && <button className="mini-action positive" title="Registrar saída" onClick={() => void markExit(row)}><LogOut size={15} /></button>}
          {isVisitor && row.status_atual === "saiu" && row.tipo_acesso === "recorrente" && <button className="mini-action positive" title="Registrar entrada recorrente" onClick={() => void markEntry(row)}><DoorOpen size={15} /></button>}
          {config.endpoint === "/api/encomendas" && row.status === "pendente" && <button className="mini-action positive" title="Registrar retirada" onClick={() => void pickup(row)}><Check size={15} /></button>}
        <button className="mini-action" title="Editar" onClick={() => openEdit(row)}><ChevronDown size={15} /></button><button className="mini-action destructive" title={requiresAdminForDelete && !modoAdmin ? "Requer Modo Administrador" : "Excluir"} aria-label={requiresAdminForDelete && !modoAdmin ? "Excluir: requer Modo Administrador" : "Excluir"} disabled={requiresAdminForDelete && !modoAdmin} onClick={() => void remove(row)}><Trash2 size={15} /></button>
      </div></td></tr>)}
      {!rows.length && <tr><td colSpan={config.columns.length + 1}><EmptyState icon={Search} title="Nenhum resultado" text={query ? "Tente outra busca ou limpe os filtros." : "Use “Novo cadastro” para registrar o primeiro item."} /></td></tr>}
    </tbody></table></div>
    <div className="pagination"><span>Exibindo {rows.length ? (page - 1) * 25 + 1 : 0}–{Math.min(page * 25, total)} de {total}</span><div><button className="button-quiet small" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Anterior</button><span className="page-number">{page}</span><button className="button-quiet small" disabled={page * 25 >= total} onClick={() => setPage((value) => value + 1)}>Próxima</button></div></div>
    {modalOpen && <ResourceModal
      title={config.title}
      editing={Boolean(editing)}
      fields={dynamicFields}
      form={form}
      saving={saving}
      error={error}
      onClose={() => { setEditing(null); setModalOpen(false); }}
      onSubmit={onSubmit}
    />}
  </section>;
}

function Cell({ value, row, field }: { value: unknown; row: Row; field: string }) {
  if (field === "ativo" || field === "status" || field === "status_atual") {
    const active = field === "ativo" ? Boolean(value) : ["pendente", "no_condominio"].includes(String(value));
    const label = field === "ativo" ? (active ? "Ativo" : "Inativo") : displayValue(value);
    return <span className={`status-pill ${active ? "good" : "muted"}`}>{label}</span>;
  }
  if (field === "unidade_id" || field === "unidade_destino_id") return <span className="unit-tag">Un. {String(value ?? "—")}</span>;
  if (field.includes("data_") || field.includes("validade_")) return <span>{value ? formatDate(value) : "—"}</span>;
  if (field === "placa") return <span className="plate-chip">{String(value ?? "—")}</span>;
  if (field === "foto_path") return <span>{row.foto_path ? <img className="table-avatar" src={fileUrl(String(row.foto_path))} alt="" /> : "—"}</span>;
  return <span>{displayValue(value)}</span>;
}
