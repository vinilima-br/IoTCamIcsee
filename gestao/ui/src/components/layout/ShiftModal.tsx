import { useState } from "react";
import { ArrowRightLeft, X } from "lucide-react";
import type { Operador } from "../../store/useOperacaoStore";
import { useOperacaoStore } from "../../store/useOperacaoStore";
import { toast } from "../../utils";

export function ShiftModal({ operadores, operadorAtivo, onClose }: {
  operadores: Operador[];
  operadorAtivo: Operador;
  onClose: () => void;
}) {
  const trocarOperador = useOperacaoStore((state) => state.trocarOperador);
  const [operadorId, setOperadorId] = useState(() => operadores.find((operador) => operador.id !== operadorAtivo.id)?.id ?? operadorAtivo.id);
  const [pin, setPin] = useState("");
  const [recado, setRecado] = useState("");
  const [error, setError] = useState("");

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pin.length !== 4) {
      setError("Informe o PIN de 4 dígitos do operador selecionado.");
      return;
    }
    if (!trocarOperador(operadorId, pin, recado)) {
      setError("PIN incorreto para o operador selecionado.");
      return;
    }
    const nome = operadores.find((operador) => operador.id === operadorId)?.nome;
    toast(`Turno transferido para ${nome ?? "o operador selecionado"}.`, "success");
    onClose();
  };

  return <div className="modal-backdrop operator-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="modal-panel operator-modal" role="dialog" aria-modal="true" aria-labelledby="shift-modal-title">
      <div className="modal-heading">
        <div><div className="eyebrow">CONTROLE DE TURNO</div><h2 id="shift-modal-title">Trocar operador</h2></div>
        <button type="button" className="icon-button" onClick={onClose} aria-label="Fechar"><X size={19} /></button>
      </div>
      <p className="operator-modal-copy">Selecione quem está assumindo a guarita e confirme o PIN de acesso.</p>
      <form className="operator-form" onSubmit={submit}>
        <fieldset className="operator-choice-list">
          <legend>Operador que assume</legend>
          {operadores.map((operador) => <label key={operador.id} className={`operator-choice ${operadorId === operador.id ? "selected" : ""}`}>
            <input type="radio" name="operador" value={operador.id} checked={operadorId === operador.id} onChange={() => { setOperadorId(operador.id); setPin(""); setError(""); }} />
            <span className="operator-choice-avatar">{operador.nome.trim().charAt(0)}</span>
            <span className="operator-choice-copy"><strong>{operador.nome}</strong><small>{operador.funcao}</small></span>
            {operador.id === operadorAtivo.id && <small className="operator-current">ATUAL</small>}
          </label>)}
        </fieldset>
        <label className="operator-input-label" htmlFor="shift-pin">PIN de acesso</label>
        <input id="shift-pin" className="operator-text-input operator-pin-input" type="password" inputMode="numeric" autoComplete="one-time-code" maxLength={4} pattern="[0-9]{4}" value={pin} onChange={(event) => { setPin(event.target.value.replace(/\D/g, "").slice(0, 4)); setError(""); }} placeholder="••••" aria-describedby={error ? "shift-error" : undefined} />
        <label className="operator-input-label" htmlFor="shift-note">Passagem de turno <span>opcional</span></label>
        <textarea id="shift-note" className="operator-text-input operator-note-input" maxLength={200} value={recado} onChange={(event) => setRecado(event.target.value)} placeholder="Deixar recado rápido para o próximo turno (ex: portão social, entregas pendentes...)" />
        <div className="operator-note-count">{recado.length}/200 caracteres</div>
        {error && <div className="operator-form-error" id="shift-error" role="alert">{error}</div>}
        <div className="operator-modal-footer">
          <button type="button" className="button-secondary" onClick={onClose}>Cancelar</button>
          <button type="submit" className="button-primary"><ArrowRightLeft size={16} /> Confirmar Troca de Turno</button>
        </div>
      </form>
    </section>
  </div>;
}
