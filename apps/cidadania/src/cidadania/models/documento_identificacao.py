import uuid
from datetime import date, datetime, timezone
from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from cidadania.models.base import Base


class DocumentoIdentificacao(Base):
    __tablename__ = "documento_identificacao"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    titular_nome: Mapped[str] = mapped_column(String(60), nullable=False)  # aa-stop-run, Member, Junior
    tipo: Mapped[str] = mapped_column(String(50), nullable=False)          # cartao_cidadao, carta_conducao, passaporte, cesd, nif, niss, sns
    
    numero: Mapped[str] = mapped_column(String(80), nullable=False)
    data_emissao: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_validade: Mapped[date | None] = mapped_column(Date, nullable=True)
    
    entidade_emissora: Mapped[str | None] = mapped_column(String(100), nullable=True, default="República Portuguesa")
    paperless_document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    @property
    def nome_legivel(self) -> str:
        mapa = {
            "cartao_cidadao": "Cartão de Cidadão",
            "carta_conducao": "Carta de Condução",
            "passaporte": "Passaporte Eletrónico Português",
            "cesd": "Cartão Europeu de Seguro de Doença",
            "nif": "Número de Identificação Fiscal (NIF)",
            "niss": "Segurança Social (NISS)",
            "sns": "Número de Utente SNS",
        }
        return mapa.get(self.tipo, self.tipo.replace("_", " ").title())

    @property
    def dias_restantes(self) -> int | None:
        if not self.data_validade:
            return None
        hoje = date.today()
        return (self.data_validade - hoje).days

    @property
    def estado_validade(self) -> str:
        d = self.dias_restantes
        if d is None:
            return "vitalicio"
        if d < 0:
            return "caducado"
        if d <= 30:
            return "urgente"
        if d <= 180:
            return "a_expirar"
        return "valido"
