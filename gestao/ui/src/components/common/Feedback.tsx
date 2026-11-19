import { AlertTriangle, Check, CircleHelp, X } from "lucide-react";
import { useEffect, useState } from "react";
import { nextToastId, registerToastEmitter } from "../../utils";

export function EmptyState({ icon: Icon, title, text }: { icon: typeof CircleHelp; title: string; text: string }) {
  return <div className="empty-state"><div><Icon size={20} /></div><strong>{title}</strong><span>{text}</span></div>;
}

export function ErrorBanner({ message }: { message: string }) {
  return <div className="error-banner"><AlertTriangle size={17} /><span>{message}</span></div>;
}

export function NotFound() {
  return <EmptyState icon={CircleHelp} title="Tela não encontrada" text="A página solicitada não existe." />;
}

type Toast = { id: number; message: string; kind: "success" | "error" };

export function ToastHost() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => registerToastEmitter((message, kind) => {
    const id = nextToastId();
    setItems((current) => [...current, { id, message, kind }]);
    window.setTimeout(() => setItems((current) => current.filter((item) => item.id !== id)), 4000);
  }), []);
  return <div className="toast-stack" aria-live="polite">{items.map((item) => <div key={item.id} className={`toast ${item.kind}`}><Check size={16} />{item.message}<button onClick={() => setItems((current) => current.filter((toastItem) => toastItem.id !== item.id))}><X size={15} /></button></div>)}</div>;
}
