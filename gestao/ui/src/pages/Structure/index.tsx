import { useState } from "react";
import { Building2, UsersRound } from "lucide-react";
import { ResourcePage } from "../Resources";
import { peopleConfig, unitConfig } from "../Resources/configs";

export default function StructurePage() {
  const [tab, setTab] = useState<"units" | "people">("units");
  return <div className="stack-lg">
    <section className="page-intro"><div><div className="eyebrow">CADASTROS</div><h2>Estrutura do condomínio</h2><p>Organize blocos, unidades e as pessoas vinculadas a cada endereço.</p></div></section>
    <div className="tabs">
      <button className={tab === "units" ? "selected" : ""} onClick={() => setTab("units")}><Building2 size={16} /> Unidades</button>
      <button className={tab === "people" ? "selected" : ""} onClick={() => setTab("people")}><UsersRound size={16} /> Moradores e funcionários</button>
    </div>
    {tab === "units" ? <ResourcePage config={unitConfig} /> : <ResourcePage config={peopleConfig} />}
  </div>;
}
