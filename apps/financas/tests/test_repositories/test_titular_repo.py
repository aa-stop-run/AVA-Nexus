import pytest

from ava.repositories.titular_repo import criar_titular, obter_titular


@pytest.mark.asyncio
async def test_criar_e_obter_titular(db_session):
    titular = await criar_titular(db_session, nome="Ana", tipo="conjuge")

    encontrado = await obter_titular(db_session, titular.id)

    assert encontrado is not None
    assert encontrado.nome == "Ana"
    assert encontrado.tipo == "conjuge"
