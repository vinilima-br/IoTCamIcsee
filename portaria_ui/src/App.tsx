import {
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Bell,
  Box,
  Building2,
  Camera,
  CarFront,
  Check,
  ChevronDown,
  CircleHelp,
  DoorOpen,
  FileClock,
  LayoutDashboard,
  LoaderCircle,
  LogOut,
  Mic,
  MicOff,
  PackageCheck,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
  UserRound,
  UsersRound,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, fileUrl, websocketUrl, type CameraInfo, type Page, type PortariaEvent } from "./api";
import { usePortariaStore } from "./store";

type Row = Record<string, unknown> & { id: number };
type FieldKind = "text" | "number" | "select" | "textarea" | "checkbox" | "datetime-local" | "photo";
type Field = {
  name: string;
  label: string;
  kind?: FieldKind;
  required?: boolean;
  options?: { label: string; value: string | number }[];
  placeholder?: string;
  wide?: boolean;
};
type ResourceConfig = {
  title: string;
  description: string;
  endpoint: string;
  fields: Field[];
  columns: { key: string; label: string }[];
  search?: string;
};

const relationshipOptions = async (endpoint: string, label: (row: Row) => string) => {
  const response = await api<Page<Row>>(`${endpoint}?page_size=100`);
  return response.items.map((row) => ({ value: row.id, label: label(row) }));
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

const navItems = [
  { to: "/", label: "Operação", icon: LayoutDashboard, end: true },
  { to: "/estrutura", label: "Unidades e moradores", icon: Building2 },
  { to: "/veiculos", label: "Veículos", icon: CarFront },
  { to: "/visitantes", label: "Visitantes", icon: UsersRound },
  { to: "/encomendas", label: "Encomendas", icon: Box },
  { to: "/logs", label: "Logs de acesso", icon: FileClock },
];

export default function App() {
  useRealtime();
  const navigate = useNavigate();
  const connected = usePortariaStore((state) => state.connected);
  const location = useLocation();
  const title = navItems.find((item) => item.to === location.pathname)?.label ?? "Operação";
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
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link className="brand" to="/">
          <div className="brand-mark"><ShieldCheck size={23} /></div>
          <span><strong>PORTARIA</strong><small>CONTROLE OPERACIONAL</small></span>
        </Link>
        <div className="side-label">MENU PRINCIPAL</div>
        <nav className="side-nav">
          {navItems.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
              <Icon size={19} strokeWidth={2.1} /><span>{label}</span>
              {to === "/" && <span className="nav-shortcut">F1</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="connection-indicator">
            <span className={`connection-dot ${connected ? "online" : ""}`} />
            <span>{connected ? "Alertas em tempo real" : "Reconectando alertas..."}</span>
          </div>
          <div className="operator-card"><div className="operator-avatar">P</div><div><strong>Portaria</strong><small>Operador local</small></div><ChevronDown size={16} /></div>
        </div>
      </aside>
      <main className="main-area">
        <header className="topbar">
          <div><div className="eyebrow">CONDOMÍNIO • GUARITA</div><h1>{title}</h1></div>
          <div className="topbar-right">
            <div className="local-badge"><span /> Sistema local</div>
            <div className="clock">{new Date().toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "short" })}</div>
            <button className="icon-button" title="Alertas ativos" onClick={() => document.getElementById("alert-feed")?.scrollIntoView({ behavior: "smooth" })}><Bell size={19} /><span className="notification-dot" /></button>
          </div>
        </header>
        <div className="page-content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/estrutura" element={<StructurePage />} />
            <Route path="/veiculos" element={<VehiclesPage />} />
            <Route path="/visitantes" element={<VisitorsPage />} />
            <Route path="/encomendas" element={<PackagesPage />} />
            <Route path="/logs" element={<LogsPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </div>
      </main>
      <ToastHost />
    </div>
  );
}

function Dashboard() {
  const [cameraState, setCameraState] = useState<{ available: boolean; error?: string | null; cameras: CameraInfo[] }>({ available: false, cameras: [] });
  const [summary, setSummary] = useState({ visitantes_ativos: 0, encomendas_pendentes: 0 });
  const [recentLogs, setRecentLogs] = useState<Row[]>([]);
  const [loadError, setLoadError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [cameras, overview, logs] = await Promise.all([
        api<typeof cameraState>("/api/cameras"),
        api<typeof summary>("/api/resumo"),
        api<Page<Row>>("/api/logs?page_size=6"),
      ]);
      setCameraState(cameras);
      setSummary(overview);
      setRecentLogs(logs.items);
      setLoadError("");
    } catch (error) {
      setLoadError(errorMessage(error));
    }
  }, []);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    window.addEventListener("portaria:data-changed", refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("portaria:data-changed", refresh);
    };
  }, [refresh]);

  return (
    <div className="stack-lg">
      <section className="welcome-strip">
        <div><div className="eyebrow amber">CENTRAL DE OPERAÇÕES</div><h2>Bom trabalho. Tudo sob controle.</h2><p>Monitore os acessos e mantenha a rotina da portaria em dia.</p></div>
        <div className="welcome-time"><strong>{new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</strong><span>HORÁRIO LOCAL</span></div>
      </section>
      {loadError && <ErrorBanner message={loadError} />}
      <section className="stats-grid">
        <StatCard label="Visitantes no condomínio" value={summary.visitantes_ativos} hint="Acessos aguardando baixa" icon={UsersRound} tone="blue" />
        <StatCard label="Encomendas pendentes" value={summary.encomendas_pendentes} hint="Pacotes para retirada" icon={PackageCheck} tone="amber" />
        <StatCard label="Câmeras online" value={cameraState.cameras.filter((camera) => camera.online).length} hint={`${cameraState.cameras.length} cadastradas`} icon={Camera} tone="green" />
      </section>
      {!cameraState.available && <div className="notice-box"><CircleHelp size={20} /><div><strong>Integração de câmeras indisponível</strong><span>{cameraState.error || "Verifique a configuração local do sistema de câmeras."}</span></div></div>}
      <section className="section-block">
        <div className="section-heading"><div><div className="eyebrow">MONITORAMENTO</div><h2>Câmeras ao vivo</h2></div><span className="live-tag"><span /> AO VIVO</span></div>
        {cameraState.cameras.length ? <div className="camera-grid">{cameraState.cameras.map((camera) => <CameraCard key={camera.id} camera={camera} />)}</div> : <EmptyState icon={Camera} title="Nenhuma câmera conectada" text="Quando o sistema de câmeras estiver configurado, os streams aparecerão aqui." />}
      </section>
      <section id="alert-feed" className="section-block">
        <div className="section-heading"><div><div className="eyebrow">EVENTOS INSTANTÂNEOS</div><h2>Alertas recentes</h2></div><AlertQueue /></div>
        <AlertFeed />
      </section>
      <section className="section-block">
        <div className="section-heading"><div><div className="eyebrow">AUDITORIA</div><h2>Últimos registros</h2></div><Link className="text-link" to="/logs">Ver todos <ArrowRight size={15} /></Link></div>
        <LogTable rows={recentLogs} compact />
      </section>
    </div>
  );
}

function StatCard({ label, value, hint, icon: Icon, tone }: { label: string; value: number; hint: string; icon: typeof UsersRound; tone: string }) {
  return <article className="stat-card"><div className={`stat-icon ${tone}`}><Icon size={20} /></div><div className="stat-copy"><span>{label}</span><strong>{value}</strong><small>{hint}</small></div></article>;
}

function CameraCard({ camera }: { camera: CameraInfo }) {
  const [listening, setListening] = useState(false);
  const [snapshot, setSnapshot] = useState<string>();
  const [talking, setTalking] = useState(false);
  const [audioError, setAudioError] = useState("");
  const audioRef = useRef<HTMLAudioElement>(null);
  const recorderRef = useRef<{ context: AudioContext; processor: ScriptProcessorNode; source: MediaStreamAudioSourceNode; gain: GainNode; stream: MediaStream; samples: number[] } | null>(null);
  const speakTimeout = useRef<number | null>(null);
  const streamUrl = `/api/cameras/${encodeURIComponent(camera.id)}/stream`;

  const sendPTZ = async (pan: number, tilt: number) => api(`/api/cameras/${encodeURIComponent(camera.id)}/ptz`, { method: "POST", body: JSON.stringify({ pan, tilt }) });
  const stopPTZ = () => void api(`/api/cameras/${encodeURIComponent(camera.id)}/ptz`, { method: "POST", body: JSON.stringify({ action: "stop" }) }).catch(() => undefined);
  const beginTalk = async () => {
    if (talking) return;
    try {
      setAudioError("");
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      const context = new AudioContext();
      const source = context.createMediaStreamSource(stream);
      const processor = context.createScriptProcessor(4096, 1, 1);
      const gain = context.createGain();
      gain.gain.value = 0;
      const samples: number[] = [];
      processor.onaudioprocess = (event) => {
        const input = event.inputBuffer.getChannelData(0);
        const ratio = context.sampleRate / 8000;
        const count = Math.floor(input.length / ratio);
        for (let index = 0; index < count; index += 1) {
          const at = Math.floor(index * ratio);
          samples.push(Math.max(-1, Math.min(1, input[at])));
        }
        if (samples.length > 8000 * 20) endTalk();
      };
      source.connect(processor);
      processor.connect(gain);
      gain.connect(context.destination);
      recorderRef.current = { context, processor, source, gain, stream, samples };
      setTalking(true);
      speakTimeout.current = window.setTimeout(endTalk, 20000);
    } catch (error) {
      setAudioError(error instanceof Error ? error.message : "Não foi possível acessar o microfone.");
    }
  };
  const endTalk = async () => {
    const recorder = recorderRef.current;
    if (!recorder) return;
    recorderRef.current = null;
    if (speakTimeout.current) window.clearTimeout(speakTimeout.current);
    recorder.processor.disconnect();
    recorder.source.disconnect();
    recorder.gain.disconnect();
    recorder.stream.getTracks().forEach((track) => track.stop());
    await recorder.context.close();
    setTalking(false);
    if (!recorder.samples.length) return;
    try {
      const bytes = Uint8Array.from(recorder.samples, encodeAlaw);
      let binary = "";
      for (let offset = 0; offset < bytes.length; offset += 0x8000) binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
      await api(`/api/cameras/${encodeURIComponent(camera.id)}/audio`, {
        method: "POST",
        body: JSON.stringify({ action: "speak", audio_base64: btoa(binary) }),
      });
    } catch (error) {
      setAudioError(errorMessage(error));
    }
  };
  useEffect(() => () => {
    if (recorderRef.current) {
      recorderRef.current.stream.getTracks().forEach((track) => track.stop());
      void recorderRef.current.context.close();
    }
    if (speakTimeout.current) window.clearTimeout(speakTimeout.current);
  }, []);
  const toggleListening = () => {
    const next = !listening;
    setListening(next);
    if (audioRef.current) {
      if (next) {
        audioRef.current.src = `/api/cameras/${encodeURIComponent(camera.id)}/audio`;
        void audioRef.current.play().catch((error: unknown) => setAudioError(errorMessage(error)));
      } else {
        audioRef.current.pause();
        audioRef.current.removeAttribute("src");
        audioRef.current.load();
      }
    }
  };
  const takeSnapshot = async () => {
    try {
      const result = await api<{ snapshot_path: string }>("/api/cameras/" + encodeURIComponent(camera.id) + "/snapshot", { method: "POST" });
      setSnapshot(fileUrl(result.snapshot_path));
    } catch (error) {
      setAudioError(errorMessage(error));
    }
  };

  return (
    <article className="camera-card">
      <div className="camera-card-head"><div><span className={`camera-status ${camera.online ? "online" : ""}`} /><strong>{camera.nome || camera.id}</strong></div><span className="camera-fps">{camera.online ? `${camera.fps} FPS` : "OFFLINE"}</span></div>
      <div className="camera-image-wrap">
        {camera.online ? <img src={streamUrl} alt={`Stream da câmera ${camera.nome}`} /> : <div className="camera-offline"><Camera size={28} /><span>{camera.erro || "Aguardando imagem"}</span></div>}
        {snapshot && <button className="snapshot-preview" onClick={() => setSnapshot(undefined)} title="Fechar captura"><img src={snapshot} alt="Último snapshot" /><X size={14} /></button>}
      </div>
      <div className="camera-controls">
        <div className="ptz-pad" aria-label="Controle PTZ">
          <button aria-label="Mover para cima" disabled={!camera.online} onPointerDown={() => void sendPTZ(0, 0.6).catch((error) => setAudioError(errorMessage(error)))} onPointerUp={stopPTZ} onPointerLeave={stopPTZ}><ArrowUp size={16} /></button>
          <button aria-label="Mover para esquerda" disabled={!camera.online} onPointerDown={() => void sendPTZ(-0.6, 0).catch((error) => setAudioError(errorMessage(error)))} onPointerUp={stopPTZ} onPointerLeave={stopPTZ}><ArrowLeft size={16} /></button>
          <span><CircleHelp size={13} /></span>
          <button aria-label="Mover para direita" disabled={!camera.online} onPointerDown={() => void sendPTZ(0.6, 0).catch((error) => setAudioError(errorMessage(error)))} onPointerUp={stopPTZ} onPointerLeave={stopPTZ}><ArrowRight size={16} /></button>
          <button aria-label="Mover para baixo" disabled={!camera.online} onPointerDown={() => void sendPTZ(0, -0.6).catch((error) => setAudioError(errorMessage(error)))} onPointerUp={stopPTZ} onPointerLeave={stopPTZ}><ArrowDown size={16} /></button>
        </div>
        <button className={`control-button ${listening ? "selected" : ""}`} onClick={toggleListening} disabled={!camera.online}>{listening ? <VolumeX size={16} /> : <Volume2 size={16} />}<span>{listening ? "Parar áudio" : "Ouvir"}</span></button>
        <button className={`control-button ${talking ? "danger" : ""}`} onPointerDown={() => void beginTalk()} onPointerUp={() => void endTalk()} onPointerLeave={() => void endTalk()} disabled={!camera.online}>{talking ? <MicOff size={16} /> : <Mic size={16} />}<span>{talking ? "Enviando..." : "Segure p/ falar"}</span></button>
        <button className="control-button snapshot-button" onClick={() => void takeSnapshot()} disabled={!camera.online}><Camera size={16} /><span>Capturar</span></button>
      </div>
      <audio ref={audioRef} hidden />
      {audioError && <button className="camera-error" onClick={() => setAudioError("")}><AlertTriangle size={13} />{audioError}<X size={13} /></button>}
    </article>
  );
}

function encodeAlaw(value: number): number {
  let sample = Math.max(-1, Math.min(1, value)) * 32768;
  const sign = sample >= 0 ? 0x80 : 0;
  if (sign) sample = -sample;
  sample = Math.min(sample, 32635) + 0x84;
  let exponent = 7;
  for (let mask = 0x4000; exponent > 0 && (sample & mask) === 0; exponent -= 1, mask >>= 1) {}
  const mantissa = (sample >> (exponent + 3)) & 0x0f;
  return (sign | (exponent << 4) | mantissa) ^ 0x55;
}

function AlertQueue() {
  const alerts = usePortariaStore((state) => state.alerts);
  return <span className="alert-count">{alerts.length} na fila</span>;
}

function AlertFeed() {
  const alerts = usePortariaStore((state) => state.alerts);
  const dismiss = usePortariaStore((state) => state.dismissAlert);
  const setDraft = usePortariaStore((state) => state.setQuickVisitorDraft);
  const navigate = useNavigate();
  if (!alerts.length) return <EmptyState icon={Bell} title="Nenhum alerta pendente" text="Eventos de reconhecimento facial e detecção das câmeras aparecerão aqui." />;
  return <div className="alert-grid">{alerts.slice(0, 6).map((alert) => {
    const recognized = alert.type === "face_recognition";
    const name = String(alert.data.nome ?? alert.data.description ?? "Alerta de câmera");
    const photo = fileUrl(String(alert.data.snapshot_path ?? ""));
    const registeredPhoto = fileUrl(String(alert.data.foto_path ?? ""));
    const allowed = alert.data.status === "permitido";
    const personId = Number(alert.data.pessoa_id);
    const visitorId = Number(alert.data.visitante_id);
    const prepareQuickVisitor = async () => {
      try {
        let foto_path: string | undefined;
        if (alert.data.snapshot_path && photo) {
          const response = await fetch(photo);
          if (!response.ok) throw new Error("Não foi possível carregar o snapshot do alerta.");
          const image = await response.blob();
          const form = new FormData();
          form.append("file", new File([image], "snapshot-visitante.jpg", { type: image.type || "image/jpeg" }));
          const uploaded = await api<{ foto_path: string }>("/api/arquivos/cadastro", { method: "POST", body: form });
          foto_path = uploaded.foto_path;
        }
        setDraft({ nome: name, foto_path });
        dismiss(alert.key);
        navigate("/visitantes");
      } catch (error) {
        toast(errorMessage(error), "error");
      }
    };
    return <article className={`alert-card ${recognized && allowed ? "recognized" : "unknown"}`} key={alert.key}>
      <div className="alert-title"><span className="alert-icon">{recognized ? (allowed ? <ShieldCheck size={17} /> : <AlertTriangle size={17} />) : <Bell size={17} />}</span><div><strong>{recognized ? (allowed ? "Face reconhecida" : "Rosto desconhecido") : "Alerta da câmera"}</strong><small>{new Date(alert.arrivedAt).toLocaleTimeString("pt-BR")}</small></div><button className="alert-dismiss" onClick={() => dismiss(alert.key)} aria-label="Dispensar"><X size={16} /></button></div>
      <div className="alert-person"><div className="alert-photos">{registeredPhoto && <figure><img src={registeredPhoto} alt={`Foto cadastrada de ${name}`} /><figcaption>CADASTRO</figcaption></figure>}{photo ? <figure><img src={photo} alt={`Captura de ${name}`} /><figcaption>CÂMERA</figcaption></figure> : <div className="alert-placeholder"><UserRound size={20} /></div>}</div><div><strong>{name}</strong><span>{String(alert.data.tipo_vinculo ?? alert.data.description ?? "Aguardando conferência")}</span>{Boolean(alert.data.unidade_id) && <small>Unidade {String(alert.data.unidade_id)}</small>}{Array.isArray(alert.data.veiculos) && alert.data.veiculos.length > 0 && <small>{alert.data.veiculos.map((vehicle) => (vehicle as { placa: string }).placa).join(" • ")}</small>}</div></div>
      <div className="alert-actions">
        {recognized && personId > 0 ? <button className="button-primary small" onClick={() => void api(`/api/pessoas/${personId}/entrada`, { method: "POST" }).then(() => dismiss(alert.key)).catch((error) => toast(errorMessage(error), "error"))}><DoorOpen size={15} /> {allowed ? "Liberar / registrar entrada" : "Registrar entrada manual"}</button> : recognized && visitorId > 0 ? <button className="button-primary small" onClick={() => void api(`/api/visitantes/${visitorId}/entrada`, { method: "POST" }).then(() => dismiss(alert.key)).catch((error) => toast(errorMessage(error), "error"))}><DoorOpen size={15} /> Liberar / registrar entrada</button> : <button className="button-secondary small" onClick={() => void prepareQuickVisitor()}><Plus size={15} /> Cadastro rápido</button>}
        <button className="button-quiet small" onClick={() => dismiss(alert.key)}>Dispensar</button>
      </div>
    </article>;
  })}</div>;
}

function StructurePage() {
  const [tab, setTab] = useState<"units" | "people">("units");
  return <div className="stack-lg"><section className="page-intro"><div><div className="eyebrow">CADASTROS</div><h2>Estrutura do condomínio</h2><p>Organize blocos, unidades e as pessoas vinculadas a cada endereço.</p></div></section><div className="tabs"><button className={tab === "units" ? "selected" : ""} onClick={() => setTab("units")}><Building2 size={16} /> Unidades</button><button className={tab === "people" ? "selected" : ""} onClick={() => setTab("people")}><UsersRound size={16} /> Moradores e funcionários</button></div>{tab === "units" ? <ResourcePage config={unitConfig} /> : <ResourcePage config={peopleConfig} />}</div>;
}

const unitConfig: ResourceConfig = {
  title: "Unidades",
  description: "Cadastre torres, blocos, casas e ramais do condomínio.",
  endpoint: "/api/unidades",
  search: "Buscar bloco ou número",
  fields: [
    { name: "bloco", label: "Bloco, torre ou rua", required: true },
    { name: "numero", label: "Número da unidade", required: true },
    { name: "ramal", label: "Ramal" },
    { name: "tipo", label: "Tipo de unidade", kind: "select", required: true, options: selectOptions([["apartamento", "Apartamento"], ["casa", "Casa"], ["sala", "Sala"], ["outro", "Outro"]]) },
    { name: "ativo", label: "Unidade ativa", kind: "checkbox" },
    { name: "observacoes", label: "Observações", kind: "textarea", wide: true },
  ],
  columns: [{ key: "bloco", label: "Bloco / torre" }, { key: "numero", label: "Unidade" }, { key: "tipo", label: "Tipo" }, { key: "ramal", label: "Ramal" }, { key: "ativo", label: "Status" }],
};

const peopleConfig: ResourceConfig = {
  title: "Moradores e funcionários",
  description: "Cadastre vínculos, contatos e foto para reconhecimento facial.",
  endpoint: "/api/pessoas",
  search: "Buscar nome, CPF ou telefone",
  fields: [
    { name: "nome", label: "Nome completo", required: true },
    { name: "unidade_id", label: "Unidade", kind: "select", required: true, options: [] },
    { name: "cpf", label: "CPF" },
    { name: "telefone", label: "Telefone" },
    { name: "tipo", label: "Tipo de vínculo", kind: "select", required: true, options: selectOptions([["proprietario", "Proprietário"], ["inquilino", "Inquilino"], ["dependente", "Dependente"], ["funcionario_unidade", "Funcionário da unidade"]]) },
    { name: "foto_path", label: "Foto facial", kind: "photo", wide: true },
    { name: "ativo", label: "Cadastro ativo", kind: "checkbox" },
  ],
  columns: [{ key: "nome", label: "Nome" }, { key: "unidade_id", label: "Unidade" }, { key: "tipo", label: "Vínculo" }, { key: "telefone", label: "Telefone" }, { key: "ativo", label: "Status" }],
};

const vehicleConfig: ResourceConfig = {
  title: "Veículos",
  description: "Identifique placas e controles vinculados às unidades.",
  endpoint: "/api/veiculos",
  search: "Buscar placa ou modelo",
  fields: [
    { name: "placa", label: "Placa", required: true, placeholder: "ABC1D23" },
    { name: "unidade_id", label: "Unidade", kind: "select", required: true, options: [] },
    { name: "pessoa_id", label: "Morador responsável", kind: "select", options: [] },
    { name: "modelo", label: "Modelo", required: true },
    { name: "cor", label: "Cor", required: true },
    { name: "tipo", label: "Tipo", kind: "select", required: true, options: selectOptions([["carro", "Carro"], ["moto", "Moto"], ["outro", "Outro"]]) },
    { name: "tag_controle", label: "Tag / controle" },
  ],
  columns: [{ key: "placa", label: "Placa" }, { key: "modelo", label: "Modelo" }, { key: "cor", label: "Cor" }, { key: "tipo", label: "Tipo" }, { key: "unidade_id", label: "Unidade" }, { key: "pessoa_id", label: "Responsável" }],
};

const visitorConfig: ResourceConfig = {
  title: "Visitantes e prestadores",
  description: "Registre entradas, recorrências e baixas de saída.",
  endpoint: "/api/visitantes",
  search: "Buscar nome ou documento",
  fields: [
    { name: "nome", label: "Nome completo", required: true },
    { name: "documento", label: "RG ou CPF" },
    { name: "empresa", label: "Empresa / prestador" },
    { name: "unidade_destino_id", label: "Unidade de destino", kind: "select", required: true, options: [] },
    { name: "autorizado_por_id", label: "Morador que autorizou", kind: "select", options: [] },
    { name: "tipo_acesso", label: "Tipo de acesso", kind: "select", required: true, options: selectOptions([["avulso", "Avulso"], ["recorrente", "Recorrente"]]) },
    { name: "validade_inicio", label: "Início da validade", kind: "datetime-local" },
    { name: "validade_fim", label: "Fim da validade", kind: "datetime-local" },
    { name: "foto_path", label: "Foto do visitante", kind: "photo", wide: true },
  ],
  columns: [{ key: "nome", label: "Visitante" }, { key: "empresa", label: "Empresa" }, { key: "unidade_destino_id", label: "Unidade" }, { key: "tipo_acesso", label: "Acesso" }, { key: "status_atual", label: "Status" }, { key: "validade_fim", label: "Validade" }],
};

const packageConfig: ResourceConfig = {
  title: "Encomendas",
  description: "Registre recebimentos e acompanhe retiradas pendentes.",
  endpoint: "/api/encomendas",
  search: "Buscar rastreio ou transportadora",
  fields: [
    { name: "unidade_id", label: "Unidade de destino", kind: "select", required: true, options: [] },
    { name: "codigo_rastreio", label: "Código de rastreio" },
    { name: "transportadora", label: "Transportadora", required: true },
    { name: "recebido_por", label: "Porteiro que recebeu", required: true },
    { name: "foto_path", label: "Foto do pacote", kind: "photo", wide: true },
  ],
  columns: [{ key: "codigo_rastreio", label: "Rastreio" }, { key: "transportadora", label: "Transportadora" }, { key: "unidade_id", label: "Unidade" }, { key: "recebido_por", label: "Recebido por" }, { key: "data_recebimento", label: "Recebido em" }, { key: "status", label: "Status" }],
};

function VehiclesPage() { return <ResourcePage config={vehicleConfig} />; }
function VisitorsPage() { return <ResourcePage config={visitorConfig} />; }
function PackagesPage() { return <ResourcePage config={packageConfig} />; }

function ResourcePage({ config }: { config: ResourceConfig }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [editing, setEditing] = useState<Row | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [dynamicFields, setDynamicFields] = useState(config.fields);
  const draft = usePortariaStore((state) => state.quickVisitorDraft);
  const setDraft = usePortariaStore((state) => state.setQuickVisitorDraft);
  const isVisitor = config.endpoint === "/api/visitantes";
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
  }, [defaultValues, draft, form, isVisitor, setDraft]);

  const openNew = () => {
    setEditing(null);
    form.reset(defaultValues);
    setError("");
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
      await load();
      toast(editing ? "Cadastro atualizado." : "Cadastro salvo.", "success");
    } catch (submitError) {
      setError(errorMessage(submitError));
    } finally {
      setSaving(false);
    }
  };
  const remove = async (row: Row) => {
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
        <button className="mini-action" title="Editar" onClick={() => openEdit(row)}><ChevronDown size={15} /></button><button className="mini-action destructive" title="Excluir" onClick={() => void remove(row)}><Trash2 size={15} /></button>
      </div></td></tr>)}
      {!rows.length && <tr><td colSpan={config.columns.length + 1}><EmptyState icon={Search} title="Nenhum resultado" text={query ? "Tente outra busca ou limpe os filtros." : "Use “Novo cadastro” para registrar o primeiro item."} /></td></tr>}
    </tbody></table></div>
    <div className="pagination"><span>Exibindo {rows.length ? (page - 1) * 25 + 1 : 0}–{Math.min(page * 25, total)} de {total}</span><div><button className="button-quiet small" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Anterior</button><span className="page-number">{page}</span><button className="button-quiet small" disabled={page * 25 >= total} onClick={() => setPage((value) => value + 1)}>Próxima</button></div></div>
    {editing !== null && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setEditing(null); }}><div className="modal-panel"><div className="modal-heading"><div><div className="eyebrow">{editing ? "EDITAR REGISTRO" : "NOVO REGISTRO"}</div><h2>{editing ? "Atualizar cadastro" : `Cadastrar ${config.title.toLowerCase()}`}</h2></div><button className="icon-button" onClick={() => setEditing(null)} aria-label="Fechar"><X size={19} /></button></div>
      <form className="form-grid" onSubmit={form.handleSubmit(onSubmit)}>{dynamicFields.map((field) => <FormField key={field.name} field={field} form={form} />)}
        {error && <div className="form-error span-two">{error}</div>}
        <div className="form-footer span-two"><button type="button" className="button-secondary" onClick={() => setEditing(null)}>Cancelar</button><button type="submit" className="button-primary" disabled={saving}>{saving ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />}{saving ? "Salvando..." : "Salvar cadastro"}</button></div>
      </form></div></div>}
  </section>;
}

function FormField({ field, form }: { field: Field; form: ReturnType<typeof useForm<Record<string, unknown>>> }) {
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
    catch (error) { toast(errorMessage(error), "error"); }
  }} />{watch(field.name) ? <span className="upload-success"><Check size={14} /> Foto pronta</span> : <span className="field-hint">JPG, PNG ou WEBP • até 8 MB</span>}</div>{error && <small className="field-error">{String(error)}</small>}</div>;
  return <div className={wrapClass}><label htmlFor={inputId}>{field.label}{field.required && <span className="required-mark"> *</span>}</label>
    {field.kind === "select" ? <select id={inputId} {...register(field.name)}><option value="">Selecione</option>{field.options?.map((option) => <option key={String(option.value)} value={option.value}>{option.label}</option>)}</select> :
      field.kind === "textarea" ? <textarea id={inputId} rows={3} placeholder={field.placeholder} {...register(field.name)} /> :
        <input id={inputId} type={field.kind ?? "text"} placeholder={field.placeholder} {...register(field.name)} />}
    {error && <small className="field-error">{String(error)}</small>}
  </div>;
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

function LogsPage() {
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
      <select className="filter-select" value={eventType} onChange={(event) => setEventType(event.target.value)}><option value="">Todos os eventos</option><option value="entrada">Entrada</option><option value="saida">Saída</option><option value="reconhecimento_facial">Reconhecimento facial</option><option value="alerta_desconhecido">Alerta desconhecido</option></select>
      <select className="filter-select" value={method} onChange={(event) => setMethod(event.target.value)}><option value="">Todos os métodos</option><option value="facial">Facial</option><option value="manual">Manual</option><option value="placa">Placa</option></select>
      <input className="filter-select" type="datetime-local" value={start} onChange={(event) => setStart(event.target.value)} aria-label="Data inicial" />
      <input className="filter-select" type="datetime-local" value={end} onChange={(event) => setEnd(event.target.value)} aria-label="Data final" />
    </div>{error && <ErrorBanner message={error} />}<LogTable rows={rows} />
      <div className="pagination"><span>{total} eventos encontrados</span><div><button className="button-quiet small" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Anterior</button><span className="page-number">{page}</span><button className="button-quiet small" disabled={page * 25 >= total} onClick={() => setPage((value) => value + 1)}>Próxima</button></div></div>
    </section>
  </div>;
}

function LogTable({ rows, compact = false }: { rows: Row[]; compact?: boolean }) {
  return <div className="table-wrap"><table><thead><tr><th>Momento</th><th>Pessoa / visitante</th><th>Unidade</th><th>Evento</th><th>Método</th><th>Snapshot</th></tr></thead><tbody>{rows.map((row) => {
    const details = typeof row.detalhes === "object" && row.detalhes ? row.detalhes as Record<string, unknown> : {};
    const name = row.pessoa_id ? `Pessoa #${row.pessoa_id}` : row.visitante_id ? `Visitante #${row.visitante_id}` : String(details.nome_reconhecido ?? "Desconhecido");
    return <tr key={row.id}><td><span className="log-time">{formatDate(row.timestamp)}</span></td><td><strong className="table-primary">{name}</strong></td><td>{String(details.unidade_id ?? "—")}</td><td><span className={`event-pill ${row.tipo_evento === "entrada" ? "entry" : row.tipo_evento === "saida" ? "exit" : "alert"}`}>{displayValue(row.tipo_evento)}</span></td><td><span className="method-chip">{displayValue(row.metodo)}</span></td><td>{row.snapshot_path ? <a href={fileUrl(String(row.snapshot_path))} target="_blank" rel="noreferrer" className="snapshot-link"><img src={fileUrl(String(row.snapshot_path))} alt="Snapshot" /><span>Ver captura</span></a> : <span className="dim">—</span>}</td></tr>;
  })}{!rows.length && <tr><td colSpan={6}><EmptyState icon={FileClock} title="Nenhum log encontrado" text={compact ? "Os acessos registrados aparecerão aqui." : "Ajuste os filtros ou aguarde novos registros."} /></td></tr>}</tbody></table></div>;
}

function NotFound() { return <EmptyState icon={CircleHelp} title="Tela não encontrada" text="A página solicitada não existe." />; }

function EmptyState({ icon: Icon, title, text }: { icon: typeof CircleHelp; title: string; text: string }) {
  return <div className="empty-state"><div><Icon size={20} /></div><strong>{title}</strong><span>{text}</span></div>;
}
function ErrorBanner({ message }: { message: string }) { return <div className="error-banner"><AlertTriangle size={17} /><span>{message}</span></div>; }

type Toast = { id: number; message: string; kind: "success" | "error" };
let toastId = 0;
let emitToast: (message: string, kind: Toast["kind"]) => void = () => undefined;
function toast(message: string, kind: Toast["kind"] = "success") { emitToast(message, kind); }
function ToastHost() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => { emitToast = (message, kind) => { const id = ++toastId; setItems((current) => [...current, { id, message, kind }]); window.setTimeout(() => setItems((current) => current.filter((item) => item.id !== id)), 4000); }; return () => { emitToast = () => undefined; }; }, []);
  return <div className="toast-stack" aria-live="polite">{items.map((item) => <div key={item.id} className={`toast ${item.kind}`}><Check size={16} />{item.message}<button onClick={() => setItems((current) => current.filter((toastItem) => toastItem.id !== item.id))}><X size={15} /></button></div>)}</div>;
}

function selectOptions(items: [string, string][]) { return items.map(([value, label]) => ({ value, label })); }
function errorMessage(error: unknown) { return error instanceof Error ? error.message : "Ocorreu um erro inesperado."; }
function displayValue(value: unknown): string {
  if (value === undefined || value === null || value === "") return "—";
  const labels: Record<string, string> = { proprietario: "Proprietário", inquilino: "Inquilino", dependente: "Dependente", funcionario_unidade: "Funcionário", apartamento: "Apartamento", avulso: "Avulso", recorrente: "Recorrente", no_condominio: "No condomínio", saiu: "Saiu", pendente: "Pendente", retirada: "Retirada", entrada: "Entrada", saida: "Saída", reconhecimento_facial: "Reconhecimento facial", alerta_desconhecido: "Alerta desconhecido", facial: "Facial", manual: "Manual", placa: "Placa", carro: "Carro", moto: "Moto", outro: "Outro" };
  return labels[String(value)] ?? String(value);
}
function formatDate(value: unknown) {
  if (!value) return "—";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}
