from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from saude.models.base import Base


class PrescricaoMedica(Base):
    __tablename__ = "prescricao_medica"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    titular: Mapped[str] = mapped_column(String(50), nullable=False)  # 'aa-stop-run', 'Member', 'Junior'
    numero_receita_sns: Mapped[str | None] = mapped_column(String(50), nullable=True)
    codigo_acesso: Mapped[str | None] = mapped_column(String(20), nullable=True)
    codigo_opcao: Mapped[str | None] = mapped_column(String(20), nullable=True)
    data_emissao: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_validade: Mapped[date | None] = mapped_column(Date, nullable=True)
    medico_prescritor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    especialidade: Mapped[str | None] = mapped_column(String(100), nullable=True)
    estado: Mapped[str] = mapped_column(String(20), default="ativa", nullable=False)  # 'ativa', 'aviada_parcial', 'aviada_total', 'expirada'
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    documento_paperless_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
