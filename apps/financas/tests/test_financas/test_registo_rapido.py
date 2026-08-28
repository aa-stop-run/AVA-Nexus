from datetime import date
from decimal import Decimal

import pytest

from ava.financas.registo_rapido import registar_movimento_rapido
from ava.repositories import movimento_repo, titular_repo


async def _titular(db_session, nome="Nuno"):
    titular = await titular_repo.criar_titular(db_session, nome=nome, tipo="proprio")
    await db_session.commit()
    return titular


async def _movimentos(db_session):
    return await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2000, 1, 1), fim=date(2100, 1, 1)
    )


@pytest.mark.asyncio
async def test_regista_despesa_com_descricao_e_valor(db_session):
    titular = await _titular(db_session)

    resposta = await registar_movimento_rapido(
        db_session, titular=titular, texto="Almoço 12,50", tipo="saida", ambito="comum"
    )

    assert "Nuno" in resposta
    movimentos = await _movimentos(db_session)
    assert len(movimentos) == 1
    movimento = movimentos[0]
    assert movimento.tipo == "saida"
    assert movimento.valor == Decimal("12.50")
    assert movimento.descricao == "Almoço"
    assert movimento.ambito == "comum"
    # "manual" e não "telegram": o bot foi removido e este é o caminho da própria app.
    assert movimento.origem == "manual"
    assert movimento.titular_id == titular.id


@pytest.mark.asyncio
async def test_regista_rendimento_e_aceita_ponto_decimal_e_simbolo_de_euro(db_session):
    titular = await _titular(db_session)

    await registar_movimento_rapido(
        db_session, titular=titular, texto="Venda OLX 50.00 €", tipo="entrada"
    )

    movimentos = await _movimentos(db_session)
    assert len(movimentos) == 1
    assert movimentos[0].tipo == "entrada"
    assert movimentos[0].valor == Decimal("50.00")
    assert movimentos[0].descricao == "Venda OLX"


@pytest.mark.asyncio
async def test_texto_sem_valor_no_fim_nao_cria_nada_e_explica_o_formato(db_session):
    # O valor TEM de estar no fim — é isso que torna a descrição não-ambígua. Um texto livre
    # como este era interpretado pelo LLM enquanto a captura passava pela fila; agora não é.
    titular = await _titular(db_session)

    resposta = await registar_movimento_rapido(
        db_session, titular=titular, texto="bónus 200 do trabalho extra", tipo="entrada"
    )

    assert "Formato inválido" in resposta
    assert await _movimentos(db_session) == []


@pytest.mark.asyncio
async def test_valor_zero_ou_negativo_nao_cria_movimento(db_session):
    titular = await _titular(db_session)

    resposta = await registar_movimento_rapido(
        db_session, titular=titular, texto="Estorno 0", tipo="saida"
    )

    assert "zero nem negativo" in resposta
    assert await _movimentos(db_session) == []


@pytest.mark.asyncio
async def test_valor_muito_acima_do_historico_e_recusado_sem_criar_movimento(db_session):
    # Teto de magnitude (A-P3): protege contra um engano que multiplique o valor por 100.
    titular = await _titular(db_session)
    for _ in range(3):
        await registar_movimento_rapido(
            db_session, titular=titular, texto="Café 2,00", tipo="saida"
        )

    resposta = await registar_movimento_rapido(
        db_session, titular=titular, texto="Café 200,00", tipo="saida"
    )

    assert "foge muito" in resposta
    assert len(await _movimentos(db_session)) == 3  # os três cafés, não o quarto


@pytest.mark.asyncio
async def test_sem_historico_qualquer_valor_passa(db_session):
    # valor_dentro_magnitude_historica devolve True sem histórico — o primeiro registo de um
    # titular nunca pode ser recusado por não ter com o que comparar.
    titular = await _titular(db_session)

    resposta = await registar_movimento_rapido(
        db_session, titular=titular, texto="Portátil 1500", tipo="saida"
    )

    assert "Registado" in resposta
    assert len(await _movimentos(db_session)) == 1


@pytest.mark.asyncio
async def test_tipo_invalido_e_erro_de_programacao_nao_mensagem_ao_utilizador(db_session):
    titular = await _titular(db_session)

    with pytest.raises(ValueError):
        await registar_movimento_rapido(
            db_session, titular=titular, texto="Almoço 10", tipo="transferencia"
        )


@pytest.mark.asyncio
async def test_origem_e_a_mesma_que_a_rota_do_formulario_completo(db_session):
    # Regressão: /registo gravava "web" e o registo rápido "manual". Como a listagem de
    # por-categorizar filtra por origem, os movimentos de uma das rotas não apareciam. As duas
    # são a mesma coisa no ledger (o utilizador escreveu isto na app) e têm de concordar.
    from ava.repositories.movimento_repo import ORIGENS_REGISTO_MANUAL

    titular = await _titular(db_session)
    await registar_movimento_rapido(
        db_session, titular=titular, texto="Almoço 10", tipo="saida"
    )

    movimento = (await _movimentos(db_session))[0]
    assert movimento.origem == "manual"
    # As origens históricas continuam a contar — senão o que já está gravado desaparece.
    assert movimento.origem in ORIGENS_REGISTO_MANUAL
    assert "web" in ORIGENS_REGISTO_MANUAL
    assert "telegram" in ORIGENS_REGISTO_MANUAL
