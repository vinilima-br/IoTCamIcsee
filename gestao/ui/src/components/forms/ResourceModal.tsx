import { Check, LoaderCircle, X } from "lucide-react";
import type { UseFormReturn } from "react-hook-form";
import { api } from "../../api";
import type { Field } from "../../types";
import { errorMessage, toast } from "../../utils";

type ResourceModalProps = {
  title: string;
  editing: boolean;
  fields: Field[];
  form: UseFormReturn<Record<string, unknown>>;
  saving: boolean;
  error: string;
  onClose: () => void;
  onSubmit: (values: Record<string, unknown>) => void;
};

export function ResourceModal({ title, editing, fields, form, saving, error, onClose, onSubmit }: ResourceModalProps) {
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="modal-panel">
      <div className="modal-heading">
        <div><div className="eyebrow">{editing ? "EDITAR REGISTRO" : "NOVO REGISTRO"}</div><h2>{editing ? `Editar ${title.toLowerCase()}` : `Cadastrar ${title.toLowerCase()}`}</h2></div>
        <button className="icon-button" onClick={onClose} aria-label="Fechar"><X size={19} /></button>
      </div>
      <form className="form-grid" onSubmit={form.handleSubmit(onSubmit)}>
        {fields.map((field, index) => <div className="form-entry span-two" key={field.name}>
          {field.section && (index === 0 || fields[index - 1]?.section !== field.section) && <div className="form-section-heading span-two">{field.section}</div>}
          <FormField field={field} form={form} />
        </div>)}
        {error && <div className="form-error span-two">{error}</div>}
        <div className="form-footer span-two">
          <button type="button" className="button-secondary" onClick={onClose}>Cancelar</button>
          <button type="submit" className="button-primary" disabled={saving}>
            {saving ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />}
            {saving ? "Salvando..." : editing ? "Salvar alterações" : "Cadastrar"}
          </button>
        </div>
      </form>
    </div>
  </div>;
}

function FormField({ field, form }: { field: Field; form: UseFormReturn<Record<string, unknown>> }) {
  const { register, setValue, watch, formState: { errors } } = form;
  const error = errors[field.name]?.message;
  const inputId = `field-${field.name}`;
  const wrapClass = `form-field ${field.wide ? "span-two" : ""} ${field.kind === "checkbox" ? "checkbox-field" : ""}`;
  if (field.kind === "checkbox") return <label className={wrapClass} htmlFor={inputId}><input id={inputId} type="checkbox" {...register(field.name)} /><span>{field.label}</span></label>;
  if (field.kind === "photo") return <div className={wrapClass}><label htmlFor={inputId}>{field.label}</label><div className="photo-upload"><input id={inputId} type="file" accept="image/jpeg,image/png,image/webp" onChange={async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const body = new FormData(); body.append("file", file);
    try { const result = await api<{ foto_path: string }>("/api/arquivos/cadastro", { method: "POST", body }); setValue(field.name, result.foto_path, { shouldValidate: true }); toast("Foto carregada.", "success"); }
    catch (uploadError) { toast(errorMessage(uploadError), "error"); }
  }} />{watch(field.name) ? <span className="upload-success"><Check size={14} /> Foto pronta</span> : <span className="field-hint">JPG, PNG ou WEBP • até 8 MB</span>}</div>{error && <small className="field-error">{String(error)}</small>}</div>;
  return <div className={wrapClass}><label htmlFor={inputId}>{field.label}{field.required && <span className="required-mark"> *</span>}</label>
    {field.kind === "select" ? <select id={inputId} {...register(field.name)}><option value="">Selecione</option>{field.options?.map((option) => <option key={String(option.value)} value={option.value}>{option.label}</option>)}</select> :
      field.kind === "textarea" ? <textarea id={inputId} rows={3} placeholder={field.placeholder} {...register(field.name)} /> :
        <input id={inputId} type={field.kind ?? "text"} placeholder={field.placeholder} {...register(field.name)} />}
    {field.hint && <small className="field-hint">{field.hint}</small>}
    {error && <small className="field-error">{String(error)}</small>}
  </div>;
}
