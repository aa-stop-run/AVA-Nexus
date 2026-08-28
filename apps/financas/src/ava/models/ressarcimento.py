"""O grupo que liga um reembolso à despesa que ele ressarce.

Só existe para dar identidade ao grupo — não guarda mais nenhum facto próprio. Despesas e
reembolsos ligam-se a ele através de `MovimentoLinha.ressarcimento_id`, em qualquer ordem: o
utilizador confirmou que às vezes recebe o reembolso antes de a despesa estar registada (spec
2026-08-14, §2). O "líquido" do grupo (despesas menos reembolsos) é sempre calculado a pedido em
`ressarcimento_repo.resumo`, nunca guardado aqui.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ava.models.base import Base


class Ressarcimento(Base):
    __tablename__ = "ressarcimento"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
