from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Unidade(Base):
    __tablename__ = "unidades"
    __table_args__ = (UniqueConstraint("bloco", "numero", name="uq_unidade_bloco_numero"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bloco: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    numero: Mapped[str] = mapped_column(String(40), nullable=False)
    ramal: Mapped[str | None] = mapped_column(String(30))
    observacoes: Mapped[str | None] = mapped_column(Text)
    tipo: Mapped[str] = mapped_column(String(20), default="apartamento", nullable=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), nullable=False)

    pessoas: Mapped[list["Pessoa"]] = relationship(back_populates="unidade")
    veiculos: Mapped[list["Veiculo"]] = relationship(back_populates="unidade")


class Pessoa(Base):
    __tablename__ = "pessoas"
    __table_args__ = (Index("ix_pessoas_unidade_ativo", "unidade_id", "ativo"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unidade_id: Mapped[int] = mapped_column(ForeignKey("unidades.id", ondelete="RESTRICT"), nullable=False)
    nome: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    cpf: Mapped[str | None] = mapped_column(String(11), unique=True)
    telefone: Mapped[str | None] = mapped_column(String(30))
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    foto_path: Mapped[str | None] = mapped_column(String(500))
    face_id_externo: Mapped[str | None] = mapped_column(String(160), unique=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), nullable=False)

    unidade: Mapped[Unidade] = relationship(back_populates="pessoas")
    veiculos: Mapped[list["Veiculo"]] = relationship(back_populates="pessoa")


class Veiculo(Base):
    __tablename__ = "veiculos"
    __table_args__ = (Index("ix_veiculos_unidade", "unidade_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unidade_id: Mapped[int] = mapped_column(ForeignKey("unidades.id", ondelete="RESTRICT"), nullable=False)
    pessoa_id: Mapped[int | None] = mapped_column(ForeignKey("pessoas.id", ondelete="SET NULL"))
    placa: Mapped[str] = mapped_column(String(7), unique=True, nullable=False, index=True)
    modelo: Mapped[str] = mapped_column(String(100), nullable=False)
    cor: Mapped[str] = mapped_column(String(50), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    tag_controle: Mapped[str | None] = mapped_column(String(80))

    unidade: Mapped[Unidade] = relationship(back_populates="veiculos")
    pessoa: Mapped[Pessoa | None] = relationship(back_populates="veiculos")


class VisitantePrestador(Base):
    __tablename__ = "visitantes_prestadores"
    __table_args__ = (Index("ix_visitantes_status_unidade", "status_atual", "unidade_destino_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nome: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    documento: Mapped[str | None] = mapped_column(String(40), index=True)
    empresa: Mapped[str | None] = mapped_column(String(120))
    foto_path: Mapped[str | None] = mapped_column(String(500))
    unidade_destino_id: Mapped[int] = mapped_column(ForeignKey("unidades.id", ondelete="RESTRICT"), nullable=False)
    autorizado_por_id: Mapped[int | None] = mapped_column(ForeignKey("pessoas.id", ondelete="SET NULL"))
    tipo_acesso: Mapped[str] = mapped_column(String(20), nullable=False, default="avulso")
    validade_inicio: Mapped[datetime | None] = mapped_column(DateTime)
    validade_fim: Mapped[datetime | None] = mapped_column(DateTime)
    status_atual: Mapped[str] = mapped_column(String(20), nullable=False, default="no_condominio")


class Encomenda(Base):
    __tablename__ = "encomendas"
    __table_args__ = (Index("ix_encomendas_unidade_status", "unidade_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unidade_id: Mapped[int] = mapped_column(ForeignKey("unidades.id", ondelete="RESTRICT"), nullable=False)
    codigo_rastreio: Mapped[str | None] = mapped_column(String(100), index=True)
    transportadora: Mapped[str] = mapped_column(String(100), nullable=False)
    recebido_por: Mapped[str] = mapped_column(String(120), nullable=False)
    data_recebimento: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pendente", index=True)
    retirado_por: Mapped[str | None] = mapped_column(String(120))
    data_retirada: Mapped[datetime | None] = mapped_column(DateTime)
    foto_path: Mapped[str | None] = mapped_column(String(500))


class LogAcesso(Base):
    __tablename__ = "logs_acesso"
    __table_args__ = (
        Index("ix_logs_timestamp_tipo", "timestamp", "tipo_evento"),
        Index("ix_logs_pessoa_timestamp", "pessoa_id", "timestamp"),
        Index("ix_logs_visitante_timestamp", "visitante_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pessoa_id: Mapped[int | None] = mapped_column(ForeignKey("pessoas.id", ondelete="SET NULL"))
    visitante_id: Mapped[int | None] = mapped_column(ForeignKey("visitantes_prestadores.id", ondelete="SET NULL"))
    veiculo_id: Mapped[int | None] = mapped_column(ForeignKey("veiculos.id", ondelete="SET NULL"))
    camera_id: Mapped[str | None] = mapped_column(String(80), index=True)
    tipo_evento: Mapped[str] = mapped_column(String(30), nullable=False)
    metodo: Mapped[str] = mapped_column(String(20), nullable=False)
    snapshot_path: Mapped[str | None] = mapped_column(String(500))
    detalhes: Mapped[dict | None] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), nullable=False, index=True)
