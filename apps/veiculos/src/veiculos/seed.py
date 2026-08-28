import asyncio
import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from veiculos.config import get_settings
from veiculos.db import get_session_factory
from veiculos.models.veiculo import Veiculo
from veiculos.repositories import veiculo_repo

logger = logging.getLogger("veiculos.seed")


async def semear_veiculos_iniciais(session: AsyncSession):
    veiculos = await veiculo_repo.listar_veiculos(session)
    if veiculos:
        return

    # Demo Vehicle 1: Sedan 2.0 TDI
    await veiculo_repo.criar_veiculo(
        session,
        nome="Sedan 2.0 TDI",
        tipo="carro",
        matricula="AA-01-BB",
        ano_matricula=2018,
        mes_matricula=6,
        combustivel="gasoleo",
        km_atual=95000,
        seguradora="Demo Insurance Co.",
        data_fim_seguro=date(2027, 2, 15),
    )

    # Demo Vehicle 2: City Hatchback 1.2
    await veiculo_repo.criar_veiculo(
        session,
        nome="City Hatchback 1.2",
        tipo="carro",
        matricula="CC-02-DD",
        ano_matricula=2021,
        mes_matricula=10,
        combustivel="gasolina",
        km_atual=42000,
        seguradora="Demo Mutual",
        data_fim_seguro=date(2026, 11, 30),
    )

    # Demo Vehicle 3: Commuter 125cc
    await veiculo_repo.criar_veiculo(
        session,
        nome="Commuter 125cc",
        tipo="mota",
        matricula="EE-03-FF",
        ano_matricula=2023,
        mes_matricula=5,
        combustivel="gasolina",
        km_atual=5200,
        seguradora="Demo Assurance",
        data_fim_seguro=date(2027, 5, 20),
    )


async def main():
    factory = get_session_factory()
    async with factory() as session:
        await semear_veiculos_iniciais(session)
        print("✓ Veículos de demonstração semeados com sucesso!")


if __name__ == "__main__":
    asyncio.run(main())
