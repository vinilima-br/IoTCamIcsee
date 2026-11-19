export type Row = Record<string, unknown> & { id: number };

export type FieldKind = "text" | "number" | "select" | "textarea" | "checkbox" | "datetime-local" | "photo";

export type Field = {
  name: string;
  label: string;
  kind?: FieldKind;
  required?: boolean;
  options?: { label: string; value: string | number }[];
  placeholder?: string;
  wide?: boolean;
  section?: string;
  hint?: string;
};

export type ResourceConfig = {
  title: string;
  description: string;
  endpoint: string;
  fields: Field[];
  columns: { key: string; label: string }[];
  search?: string;
};
