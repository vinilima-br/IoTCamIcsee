import { create } from "zustand";
import type { PortariaEvent } from "./api";

export type AlertCard = {
  key: string;
  type: string;
  data: Record<string, unknown>;
  arrivedAt: number;
};

type Store = {
  connected: boolean;
  alerts: AlertCard[];
  quickVisitorDraft: Record<string, unknown> | null;
  setConnected: (connected: boolean) => void;
  pushEvent: (event: PortariaEvent) => void;
  dismissAlert: (key: string) => void;
  setQuickVisitorDraft: (draft: Record<string, unknown> | null) => void;
};

export const usePortariaStore = create<Store>((set) => ({
  connected: false,
  alerts: [],
  quickVisitorDraft: null,
  setConnected: (connected) => set({ connected }),
  pushEvent: (event) => {
    if (!["face_recognition", "camera_alert"].includes(event.type)) return;
    const key = `${event.type}-${String(event.data.log_id ?? event.data.timestamp ?? Date.now())}`;
    set((state) => ({
      alerts: [{ key, type: event.type, data: event.data, arrivedAt: Date.now() }, ...state.alerts].slice(0, 30),
    }));
  },
  dismissAlert: (key) => set((state) => ({ alerts: state.alerts.filter((alert) => alert.key !== key) })),
  setQuickVisitorDraft: (draft) => set({ quickVisitorDraft: draft }),
}));
