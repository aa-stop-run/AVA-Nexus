import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from veiculos.models.veiculo import Veiculo
from veiculos.models.manutencao import VeiculoManutencao
from veiculos.models.abastecimento import VeiculoAbastecimento


async def listar_veiculos(session: AsyncSession, *, apenas_ativos: bool = True) -> list[Veiculo]:
    stmt = select(Veiculo).options(
        selectinload(Veiculo.manutencoes),
        selectinload(Veiculo.abastecimentos),
    )
    if apenas_ativos:
        stmt = stmt.where(Veiculo.ativo.is_(True))
    stmt = stmt.order_by(Veiculo.nome.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def obter_veiculo_por_id(session: AsyncSession, veiculo_id: uuid.UUID) -> Veiculo | None:
    stmt = (
        select(Veiculo)
        .options(
            selectinload(Veiculo.manutencoes),
            selectinload(Veiculo.abastecimentos),
        )
        .where(Veiculo.id == veiculo_id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def criar_veiculo(
    session: AsyncSession,
    *,
    nome: str,
    tipo: str = "carro",
    matricula: str | None = None,
    ano_matricula: int | None = None,
    mes_matricula: int | None = None,
    combustivel: str = "gasoleo",
    km_atual: int = 0,
    data_proxima_ipo: date | None = None,
    seguradora: str | None = None,
    numero_apolice: str | None = None,
    data_fim_seguro: date | None = None,
    titular_id: uuid.UUID | None = None,
    ativo_id: uuid.UUID | None = None,
) -> Veiculo:
    v = Veiculo(
        nome=nome,
        tipo=tipo,
        matricula=matricula,
        ano_matricula=ano_matricula,
        mes_matricula=mes_matricula,
        combustivel=combustivel,
        km_atual=km_atual,
        data_proxima_ipo=data_proxima_ipo,
        seguradora=seguradora,
        numero_apolice=numero_apolice,
        data_fim_seguro=data_fim_seguro,
        titular_id=titular_id,
        ativo_id=ativo_id,
    )
    session.add(v)
    await session.commit()
    await session.refresh(v)
    return v


async def atualizar_veiculo(
    session: AsyncSession,
    veiculo_id: uuid.UUID,
    *,
    nome: str,
    tipo: str,
    matricula: str | None = None,
    ano_matricula: int | None = None,
    mes_matricula: int | None = None,
    combustivel: str = "gasoleo",
    km_atual: int = 0,
    data_proxima_ipo: date | None = None,
    seguradora: str | None = None,
    numero_apolice: str | None = None,
    data_fim_seguro: date | None = None,
) -> Veiculo | None:
    v = await obter_veiculo_por_id(session, veiculo_id)
    if v:
        v.nome = nome
        v.tipo = tipo
        v.matricula = matricula
        v.ano_matricula = ano_matricula
        v.mes_matricula = mes_matricula
        v.combustivel = combustivel
        v.km_atual = max(v.km_atual, km_atual)
        v.data_proxima_ipo = data_proxima_ipo
        v.seguradora = seguradora
        v.numero_apolice = numero_apolice
        v.data_fim_seguro = data_fim_seguro
        await session.commit()
        await session.refresh(v)
    return v


async def apagar_veiculo(session: AsyncSession, veiculo_id: uuid.UUID) -> bool:
    v = await obter_veiculo_por_id(session, veiculo_id)
    if v:
        await session.delete(v)
        await session.commit()
        return True
    return False


async def atualizar_km(session: AsyncSession, veiculo_id: uuid.UUID, novo_km: int) -> Veiculo | None:
    v = await obter_veiculo_por_id(session, veiculo_id)
    if v:
        v.km_atual = max(v.km_atual, novo_km)
        await session.commit()
        await session.refresh(v)
    return v


async def registar_manutencao(
    session: AsyncSession,
    *,
    veiculo_id: uuid.UUID,
    data: date,
    km: int,
    tipo_servico: str,
    descricao: str,
    oficina: str | None = None,
    custo: Decimal = Decimal("0.00"),
    proxima_revisao_km: int | None = None,
    proxima_revisao_data: date | None = None,
    documento_id: uuid.UUID | None = None,
) -> VeiculoManutencao:
    m = VeiculoManutencao(
        veiculo_id=veiculo_id,
        data=data,
        km=km,
        tipo_servico=tipo_servico,
        descricao=descricao,
        oficina=oficina,
        custo=custo,
        proxima_revisao_km=proxima_revisao_km,
        proxima_revisao_data=proxima_revisao_data,
        documento_id=documento_id,
    )
    session.add(m)
    
    # Atualiza o odómetro do veículo se o km for superior
    v = await obter_veiculo_por_id(session, veiculo_id)
    if v and km > v.km_atual:
        v.km_atual = km
        
    await session.commit()
    await session.refresh(m)
    return m


async def listar_manutencoes(session: AsyncSession, veiculo_id: uuid.UUID) -> list[VeiculoManutencao]:
    stmt = (
        select(VeiculoManutencao)
        .where(VeiculoManutencao.veiculo_id == veiculo_id)
        .order_by(VeiculoManutencao.data.desc(), VeiculoManutencao.km.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def registar_abastecimento(
    session: AsyncSession,
    *,
    veiculo_id: uuid.UUID,
    data: date,
    km: int,
    quantidade: Decimal,
    preco_total: Decimal,
    preco_unitario: Decimal | None = None,
    posto: str | None = None,
    tanque_cheio: bool = True,
) -> VeiculoAbastecimento:
    if preco_unitario is None and quantidade > Decimal("0"):
        preco_unitario = (preco_total / quantidade).quantize(Decimal("0.001"))

    ab = VeiculoAbastecimento(
        veiculo_id=veiculo_id,
        data=data,
        km=km,
        quantidade=quantidade,
        preco_total=preco_total,
        preco_unitario=preco_unitario,
        posto=posto,
        tanque_cheio=tanque_cheio,
    )
    session.add(ab)
    
    # Atualiza odómetro
    v = await obter_veiculo_por_id(session, veiculo_id)
    if v and km > v.km_atual:
        v.km_atual = km
        
    await session.commit()
    await session.refresh(ab)
    return ab


async def listar_abastecimentos(session: AsyncSession, veiculo_id: uuid.UUID) -> list[VeiculoAbastecimento]:
    stmt = (
        select(VeiculoAbastecimento)
        .where(VeiculoAbastecimento.veiculo_id == veiculo_id)
        .order_by(VeiculoAbastecimento.data.desc(), VeiculoAbastecimento.km.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
