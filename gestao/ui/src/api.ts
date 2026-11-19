export type Page<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};

export type CameraInfo = {
  id: string;
  nome: string;
  ip?: string | null;
  online: boolean;
  pausada?: boolean;
  largura?: number;
  altura?: number;
  lente_det?: string;
  tem_som?: boolean;
  fps: number;
  erro: string | null;
  ptz?: boolean | null;
};

export type PortariaEvent = {
  type: string;
  data: Record<string, unknown>;
};

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = `Falha ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail ?? message;
    } catch {
      message = response.statusText || message;
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function fileUrl(path?: string | null): string | undefined {
  if (!path) return undefined;
  return `/api/arquivos/${path.replace(/^\/+/, "")}`;
}

export function websocketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/eventos`;
}
