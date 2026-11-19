import { useEffect, useRef, useState } from "react";
import { ArrowDownToLine, ArrowLeftRight, Bell, BellOff, Box, Building2, CarFront, ChevronDown, Database, FileClock, LayoutDashboard, ShieldCheck, UsersRound } from "lucide-react";
import { Link, NavLink } from "react-router-dom";
import { usePortariaStore } from "../../store";
import { useOperacaoStore } from "../../store/useOperacaoStore";
import { toast } from "../../utils";
import { AdminPinModal } from "./AdminPinModal";
import { ShiftModal } from "./ShiftModal";

const navItems = [
  { to: "/", label: "Operação", icon: LayoutDashboard, end: true },
  { to: "/estrutura", label: "Unidades e moradores", icon: Building2 },
  { to: "/veiculos", label: "Veículos", icon: CarFront },
  { to: "/visitantes", label: "Visitantes", icon: UsersRound },
  { to: "/encomendas", label: "Encomendas", icon: Box },
  { to: "/logs", label: "Logs de acesso", icon: FileClock },
];

export function Sidebar() {
  const connected = usePortariaStore((state) => state.connected);
  const { operadores, operadorAtivo, alertasSilenciados, modoAdmin, toggleMuteAlertas, desativarModoAdmin } = useOperacaoStore();
  const [menuOpen, setMenuOpen] = useState(false);
  const [shiftOpen, setShiftOpen] = useState(false);
  const [adminPinOpen, setAdminPinOpen] = useState(false);
  const controlsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (event.target instanceof Node && !controlsRef.current?.contains(event.target)) setMenuOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [menuOpen]);

  return <aside className="sidebar">
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
      <div className="operator-controls" ref={controlsRef}>
        {menuOpen && <div className="operator-menu" role="menu" aria-label="Configurações da operação">
          <div className="operator-menu-label">OPERAÇÃO</div>
          <button className="operator-menu-item" role="menuitem" onClick={() => { setMenuOpen(false); setShiftOpen(true); }}>
            <ArrowLeftRight size={17} /><span><strong>Trocar Operador</strong><small>Passar turno</small></span><ChevronDown className="operator-menu-arrow" size={15} />
          </button>
          <button className="operator-menu-item" role="switch" aria-checked={alertasSilenciados} onClick={toggleMuteAlertas}>
            {alertasSilenciados ? <BellOff size={17} /> : <Bell size={17} />}
            <span><strong>Alertas sonoros</strong><small>{alertasSilenciados ? "Silenciados" : "Ativos"}</small></span>
            <span className={`operator-toggle ${alertasSilenciados ? "on" : ""}`}><i /></span>
          </button>
          <button className={`operator-menu-item ${modoAdmin ? "admin-enabled" : ""}`} role="menuitem" onClick={() => {
            setMenuOpen(false);
            if (modoAdmin) {
              desativarModoAdmin();
              toast("Modo Administrador desativado.", "success");
            } else setAdminPinOpen(true);
          }}>
            <ShieldCheck size={17} /><span><strong>{modoAdmin ? "Desativar modo admin" : "Modo Administrador"}</strong><small>{modoAdmin ? "Acesso elevado ativo" : "Requer PIN do supervisor"}</small></span>
            {modoAdmin && <span className="admin-badge">ADMIN</span>}
          </button>
          <div className="operator-menu-divider" />
          <button className="operator-menu-item" role="menuitem" onClick={() => { setMenuOpen(false); toast("Simulação: Backup solicitado (aguardando integração com backend)", "success"); }}>
            <Database size={17} /><span><strong>Backup do Banco</strong><small>Solicitar cópia de segurança</small></span><ArrowDownToLine className="operator-menu-download" size={15} />
          </button>
        </div>}
        <button className={`operator-card ${menuOpen ? "open" : ""}`} aria-expanded={menuOpen} aria-haspopup="menu" onClick={() => setMenuOpen((open) => !open)}>
          <div className="operator-avatar">{operadorAtivo.nome.trim().charAt(0)}</div>
          <span className="operator-identity"><strong>{operadorAtivo.nome}</strong><small>{operadorAtivo.funcao}</small></span>
          {modoAdmin && <span className="admin-badge sidebar-admin-badge">ADMIN</span>}
          <ChevronDown className="operator-trigger-chevron" size={16} />
        </button>
      </div>
    </div>
    {shiftOpen && <ShiftModal operadores={operadores} operadorAtivo={operadorAtivo} onClose={() => setShiftOpen(false)} />}
    {adminPinOpen && <AdminPinModal onClose={() => setAdminPinOpen(false)} />}
  </aside>;
}
