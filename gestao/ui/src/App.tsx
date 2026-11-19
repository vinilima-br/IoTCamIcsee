import { useEffect } from "react";
import { Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { websocketUrl, type PortariaEvent } from "./api";
import { AppLayout } from "./components/layout/AppLayout";
import { NotFound, ToastHost } from "./components/common/Feedback";
import StructurePage from "./pages/Structure";
import VehiclesPage from "./pages/Vehicles";
import VisitorsPage from "./pages/Visitors";
import PackagesPage from "./pages/Packages";
import Dashboard from "./pages/Operation";
import LogsPage from "./pages/Logs";
import { usePortariaStore } from "./store";

const pageTitles: Record<string, string> = {
  "/": "Operação",
  "/estrutura": "Unidades e moradores",
  "/veiculos": "Veículos",
  "/visitantes": "Visitantes",
  "/encomendas": "Encomendas",
  "/logs": "Logs de acesso",
};

function useRealtime() {
  const setConnected = usePortariaStore((state) => state.setConnected);
  const pushEvent = usePortariaStore((state) => state.pushEvent);
  useEffect(() => {
    let retry: number | undefined;
    let socket: WebSocket | undefined;
    let disposed = false;
    const connect = () => {
      if (disposed) return;
      socket = new WebSocket(websocketUrl());
      socket.onopen = () => setConnected(true);
      socket.onmessage = (message) => {
        try {
          pushEvent(JSON.parse(message.data) as PortariaEvent);
          window.dispatchEvent(new CustomEvent("portaria:data-changed"));
        } catch (error) {
          console.error("Mensagem WebSocket inválida", error);
        }
      };
      socket.onclose = () => {
        setConnected(false);
        if (!disposed) retry = window.setTimeout(connect, 1800);
      };
      socket.onerror = () => socket?.close();
    };
    connect();
    return () => {
      disposed = true;
      if (retry) window.clearTimeout(retry);
      socket?.close();
      setConnected(false);
    };
  }, [pushEvent, setConnected]);
}

export default function App() {
  useRealtime();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target?.matches("input, textarea, select, [contenteditable='true']");
      if (event.key === "F1") {
        event.preventDefault();
        navigate("/");
      } else if (event.key === "/" && !typing) {
        event.preventDefault();
        document.querySelector<HTMLInputElement>("[data-quick-search]")?.focus();
      } else if (event.key === "F2" && !typing) {
        event.preventDefault();
        document.querySelector<HTMLButtonElement>(".resource-heading .button-primary")?.click();
      }
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, [navigate]);

  return <>
    <AppLayout title={pageTitles[location.pathname] ?? "Operação"}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/estrutura" element={<StructurePage />} />
        <Route path="/veiculos" element={<VehiclesPage />} />
        <Route path="/visitantes" element={<VisitorsPage />} />
        <Route path="/encomendas" element={<PackagesPage />} />
        <Route path="/logs" element={<LogsPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </AppLayout>
    <ToastHost />
  </>;
}
