import type { ResourceConfig } from "../../types";
import { selectOptions } from "../../utils";

export const unitConfig: ResourceConfig = {
  title: "Unidades",
  description: "Cadastre torres, blocos, casas e ramais do condomínio.",
  endpoint: "/api/unidades",
  search: "Buscar bloco ou número",
  fields: [
    { name: "bloco", label: "Bloco, torre ou rua", required: true, section: "Identificação", placeholder: "Ex.: Torre A" },
    { name: "numero", label: "Número da unidade", required: true, section: "Identificação", placeholder: "Ex.: 101" },
    { name: "ramal", label: "Ramal", section: "Identificação", placeholder: "Ex.: 1010" },
    { name: "tipo", label: "Tipo de unidade", kind: "select", required: true, section: "Identificação", options: selectOptions([["apartamento", "Apartamento"], ["casa", "Casa"], ["sala", "Sala"], ["outro", "Outro"]]) },
    { name: "ativo", label: "Unidade ativa", kind: "checkbox", section: "Situação" },
    { name: "observacoes", label: "Observações", kind: "textarea", wide: true, section: "Observações", placeholder: "Informações adicionais sobre a unidade" },
  ],
  columns: [{ key: "bloco", label: "Bloco / torre" }, { key: "numero", label: "Unidade" }, { key: "tipo", label: "Tipo" }, { key: "ramal", label: "Ramal" }, { key: "ativo", label: "Status" }],
};

export const peopleConfig: ResourceConfig = {
  title: "Moradores e funcionários",
  description: "Cadastre vínculos, contatos e foto para reconhecimento facial.",
  endpoint: "/api/pessoas",
  search: "Buscar nome, CPF ou telefone",
  fields: [
    { name: "nome", label: "Nome completo", required: true, section: "Dados pessoais", placeholder: "Nome completo" },
    { name: "cpf", label: "CPF", section: "Dados pessoais", placeholder: "000.000.000-00" },
    { name: "telefone", label: "Telefone", section: "Dados pessoais", placeholder: "(00) 00000-0000" },
    { name: "unidade_id", label: "Unidade", kind: "select", required: true, section: "Vínculo", options: [] },
    { name: "tipo", label: "Tipo de vínculo", kind: "select", required: true, section: "Vínculo", options: selectOptions([["proprietario", "Proprietário"], ["inquilino", "Inquilino"], ["dependente", "Dependente"], ["funcionario_unidade", "Funcionário da unidade"]]) },
    { name: "face_id_externo", label: "Identificador facial externo", section: "Reconhecimento", placeholder: "Opcional", hint: "ID utilizado pelo sistema de reconhecimento facial." },
    { name: "foto_path", label: "Foto facial", kind: "photo", wide: true, section: "Reconhecimento" },
    { name: "ativo", label: "Cadastro ativo", kind: "checkbox", section: "Situação" },
  ],
  columns: [{ key: "nome", label: "Nome" }, { key: "unidade_id", label: "Unidade" }, { key: "tipo", label: "Vínculo" }, { key: "telefone", label: "Telefone" }, { key: "ativo", label: "Status" }],
};

export const vehicleConfig: ResourceConfig = {
  title: "Veículos",
  description: "Identifique placas e controles vinculados às unidades.",
  endpoint: "/api/veiculos",
  search: "Buscar placa ou modelo",
  fields: [
    { name: "placa", label: "Placa", required: true, section: "Identificação", placeholder: "ABC1D23" },
    { name: "tipo", label: "Tipo", kind: "select", required: true, section: "Identificação", options: selectOptions([["carro", "Carro"], ["moto", "Moto"], ["outro", "Outro"]]) },
    { name: "modelo", label: "Modelo", required: true, section: "Identificação", placeholder: "Ex.: Onix" },
    { name: "cor", label: "Cor", required: true, section: "Identificação", placeholder: "Ex.: Prata" },
    { name: "unidade_id", label: "Unidade", kind: "select", required: true, section: "Vínculo", options: [] },
    { name: "pessoa_id", label: "Morador responsável", kind: "select", section: "Vínculo", options: [] },
    { name: "tag_controle", label: "Tag / controle", section: "Acesso", placeholder: "Código do controle ou tag", hint: "Opcional. Usado para identificar o veículo em outras integrações." },
  ],
  columns: [{ key: "placa", label: "Placa" }, { key: "modelo", label: "Modelo" }, { key: "cor", label: "Cor" }, { key: "tipo", label: "Tipo" }, { key: "unidade_id", label: "Unidade" }, { key: "pessoa_id", label: "Responsável" }],
};

export const visitorConfig: ResourceConfig = {
  title: "Visitantes e prestadores",
  description: "Registre entradas, recorrências e baixas de saída.",
  endpoint: "/api/visitantes",
  search: "Buscar nome ou documento",
  fields: [
    { name: "nome", label: "Nome completo", required: true, section: "Identificação", placeholder: "Nome completo" },
    { name: "documento", label: "RG ou CPF", section: "Identificação", placeholder: "Documento" },
    { name: "empresa", label: "Empresa / prestador", section: "Identificação", placeholder: "Nome da empresa" },
    { name: "unidade_destino_id", label: "Unidade de destino", kind: "select", required: true, section: "Destino e autorização", options: [] },
    { name: "autorizado_por_id", label: "Morador que autorizou", kind: "select", section: "Destino e autorização", options: [] },
    { name: "tipo_acesso", label: "Tipo de acesso", kind: "select", required: true, section: "Validade", options: selectOptions([["avulso", "Avulso"], ["recorrente", "Recorrente"]]) },
    { name: "validade_inicio", label: "Início da validade", kind: "datetime-local", section: "Validade" },
    { name: "validade_fim", label: "Fim da validade", kind: "datetime-local", section: "Validade" },
    { name: "foto_path", label: "Foto do visitante", kind: "photo", wide: true, section: "Registro visual" },
  ],
  columns: [{ key: "nome", label: "Visitante" }, { key: "empresa", label: "Empresa" }, { key: "unidade_destino_id", label: "Unidade" }, { key: "tipo_acesso", label: "Acesso" }, { key: "status_atual", label: "Status" }, { key: "validade_fim", label: "Validade" }],
};

export const packageConfig: ResourceConfig = {
  title: "Encomendas",
  description: "Registre recebimentos e acompanhe retiradas pendentes.",
  endpoint: "/api/encomendas",
  search: "Buscar rastreio ou transportadora",
  fields: [
    { name: "unidade_id", label: "Unidade de destino", kind: "select", required: true, section: "Entrega", options: [] },
    { name: "codigo_rastreio", label: "Código de rastreio", section: "Entrega", placeholder: "Código informado pela transportadora" },
    { name: "transportadora", label: "Transportadora", required: true, section: "Entrega", placeholder: "Ex.: Correios" },
    { name: "recebido_por", label: "Porteiro que recebeu", required: true, section: "Recebimento", placeholder: "Nome do responsável" },
    { name: "foto_path", label: "Foto do pacote", kind: "photo", wide: true, section: "Registro visual" },
  ],
  columns: [{ key: "codigo_rastreio", label: "Rastreio" }, { key: "transportadora", label: "Transportadora" }, { key: "unidade_id", label: "Unidade" }, { key: "recebido_por", label: "Recebido por" }, { key: "data_recebimento", label: "Recebido em" }, { key: "status", label: "Status" }],
};
