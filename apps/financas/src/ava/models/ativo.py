import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ava.models.base import Base


class Ativo(Base):
    __tablename__ = "ativo"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    titular_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("titular.id"), nullable=False
    )
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="ativo")
    # tipo: carro | mota | casa | outro ("veiculo" é valor legado da migração e1a2b3c4d5e6 —
    # não oferecer em formulários novos). Esta coluna é a CHAVE de
    # ava.financas.valorizacao.TAXAS_POR_TIPO: um valor fora desta lista (ex.: "imovel", "ativo")
    # não levanta erro, cai em silêncio na taxa 0 — nunca se inventa uma taxa para um tipo
    # desconhecido, mas também nunca se avisa que o tipo não foi reconhecido.
    data_aquisicao: Mapped[date | None] = mapped_column(Date, nullable=True) # Antiga "matricula"
    # Taxa de variação anual própria deste bem, como fração (-0.15 = -15%/ano). NULL significa
    # "usa a omissão do tipo" — ver ava.financas.valorizacao.TAXAS_POR_TIPO.
    taxa_anual: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
