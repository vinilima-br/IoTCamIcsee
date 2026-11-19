import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Operador = {
  id: string;
  nome: string;
  funcao: string;
  pin: string;
  isAdmin: boolean;
};

export type RecadoTurno = {
  mensagem: string;
  autor: string;
  dataHora: string;
};

const operadoresMockados: Operador[] = [
  { id: "1", nome: "Carlos Silva", funcao: "Porteiro Diurno", pin: "1234", isAdmin: false },
  { id: "2", nome: "Roberto Almeida", funcao: "Porteiro Noturno", pin: "5678", isAdmin: false },
  { id: "3", nome: "Supervisor / Síndico", funcao: "Administrador", pin: "0000", isAdmin: true },
];

type OperacaoState = {
  operadores: Operador[];
  operadorAtivo: Operador;
  alertasSilenciados: boolean;
  modoAdmin: boolean;
  recadoTurno: RecadoTurno | null;
  trocarOperador: (operadorId: string, pin: string, novoRecado?: string) => boolean;
  toggleMuteAlertas: () => void;
  ativarModoAdmin: (pin: string) => boolean;
  desativarModoAdmin: () => void;
  dispensarRecadoTurno: () => void;
};

export const useOperacaoStore = create<OperacaoState>()(persist((set, get) => ({
  operadores: operadoresMockados,
  operadorAtivo: operadoresMockados[0],
  alertasSilenciados: false,
  modoAdmin: false,
  recadoTurno: null,
  trocarOperador: (operadorId, pin, novoRecado = "") => {
    const state = get();
    const proximoOperador = state.operadores.find((operador) => operador.id === operadorId);
    if (!proximoOperador || proximoOperador.pin !== pin) return false;

    const mensagem = novoRecado.trim();
    set({
      operadorAtivo: proximoOperador,
      ...(mensagem ? { recadoTurno: {
        mensagem,
        autor: state.operadorAtivo.nome,
        dataHora: new Date().toISOString(),
      } } : {}),
      modoAdmin: false,
    });
    return true;
  },
  toggleMuteAlertas: () => set((state) => ({ alertasSilenciados: !state.alertasSilenciados })),
  ativarModoAdmin: (pin) => {
    const supervisor = get().operadores.find((operador) => operador.isAdmin);
    if (!supervisor || supervisor.pin !== pin) return false;
    set({ modoAdmin: true });
    return true;
  },
  desativarModoAdmin: () => set({ modoAdmin: false }),
  dispensarRecadoTurno: () => set({ recadoTurno: null }),
}), {
  name: "portaria-operacao",
}));

export function useModoAdmin() {
  return useOperacaoStore((state) => state.modoAdmin);
}
