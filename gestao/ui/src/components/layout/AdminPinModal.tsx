import { useState } from "react";
import { ShieldCheck, X } from "lucide-react";
import { useOperacaoStore } from "../../store/useOperacaoStore";
import { toast } from "../../utils";

export function AdminPinModal({ onClose }: { onClose: () => void }) {
  const ativarModoAdmin = useOperacaoStore((state) => state.ativarModoAdmin);
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!ativarModoAdmin(pin)) {
      setError("PIN de supervisor incorreto.");
      return;
    }
    toast("Modo Administrador ativado.", "success");
    onClose();
  };

  return <div className="modal-backdrop operator-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="modal-panel admin-pin-modal" role="dialog" aria-modal="true" aria-labelledby="admin-pin-title">
      <div className="modal-heading">
        <div><div className="eyebrow">ACESSO RESTRITO</div><h2 id="admin-pin-title">Modo Administrador</h2></div>
        <button type="button" className="icon-button" onClick={onClose} aria-label="Fechar"><X size={19} /></button>
      </div>
      <p className="operator-modal-copy">Informe o PIN do supervisor para liberar ações administrativas.</p>
      <form className="operator-form" onSubmit={submit}>
        <label className="operator-input-label" htmlFor="admin-pin">PIN do supervisor</label>
        <input id="admin-pin" className="operator-text-input operator-pin-input" type="password" inputMode="numeric" autoComplete="one-time-code" maxLength={4} pattern="[0-9]{4}" autoFocus value={pin} onChange={(event) => { setPin(event.target.value.replace(/\D/g, "").slice(0, 4)); setError(""); }} placeholder="••••" />
        {error && <div className="operator-form-error" role="alert">{error}</div>}
        <div className="operator-modal-footer">
          <button type="button" className="button-secondary" onClick={onClose}>Cancelar</button>
          <button type="submit" className="button-primary"><ShieldCheck size={16} /> Ativar modo admin</button>
        </div>
      </form>
    </section>
  </div>;
}
