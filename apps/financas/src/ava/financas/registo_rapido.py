"""Registo de uma despesa ou rendimento a partir de uma linha de texto ("Almoço 15,50").

Funcionalidade de interpretação rápida de texto livre para registar movimentos no ledger.
"""

import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from ava.extraction.validadores import valor_dentro_magnitude_historica
from ava.models.titular import Titular
from ava.repositories import movimento_repo

# "Descrição Valor", com o valor no fim e o € opcional: "Almoço 15,50", "Venda OLX 50 €".
# O valor tem de estar no FIM — é o que torna a descrição não-ambígua sem adivinhação.
_LINHA = re.compile(r"^(.*?)\s+([\d.,]+)\s*€?$")

_ROTULOS = {
    "saida": ("Despesa", "despesas", "Despesa avulsa", "Almoço 15,50"),
    "entrada": ("Rendimento", "rendimentos", "Rendimento avulso", "Venda OLX 50"),
}


async def registar_movimento_rapido(
    session: AsyncSession,
    *,
    titular: Titular,
    texto: str,
    tipo: str,
    ambito: str = "comum",
    categoria_id: uuid.UUID | None = None,
) -> str:
    """Cria o movimento e devolve a mensagem a mostrar ao utilizador.

    Devolve uma mensagem de erro (sem criar nada) quando o texto não encaixa no formato, quando o
    valor não é positivo, ou quando foge à magnitude histórica — ver
    `valor_dentro_magnitude_historica`. `tipo` é "saida" ou "entrada".
    """
    if tipo not in _ROTULOS:
        raise ValueError(f"tipo tem de ser 'saida' ou 'entrada', não {tipo!r}")
    rotulo, plural, descricao_linha, exemplo = _ROTULOS[tipo]

    correspondencia = _LINHA.match(texto.strip())
    if not correspondencia:
        return (
            f"Formato inválido, {titular.nome}. Usa 'Descrição Valor' — por exemplo: {exemplo}."
        )

    descricao = correspondencia.group(1).strip()
    try:
        valor = Decimal(correspondencia.group(2).replace(",", "."))
    except InvalidOperation:
        # Só apanha o que o regex deixa passar mas não é decimal válido (ex. "1.2.3").
        return f"Valor inválido, {titular.nome}. Verifica os números."

    if valor <= 0:
        return f"O valor não pode ser zero nem negativo, {titular.nome}."

    # Teto de magnitude (A-P3): protege contra um engano de digitação que multiplique o valor por
    # 100. Sem histórico, deixa passar — ver valor_dentro_magnitude_historica.
    historico = await movimento_repo.historico_valores_registo_rapido(
        session, titular_id=titular.id, tipo=tipo
    )
    if not valor_dentro_magnitude_historica(valor, historico, verificar_minimo=False):
        return (
            f"O valor {valor}€ foge muito do teu histórico de {plural} registados assim, "
            f"{titular.nome}. Regista pelo formulário completo se estiver correto."
        )

    await movimento_repo.criar_movimento(
        session,
        tipo=tipo,
        valor=valor,
        data=date.today(),
        origem="manual",
        descricao=descricao,
        titular_id=titular.id,
        registado_por=titular.id,
        ambito=ambito,
        conta_id=None,
        linhas=[
            movimento_repo.LinhaNova(
                valor=valor, categoria_id=categoria_id, descricao=descricao_linha
            )
        ],
    )
    await session.commit()
    return f"Registado, {titular.nome}! {rotulo}: {descricao} — {valor}€"
