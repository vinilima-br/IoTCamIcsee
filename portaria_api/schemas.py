import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class UnidadeIn(Schema):
    bloco: str = Field(min_length=1, max_length=80)
    numero: str = Field(min_length=1, max_length=40)
    ramal: str | None = Field(default=None, max_length=30)
    observacoes: str | None = None
    tipo: Literal["apartamento", "casa", "sala", "outro"] = "apartamento"
    ativo: bool = True

    @field_validator("bloco", "numero")
    @classmethod
    def trim_required(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("campo obrigatório")
        return value


class PessoaIn(Schema):
    unidade_id: int = Field(gt=0)
    nome: str = Field(min_length=2, max_length=160)
    cpf: str | None = None
    telefone: str | None = Field(default=None, max_length=30)
    tipo: Literal["proprietario", "inquilino", "dependente", "funcionario_unidade"]
    foto_path: str | None = Field(default=None, max_length=500)
    face_id_externo: str | None = Field(default=None, max_length=160)
    ativo: bool = True

    @field_validator("nome")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("informe o nome completo")
        return value

    @field_validator("cpf")
    @classmethod
    def validate_cpf(cls, value):
        if value is None or not value.strip():
            return None
        digits = re.sub(r"\D", "", value)
        if len(digits) != 11 or len(set(digits)) == 1:
            raise ValueError("CPF inválido")
        for size in (9, 10):
            total = sum(int(digits[i]) * (size + 1 - i) for i in range(size))
            check = (total * 10 % 11) % 10
            if check != int(digits[size]):
                raise ValueError("CPF inválido")
        return digits


class VeiculoIn(Schema):
    unidade_id: int = Field(gt=0)
    pessoa_id: int | None = Field(default=None, gt=0)
    placa: str = Field(min_length=7, max_length=8)
    modelo: str = Field(min_length=1, max_length=100)
    cor: str = Field(min_length=1, max_length=50)
    tipo: Literal["carro", "moto", "outro"]
    tag_controle: str | None = Field(default=None, max_length=80)

    @field_validator("placa")
    @classmethod
    def validate_plate(cls, value):
        plate = re.sub(r"[\s-]", "", value).upper()
        if not (re.fullmatch(r"[A-Z]{3}\d{4}", plate) or
                re.fullmatch(r"[A-Z]{3}\d[A-Z]\d{2}", plate)):
            raise ValueError("placa deve seguir o padrão antigo ABC1234 ou Mercosul ABC1D23")
        return plate


class VisitanteIn(Schema):
    nome: str = Field(min_length=2, max_length=160)
    documento: str | None = Field(default=None, max_length=40)
    empresa: str | None = Field(default=None, max_length=120)
    foto_path: str | None = Field(default=None, max_length=500)
    unidade_destino_id: int = Field(gt=0)
    autorizado_por_id: int | None = Field(default=None, gt=0)
    tipo_acesso: Literal["avulso", "recorrente"] = "avulso"
    validade_inicio: datetime | None = None
    validade_fim: datetime | None = None
    status_atual: Literal["no_condominio", "saiu"] = "no_condominio"

    @field_validator("nome")
    @classmethod
    def trim_name(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("informe o nome completo")
        return value

    @model_validator(mode="after")
    def validate_validity(self):
        if self.tipo_acesso == "recorrente" and (not self.validade_inicio or not self.validade_fim):
            raise ValueError("acesso recorrente exige início e fim de validade")
        if self.validade_inicio and self.validade_fim and self.validade_fim <= self.validade_inicio:
            raise ValueError("a validade final deve ser posterior à inicial")
        return self


class EncomendaIn(Schema):
    unidade_id: int = Field(gt=0)
    codigo_rastreio: str | None = Field(default=None, max_length=100)
    transportadora: str = Field(min_length=1, max_length=100)
    recebido_por: str = Field(min_length=1, max_length=120)
    data_recebimento: datetime | None = None
    status: Literal["pendente", "retirada"] = "pendente"
    retirado_por: str | None = Field(default=None, max_length=120)
    data_retirada: datetime | None = None
    foto_path: str | None = Field(default=None, max_length=500)


class RetiradaIn(Schema):
    retirado_por: str = Field(min_length=1, max_length=120)


class LogIn(Schema):
    pessoa_id: int | None = Field(default=None, gt=0)
    visitante_id: int | None = Field(default=None, gt=0)
    veiculo_id: int | None = Field(default=None, gt=0)
    camera_id: str | None = Field(default=None, max_length=80)
    tipo_evento: Literal["entrada", "saida", "alerta_desconhecido", "reconhecimento_facial"]
    metodo: Literal["facial", "manual", "placa"]
    snapshot_path: str | None = Field(default=None, max_length=500)
    detalhes: dict | None = None
    timestamp: datetime | None = None
