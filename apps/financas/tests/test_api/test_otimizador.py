import pytest
from datetime import date
from decimal import Decimal

from tests.test_api.test_dashboard import _client_para
from ava.repositories import titular_repo, conta_repo, categoria_repo, movimento_repo, contrato_repo


@pytest.mark.asyncio
async def test_get_otimizador_page_retorna_200(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="aa-stop-run", tipo="proprio")
    c_bpi = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta BPI"
    )
    grupo = await categoria_repo.criar_grupo(db_session, nome="Subscrições")
    cat = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Streaming", tipo="despesa", natureza="variavel"
    )
    await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("15.99"),
        data=date(2026, 8, 5),
        origem="ficheiro",
        descricao="NETFLIX COM",
        conta_id=c_bpi.id,
        titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("15.99"), categoria_id=cat.id)],
    )
    await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("15.99"),
        data=date(2026, 7, 5),
        origem="ficheiro",
        descricao="NETFLIX COM",
        conta_id=c_bpi.id,
        titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("15.99"), categoria_id=cat.id)],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/otimizador?periodo=2026-08")

    assert resposta.status_code == 200
    assert "Radar de Poupança" in resposta.text
    assert "Subscrições" in resposta.text
    assert "Potencial de Poupança" in resposta.text


@pytest.mark.asyncio
async def test_post_simular_acao_subscricao_retorna_html_atualizado(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/otimizador/simular-acao-subscricao",
            data={
                "subscricao_id": "sub-1",
                "nome": "Netflix",
                "categoria_nome": "Streaming",
                "valor_periodo": "15.99",
                "periodicidade": "mensal",
                "custo_anual": "191.88",
                "nova_acao": "cancelar",
            },
        )

    assert resposta.status_code == 200
    assert "A cancelar" in resposta.text
    assert "191,88" in resposta.text
