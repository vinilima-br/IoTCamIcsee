import {
  AlertTriangle, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Camera, CircleHelp,
  Maximize2, Mic, MicOff, PackageCheck, UsersRound, Volume2, VolumeX, X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, fileUrl, type CameraInfo, type Page } from "../../api";
import { ErrorBanner } from "../../components/common/Feedback";
import { AlertFeed, AlertQueue } from "../../components/alerts/AlertFeed";
import { LogTable } from "../Logs";
import { errorMessage } from "../../utils";
import type { Row } from "../../types";

export default function Dashboard() {
  const [cameraState, setCameraState] = useState<{ available: boolean; error?: string | null; cameras: CameraInfo[] }>({ available: false, cameras: [] });
  // Câmera pequena no topo; o operador clica para ampliar (com PTZ, som e captura).
  const [openCameraId, setOpenCameraId] = useState<string | null>(null);
  const openCamera = cameraState.cameras.find((camera) => camera.id === openCameraId) ?? null;
  useEffect(() => {
    if (!openCameraId) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpenCameraId(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openCameraId]);
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
        <div className="welcome-copy"><div className="eyebrow amber">CENTRAL DE OPERAÇÕES</div><h2>Bom trabalho. Tudo sob controle.</h2><p>Monitore os acessos e mantenha a rotina da portaria em dia.</p></div>
        {cameraState.cameras.length > 0 && !openCamera && (
          <div className="welcome-cams">{cameraState.cameras.map((camera) => <CameraThumb key={camera.id} camera={camera} onOpen={() => setOpenCameraId(camera.id)} />)}</div>
        )}
        <div className="welcome-time"><strong>{new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</strong><span>HORÁRIO LOCAL</span></div>
      </section>
      {loadError && <ErrorBanner message={loadError} />}
      <section className="stats-grid">
        <StatCard label="Visitantes no condomínio" value={summary.visitantes_ativos} hint="Acessos aguardando baixa" icon={UsersRound} tone="blue" />
        <StatCard label="Encomendas pendentes" value={summary.encomendas_pendentes} hint="Pacotes para retirada" icon={PackageCheck} tone="amber" />
        <StatCard label="Câmeras online" value={cameraState.cameras.filter((camera) => camera.online).length} hint={`${cameraState.cameras.length} cadastradas`} icon={Camera} tone="green" />
      </section>
      {!cameraState.available && <div className="notice-box"><CircleHelp size={20} /><div><strong>Integração de câmeras indisponível</strong><span>{cameraState.error || "Verifique a configuração local do sistema de câmeras."}</span></div></div>}
      {openCamera && (
        <div className="modal-backdrop" onClick={(event) => { if (event.target === event.currentTarget) setOpenCameraId(null); }}>
          <div className="camera-modal" role="dialog" aria-label={`Câmera ${openCamera.nome}`}>
            <button className="camera-modal-close" onClick={() => setOpenCameraId(null)} aria-label="Fechar"><X size={18} /></button>
            <CameraCard camera={openCamera} />
          </div>
        </div>
      )}
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

function savedLens(camera: CameraInfo): string {
  try {
    const saved = window.localStorage.getItem(`portaria.lente.${camera.id}`);
    if (saved === "cima" || saved === "baixo" || saved === "ambas") return saved;
  } catch {
    /* sem armazenamento: usa o padrão */
  }
  return camera.lente_det === "cima" || camera.lente_det === "baixo" ? camera.lente_det : "cima";
}

function isDualLens(camera: CameraInfo): boolean {
  return Boolean(camera.largura && camera.altura && camera.altura / camera.largura > 0.9);
}

function CameraThumb({ camera, onOpen }: { camera: CameraInfo; onOpen: () => void }) {
  const [streamTry, setStreamTry] = useState(0);
  const lensClass = isDualLens(camera) ? `lens-${savedLens(camera)}` : "lens-single";
  return (
    <button type="button" className="welcome-cam" onClick={onOpen} title={`Ampliar ${camera.nome || camera.id}`}>
      <img key={streamTry} className={lensClass} src={`/api/cameras/${encodeURIComponent(camera.id)}/stream?t=${streamTry}`} alt="" onError={() => window.setTimeout(() => setStreamTry((value) => value + 1), 3000)} />
      {!camera.online && <span className="welcome-cam-off">{camera.pausada ? "Acordando..." : "Aguardando imagem"}</span>}
      <span className="welcome-cam-label"><i className={camera.online ? "on" : ""} />{camera.nome || camera.id}</span>
      <span className="welcome-cam-zoom"><Maximize2 size={12} /></span>
    </button>
  );
}

function CameraCard({ camera }: { camera: CameraInfo }) {
  const [listening, setListening] = useState(false);
  const [snapshot, setSnapshot] = useState<string>();
  const [talking, setTalking] = useState(false);
  const [audioError, setAudioError] = useState("");
  const listenRef = useRef<{ stop: () => void } | null>(null);
  const [phrase, setPhrase] = useState("");
  const [speaking, setSpeaking] = useState(false);
  const cameraPath = `/api/cameras/${encodeURIComponent(camera.id)}`;
  // Câmera de 2 lentes (X6S): o quadro vem com as duas empilhadas (mais alto que largo).
  // Igual ao painel: mostra Lente 1, Lente 2 ou as 2, e lembra a escolha por câmera.
  const dualLens = isDualLens(camera);
  const lensKey = `portaria.lente.${camera.id}`;
  const [lens, setLensState] = useState<string>(() => savedLens(camera));
  const setLens = (value: string) => {
    setLensState(value);
    try {
      window.localStorage.setItem(lensKey, value);
    } catch {
      /* sem armazenamento: só nesta sessão */
    }
  };
  const lensClass = dualLens ? `lens-${lens}` : "lens-single";
  const recorderRef = useRef<{ context: AudioContext; processor: ScriptProcessorNode; source: MediaStreamAudioSourceNode; gain: GainNode; stream: MediaStream; samples: number[] } | null>(null);
  const speakTimeout = useRef<number | null>(null);
  // O vídeo é aberto SEMPRE: o servidor de câmeras deixa a câmera em pausa quando
  // ninguém assiste e só religa quando alguém abre o stream (antes ficava esperando
  // "online" pra abrir, e "online" esperando alguém abrir).
  const [streamTry, setStreamTry] = useState(0);
  const streamUrl = `/api/cameras/${encodeURIComponent(camera.id)}/stream?t=${streamTry}`;
  const retryStream = () => window.setTimeout(() => setStreamTry((value) => value + 1), 3000);

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
  const stopListening = () => {
    const current = listenRef.current;
    listenRef.current = null;
    setListening(false);
    if (current) current.stop();
  };
  const toggleListening = () => {
    if (listenRef.current) {
      stopListening();
      return;
    }
    setAudioError("");
    const context = new AudioContext();
    void context.resume().catch(() => undefined);
    const sampleRate = 8000;
    let playing = true;
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
    let next = context.currentTime + 0.2;
    const handle = {
      stop: () => {
        playing = false;
        if (reader) void reader.cancel().catch(() => undefined);
        void context.close().catch(() => undefined);
      },
    };
    listenRef.current = handle;
    setListening(true);
    void (async () => {
      try {
        const response = await fetch(`${cameraPath}/audio_pcm`);
        if (!response.ok || !response.body) {
          let message = "Áudio indisponível";
          try {
            message = (await response.json()).detail ?? message;
          } catch {
            /* resposta sem JSON */
          }
          throw new Error(message);
        }
        reader = response.body.getReader();
        let rest = new Uint8Array(0);
        while (playing) {
          const { done, value } = await reader.read();
          if (done || !value) break;
          const joined = new Uint8Array(rest.length + value.length);
          joined.set(rest, 0);
          joined.set(value, rest.length);
          const count = joined.length >> 1;
          rest = joined.slice(count << 1);
          if (!count) continue;
          const view = new DataView(joined.buffer, 0, count * 2);
          const buffer = context.createBuffer(1, count, sampleRate);
          const channel = buffer.getChannelData(0);
          for (let index = 0; index < count; index += 1) channel[index] = view.getInt16(index * 2, true) / 32768;
          const source = context.createBufferSource();
          source.buffer = buffer;
          source.connect(context.destination);
          const now = context.currentTime;
          if (next < now) next = now + 0.1;
          source.start(next);
          next += buffer.duration;
        }
        if (playing) throw new Error("O áudio da câmera parou");
      } catch (error) {
        if (playing) setAudioError(errorMessage(error));
      } finally {
        if (listenRef.current === handle) {
          listenRef.current = null;
          setListening(false);
        }
        handle.stop();
      }
    })();
  };
  useEffect(() => () => {
    if (listenRef.current) listenRef.current.stop();
  }, []);
  const speakText = async () => {
    const texto = phrase.trim();
    if (!texto || speaking) return;
    setSpeaking(true);
    setAudioError("");
    try {
      await api(`${cameraPath}/falar`, { method: "POST", body: JSON.stringify({ texto }) });
      setPhrase("");
    } catch (error) {
      setAudioError(errorMessage(error));
    } finally {
      setSpeaking(false);
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
      <div className="camera-card-head"><div><span className={`camera-status ${camera.online ? "online" : ""}`} /><strong>{camera.nome || camera.id}</strong>{camera.ip && <span className="camera-ip">{camera.ip}</span>}</div><span className="camera-fps">{camera.online ? `${camera.fps} FPS` : "OFFLINE"}</span></div>
      <div className="camera-image-wrap">
        <img key={streamTry} className={lensClass} src={streamUrl} alt={`Stream da câmera ${camera.nome}`} onError={retryStream} />
        {!camera.online && <div className="camera-offline camera-offline-overlay"><Camera size={28} /><span>{camera.erro || (camera.pausada ? "Acordando a câmera..." : "Aguardando imagem")}{camera.ip ? ` (${camera.ip})` : ""}</span></div>}
        {snapshot && <button className="snapshot-preview" onClick={() => setSnapshot(undefined)} title="Fechar captura"><img src={snapshot} alt="Último snapshot" /><X size={14} /></button>}
      </div>
      {dualLens && (
        <div className="lens-switch" role="group" aria-label="Lente da câmera">
          {[["cima", "Lente 1"], ["baixo", "Lente 2"], ["ambas", "2 lentes"]].map(([value, label]) => (
            <button key={value} type="button" className={lens === value ? "active" : ""} onClick={() => setLens(value)}>{label}</button>
          ))}
        </div>
      )}
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
      {camera.tem_som !== false && (
        <form className="camera-speak" onSubmit={(event) => { event.preventDefault(); void speakText(); }}>
          <input value={phrase} maxLength={500} placeholder="Digite uma frase para a câmera falar" onChange={(event) => setPhrase(event.target.value)} disabled={!camera.online || speaking} />
          <button type="submit" className="control-button" disabled={!camera.online || speaking || !phrase.trim()}><Volume2 size={16} /><span>{speaking ? "Falando..." : "Falar"}</span></button>
        </form>
      )}
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
