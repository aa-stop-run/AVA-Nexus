import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from ava.models.base import Base
from ava.models.movimento_linha import MovimentoLinha


class Movimento(Base):
    """O que aconteceu: um lançamento do ledger. Substitui transacao e rendimento.

    `valor` é SEMPRE positivo; a direção vem de `tipo`. Save valores com sinal foi a origem
    de três rondas de correção no modelo anterior.
    """

    __tablename__ = "movimento"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tipo: Mapped[str] = mapped_column(String(15), nullable=False, index=True)
    # tipo: entrada | saida | transferencia
    valor: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    data: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Em saida/transferencia é a conta de origem; em entrada é a conta de destino.
    conta_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conta.id"), nullable=True
    )
    # Só em transferencia. Um empréstimo recebido é uma transferência da conta de dívida para a
    # conta à ordem — entra dinheiro, a dívida sobe, e não conta como receita (spec §6).
    conta_destino_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conta.id"), nullable=True
    )

    titular_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("titular.id"), nullable=True
    )
    registado_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("titular.id"), nullable=True
    )
    ambito: Mapped[str] = mapped_column(String(10), nullable=False, default="comum")
    # ambito: comum | pessoal
    descricao: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    origem: Mapped[str] = mapped_column(String(20), nullable=False)
    # origem: documento | extrato | ficheiro | manual | regra
    # ("ficheiro" é o export de movimentos do BPI Net)
    # ("regra" é escrito pela geração de recorrentes)

    documento_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documento.id"), nullable=True
    )
    fornecedor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fornecedor.id"), nullable=True
    )
    # Referencia a tabela recorrente, criada na Tarefa 7. A FK foi acrescentada à base de dados
    # pela migração 520da9ca66ae (movimento_recorrente_id_fkey); este modelo passou a declará-la
    # também, para que `alembic check`/autogenerate deixem de a ver como deriva a remover.
    recorrente_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recorrente.id"), nullable=True
    )
    # Linha de extrato que reconciliou com este movimento. NULL = ainda não reconciliado. Em
    # saida/entrada é a única ligação; em transferencia é o lado de ORIGEM (ver conta_id acima).
    linha_extrato_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("linha_extrato.id"), nullable=True
    )
    # Só em transferencia entre uma conta à ordem e uma conta de dívida: o mesmo evento real
    # (ex. amortização de crédito) aparece como DUAS linhas de extrato distintas, uma em cada
    # conta (ver ava.ingestion.reconciliacao). Este é o lado de DESTINO (ver conta_destino_id).
    linha_extrato_destino_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("linha_extrato.id"), nullable=True
    )
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # lazy="selectin": carregamento preguiçoso numa AsyncSession rebenta com MissingGreenlet ao
    # ler o atributo fora de um await explícito. Carregar sempre à frente evita essa classe de bug.
    linhas: Mapped[list[MovimentoLinha]] = relationship(
        back_populates="movimento", cascade="all, delete-orphan", lazy="selectin"
    )
