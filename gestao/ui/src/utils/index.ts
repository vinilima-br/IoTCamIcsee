import { api, type Page } from "../api";
import type { Row } from "../types";

export async function relationshipOptions(endpoint: string, label: (row: Row) => string) {
  const response = await api<Page<Row>>(`${endpoint}?page_size=100`);
  return response.items.map((row) => ({ value: row.id, label: label(row) }));
}

export function selectOptions(items: [string, string][]) {
  return items.map(([value, label]) => ({ value, label }));
}

export function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Ocorreu um erro inesperado.";
}

export function displayValue(value: unknown): string {
  if (value === undefined || value === null || value === "") return "—";
  const labels: Record<string, string> = {
    proprietario: "Proprietário", inquilino: "Inquilino", dependente: "Dependente",
    funcionario_unidade: "Funcionário", apartamento: "Apartamento", avulso: "Avulso",
    recorrente: "Recorrente", no_condominio: "No condomínio", saiu: "Saiu",
    pendente: "Pendente", retirada: "Retirada", entrada: "Entrada", saida: "Saída",
    reconhecimento_facial: "Reconhecimento facial", alerta_desconhecido: "Alerta desconhecido",
    alerta_camera: "Alerta da câmera", camera: "Câmera", facial: "Facial",
    manual: "Manual", placa: "Placa", carro: "Carro", moto: "Moto", outro: "Outro",
  };
  return labels[String(value)] ?? String(value);
}

export function formatDate(value: unknown) {
  if (!value) return "—";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

type ToastKind = "success" | "error";
let toastId = 0;
let emitToast: (message: string, kind: ToastKind) => void = () => undefined;

export function toast(message: string, kind: ToastKind = "success") {
  emitToast(message, kind);
}

export function registerToastEmitter(emit: typeof emitToast) {
  emitToast = emit;
  return () => {
    if (emitToast === emit) emitToast = () => undefined;
  };
}

export function nextToastId() {
  toastId += 1;
  return toastId;
}
