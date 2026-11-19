import { AlertTriangle, Bell, DoorOpen, Plus, ShieldCheck, UserRound, X } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api, fileUrl } from "../../api";
import { EmptyState } from "../common/Feedback";
import { errorMessage, toast } from "../../utils";
import { usePortariaStore } from "../../store";

export function AlertQueue() {
  const alerts = usePortariaStore((state) => state.alerts);
  return <span className="alert-count">{alerts.length} na fila</span>;
}

export function AlertFeed() {
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
      <div className="alert-title"><span className="alert-icon">{recognized ? (allowed ? <ShieldCheck size={17} /> : <AlertTriangle size={17} />) : <Bell size={17} />}</span><div><strong>{recognized ? (allowed ? "Face reconhecida" : alert.data.status === "negado" ? "Acesso negado" : "Rosto desconhecido") : "Alerta da câmera"}</strong><small>{new Date(alert.arrivedAt).toLocaleTimeString("pt-BR")}</small></div><button className="alert-dismiss" onClick={() => dismiss(alert.key)} aria-label="Dispensar"><X size={16} /></button></div>
      <div className="alert-person"><div className="alert-photos">{registeredPhoto && <figure><img src={registeredPhoto} alt={`Foto cadastrada de ${name}`} /><figcaption>CADASTRO</figcaption></figure>}{photo ? <figure><img src={photo} alt={`Captura de ${name}`} /><figcaption>CÂMERA</figcaption></figure> : <div className="alert-placeholder"><UserRound size={20} /></div>}</div><div><strong>{name}</strong><span>{String(alert.data.tipo_vinculo ?? alert.data.description ?? "Aguardando conferência")}</span>{Boolean(alert.data.unidade_id) && <small>Unidade {String(alert.data.unidade_id)}</small>}{Array.isArray(alert.data.veiculos) && alert.data.veiculos.length > 0 && <small>{alert.data.veiculos.map((vehicle) => (vehicle as { placa: string }).placa).join(" • ")}</small>}</div></div>
      <div className="alert-actions">
        {recognized && personId > 0 ? <button className="button-primary small" onClick={() => void api(`/api/pessoas/${personId}/entrada`, { method: "POST" }).then(() => dismiss(alert.key)).catch((error) => toast(errorMessage(error), "error"))}><DoorOpen size={15} /> {allowed ? "Liberar / registrar entrada" : "Registrar entrada manual"}</button> : recognized && visitorId > 0 ? <button className="button-primary small" onClick={() => void api(`/api/visitantes/${visitorId}/entrada`, { method: "POST" }).then(() => dismiss(alert.key)).catch((error) => toast(errorMessage(error), "error"))}><DoorOpen size={15} /> Liberar / registrar entrada</button> : <button className="button-secondary small" onClick={() => void prepareQuickVisitor()}><Plus size={15} /> {alert.data.sem_ficha ? "Criar ficha na gestão" : "Cadastro rápido"}</button>}
        <button className="button-quiet small" onClick={() => dismiss(alert.key)}>Dispensar</button>
      </div>
    </article>;
  })}</div>;
}
