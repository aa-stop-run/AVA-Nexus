import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from saude.models.base import Base
from saude.models.titular import Titular
from saude.models.perfil import PerfilSaude
from saude.models.consulta import ConsultaMedica
from saude.models.exame import ExameMedico
from saude.models.medicamento import Medicamento, MedicamentoAtivo, MedicamentoRegistoToma, MedicamentoTomaHorario
from saude.models.prescricao import PrescricaoMedica
from saude.models.vacina import VacinaRegisto

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
