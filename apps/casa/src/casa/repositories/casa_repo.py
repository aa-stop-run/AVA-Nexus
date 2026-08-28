import uuid
from datetime import date
from decimal import Decimal
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from casa.models.equipamento import EquipamentoCasa
from casa.models.manutencao import ManutencaoCasa


async def obter_equipamentos(
    session: AsyncSession,
    categoria: str | None = None,
    divisao: str | None = None,
    apenas_ativos: bool = True
) -> list[EquipamentoCasa]:
    stmt = select(EquipamentoCasa)
    if apenas_ativos:
        stmt = stmt.where(EquipamentoCasa.ativo.is_(True))
    if categoria:
        stmt = stmt.where(EquipamentoCasa.categoria == categoria)
    if divisao:
        stmt = stmt.where(EquipamentoCasa.divisao_casa == divisao)
    stmt = stmt.order_by(EquipamentoCasa.data_fim_garantia.asc().nulls_last())
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def criar_equipamento(
    session: AsyncSession,
    *,
    nome: str,
    marca: str | None = None,
    modelo: str | None = None,
    numero_serie: str | None = None,
    categoria: str = "eletronica",
    divisao_casa: str = "Geral",
    data_compra: date | None = None,
    valor_compra: Decimal | None = None,
    fornecedor_loja: str | None = None,
    anos_garantia: int = 3,
    data_fim_garantia: date | None = None,
    paperless_document_id: int | None = None,
    numero_fatura: str | None = None,
    notas: str | None = None,
) -> EquipamentoCasa:
    if data_compra and not data_fim_garantia:
        try:
            data_fim_garantia = date(data_compra.year + anos_garantia, data_compra.month, data_compra.day)
        except Exception:
            data_fim_garantia = None

    eq = EquipamentoCasa(
        nome=nome,
        marca=marca,
        modelo=modelo,
        numero_serie=numero_serie,
        categoria=categoria,
        divisao_casa=divisao_casa,
        data_compra=data_compra,
        valor_compra=valor_compra,
        fornecedor_loja=fornecedor_loja,
        anos_garantia=anos_garantia,
        data_fim_garantia=data_fim_garantia,
        paperless_document_id=paperless_document_id,
        numero_fatura=numero_fatura,
        notas=notas,
        ativo=True,
    )
    session.add(eq)
    await session.commit()
    await session.refresh(eq)
    return eq


async def obter_manutencoes(
    session: AsyncSession,
    concluidas: bool = False
) -> list[ManutencaoCasa]:
    stmt = (
        select(ManutencaoCasa)
        .where(ManutencaoCasa.concluida.is_(concluidas))
        .order_by(ManutencaoCasa.proxima_data.asc().nulls_last())
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def criar_manutencao(
    session: AsyncSession,
    *,
    titulo: str,
    equipamento_id: uuid.UUID | None = None,
    divisao_casa: str = "Geral",
    periodicidade_meses: int = 12,
    ultima_data: date | None = None,
    proxima_data: date | None = None,
    custo_estimado: Decimal | None = None,
    tecnico_contacto: str | None = None,
    notas: str | None = None,
) -> ManutencaoCasa:
    m = ManutencaoCasa(
        titulo=titulo,
        equipamento_id=equipamento_id,
        divisao_casa=divisao_casa,
        periodicidade_meses=periodicidade_meses,
        ultima_data=ultima_data,
        proxima_data=proxima_data,
        custo_estimado=custo_estimado,
        tecnico_contacto=tecnico_contacto,
        notas=notas,
        concluida=False,
    )
    session.add(m)
    await session.commit()
    await session.refresh(m)
    return m


async def garantir_dados_iniciais(session: AsyncSession) -> None:
    """Carrega dados iniciais conhecidos da casa e equipamentos caso a tabela esteja vazia."""
    res = await session.execute(select(func.count(EquipamentoCasa.id)))
    count = res.scalar() or 0
    if count == 0:
        # Equipamento 1: Smartwatch Membersung da PCDIGA (Doc #72)
        await criar_equipamento(
            session,
            nome="Smartwatch Membersung Galaxy Watch 8 44mm GPS",
            marca="Membersung",
            modelo="SM-L330NZSAEUB",
            numero_serie="RFGYC3JH2HL",
            categoria="eletronica",
            divisao_casa="Escritório / Pessoal",
            data_compra=date(2026, 8, 19),
            valor_compra=Decimal("204.90"),
            fornecedor_loja="PCDIGA",
            anos_garantia=3,
            data_fim_garantia=date(2029, 8, 19),
            paperless_document_id=72,
            numero_fatura="ZFAT BZA1/9181724356",
            notas="Smartwatch prateado com GPS. Comprado na PCDIGA com tracking CTT DX138210620PT.",
        )
        # Equipamento 2: Caldeira / Climatização
        caldeira = await criar_equipamento(
            session,
            nome="Caldeira Mural de Aquecimento & Águas Quentes",
            marca="Vulcano / Junkers",
            modelo="Aquecimento Central & Sanitário",
            categoria="climatizacao",
            divisao_casa="Lavandaria / Cozinha",
            data_compra=date(2023, 10, 15),
            anos_garantia=3,
            data_fim_garantia=date(2026, 10, 15),
            notas="Caldeira a gás com circuito fechado para radiadores e AQS.",
        )
        # Equipamento 3: Ar Condicionado
        await criar_equipamento(
            session,
            nome="Ar Condicionado Split Inverter",
            marca="Daikin / Mitsubishi",
            modelo="Multi-Split Sala + Quartos",
            categoria="climatizacao",
            divisao_casa="Sala de Estar",
            data_compra=date(2024, 6, 1),
            anos_garantia=3,
            data_fim_garantia=date(2027, 6, 1),
            notas="Bomba de calor reversível A++.",
        )

        # Manutenção 1: Revisão anual da caldeira
        await criar_manutencao(
            session,
            titulo="Revisão Anual da Caldeira & Queimador",
            equipamento_id=caldeira.id,
            divisao_casa="Lavandaria / Cozinha",
            periodicidade_meses=12,
            ultima_data=date(2025, 10, 20),
            proxima_data=date(2026, 10, 20),
            custo_estimado=Decimal("85.00"),
            tecnico_contacto="Técnico Certificado DGEG",
            notas="Limpeza do queimador, verificação do vaso de expansão e pressão do circuito.",
        )
        # Manutenção 2: Limpeza dos filtros AC
        await criar_manutencao(
            session,
            titulo="Higienização & Limpeza de Filtros AC",
            divisao_casa="Geral",
            periodicidade_meses=6,
            ultima_data=date(2026, 5, 10),
            proxima_data=date(2026, 11, 10),
            custo_estimado=Decimal("0.00"),
            tecnico_contacto="Próprio / aa-stop-run",
            notas="Lavar filtros laváveis com água morna e aplicar spray antibacteriano.",
        )
