from datetime import date
from decimal import Decimal

import pytest

from ava.financas.recorrentes import gerar_movimentos_recorrentes_do_mes
from ava.repositories import alerta_repo, categoria_repo, movimento_repo, recorrente_repo, titular_repo


async def _titular(db_session, nome: str = "Nuno"):
    return await titular_repo.criar_titular(db_session, nome=nome, tipo="proprio")


async def _categoria(db_session, *, tipo: str, nome: str):
    grupo = await categoria_repo.criar_grupo(db_session, nome=f"Grupo {nome}")
    natureza = "extraordinario" if tipo == "receita" else "variavel"
    return await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome=nome, tipo=tipo, natureza=natureza
    )


@pytest.mark.asyncio
async def test_gera_entrada_e_saida_no_dia_configurado(db_session):
    # salário (entrada, dia 1) + renda (saída, dia 8), ambos ativos
    titular = await _titular(db_session)
    categoria_salario = await _categoria(db_session, tipo="receita", nome="Salário")
    categoria_renda = await _categoria(db_session, tipo="despesa", nome="Renda")

    await recorrente_repo.criar_recorrente(
        db_session,
        tipo="entrada",
        categoria_id=categoria_salario.id,
        titular_id=titular.id,
        valor=Decimal("1500.00"),
        dia_do_mes=1,
        descricao="Salário",
    )
    await recorrente_repo.criar_recorrente(
        db_session,
        tipo="saida",
        categoria_id=categoria_renda.id,
        titular_id=titular.id,
        valor=Decimal("650.00"),
        dia_do_mes=8,
        descricao="Renda",
    )
    await db_session.commit()

    criados = await gerar_movimentos_recorrentes_do_mes(db_session, referencia=date(2026, 7, 20))
    assert criados == 2

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31)
    )
    por_tipo = {m.tipo: m for m in movimentos}
    assert por_tipo["entrada"].data == date(2026, 7, 1)
    assert por_tipo["entrada"].origem == "regra"
    assert por_tipo["saida"].data == date(2026, 7, 8)
    assert por_tipo["saida"].linhas[0].categoria_id is not None


@pytest.mark.asyncio
async def test_nao_duplica_no_mesmo_mes(db_session):
    titular = await _titular(db_session)
    categoria = await _categoria(db_session, tipo="receita", nome="Salário")
    await recorrente_repo.criar_recorrente(
        db_session,
        tipo="entrada",
        categoria_id=categoria.id,
        titular_id=titular.id,
        valor=Decimal("1500.00"),
        dia_do_mes=1,
    )
    await db_session.commit()

    await gerar_movimentos_recorrentes_do_mes(db_session, referencia=date(2026, 7, 20))
    assert await gerar_movimentos_recorrentes_do_mes(db_session, referencia=date(2026, 7, 25)) == 0


@pytest.mark.asyncio
async def test_ignora_recorrentes_inativos(db_session):
    # um recorrente com ativo=False não gera nada
    titular = await _titular(db_session)
    categoria = await _categoria(db_session, tipo="receita", nome="Salário")
    recorrente = await recorrente_repo.criar_recorrente(
        db_session,
        tipo="entrada",
        categoria_id=categoria.id,
        titular_id=titular.id,
        valor=Decimal("1500.00"),
        dia_do_mes=1,
    )
    recorrente.ativo = False
    await db_session.commit()

    assert await gerar_movimentos_recorrentes_do_mes(db_session, referencia=date(2026, 7, 20)) == 0


@pytest.mark.asyncio
async def test_dia_31_num_mes_de_30_cai_no_ultimo_dia(db_session):
    # recorrente com dia_do_mes=31, referência em abril -> movimento a 30 de abril.
    # Referência ajustada para o próprio dia 30 (em vez de 20): com a porta "ainda não chegou
    # o dia" (ver test_dia_ainda_nao_chegado_nao_gera), uma referência de dia 20 seria anterior
    # ao dia 31 encaixado em 30, e o recorrente seria (corretamente) saltado nesse mês — o que
    # tornaria este teste sobre o encaixe em meses curtos incapaz de observar a data gerada.
    # Dia 30 é também o cenário crítico: se a porta comparasse contra o dia_do_mes cru (31) em
    # vez do dia já encaixado (30), 30 < 31 saltaria sempre este recorrente em abril — o bug
    # clássico que a porta tem de evitar.
    titular = await _titular(db_session)
    categoria = await _categoria(db_session, tipo="despesa", nome="Subscrição")
    await recorrente_repo.criar_recorrente(
        db_session,
        tipo="saida",
        categoria_id=categoria.id,
        titular_id=titular.id,
        valor=Decimal("9.99"),
        dia_do_mes=31,
    )
    await db_session.commit()

    criados = await gerar_movimentos_recorrentes_do_mes(db_session, referencia=date(2026, 4, 30))
    assert criados == 1

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 4, 1), fim=date(2026, 4, 30)
    )
    assert movimentos[0].data == date(2026, 4, 30)


@pytest.mark.asyncio
async def test_dia_ainda_nao_chegado_nao_gera(db_session):
    # recorrente a dia 28, referência no dia 10 -> o dia ainda não chegou este mês, não gera
    titular = await _titular(db_session)
    categoria = await _categoria(db_session, tipo="despesa", nome="Renda")
    await recorrente_repo.criar_recorrente(
        db_session,
        tipo="saida",
        categoria_id=categoria.id,
        titular_id=titular.id,
        valor=Decimal("650.00"),
        dia_do_mes=28,
    )
    await db_session.commit()

    criados = await gerar_movimentos_recorrentes_do_mes(db_session, referencia=date(2026, 7, 10))
    assert criados == 0

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31)
    )
    assert movimentos == []


@pytest.mark.asyncio
async def test_dia_chegado_gera_incluindo_fronteira_de_igualdade(db_session):
    # o mesmo recorrente (dia 28) gera quando a referência já chegou ao dia — incluindo a
    # igualdade exata (referencia.day == dia encaixado), fronteira que o "<" (não "<=") respeita
    titular = await _titular(db_session)
    categoria = await _categoria(db_session, tipo="despesa", nome="Renda")
    await recorrente_repo.criar_recorrente(
        db_session,
        tipo="saida",
        categoria_id=categoria.id,
        titular_id=titular.id,
        valor=Decimal("650.00"),
        dia_do_mes=28,
    )
    await db_session.commit()

    criados = await gerar_movimentos_recorrentes_do_mes(db_session, referencia=date(2026, 7, 28))
    assert criados == 1

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31)
    )
    assert movimentos[0].data == date(2026, 7, 28)


@pytest.mark.asyncio
async def test_recorrente_com_valor_invalido_nao_bloqueia_os_restantes(db_session):
    # Achado Importante (revisão final Fase A): gerar_movimentos_recorrentes_do_mes não tinha
    # isolamento por-recorrente — um único recorrente com valor <= 0 (dado legado de antes da
    # validação em movimento_repo.criar_movimento existir — ver ValorNaoPositivo — ou introduzido
    # por engano futuro via /rendimentos-recorrentes/novo, que não valida o sinal) fazia
    # criar_movimento levantar e interrompia o ciclo, impedindo TODOS os recorrentes seguintes do
    # mês de gerar o seu movimento. Mesmo princípio já corrigido para
    # sincronizar_obrigacoes_dos_veiculos_ativos (ava.alerts.scheduler): um item avariado não pode
    # bloquear os restantes.
    titular = await _titular(db_session)
    categoria_invalida = await _categoria(db_session, tipo="despesa", nome="Mal configurado")
    categoria_saudavel = await _categoria(db_session, tipo="despesa", nome="Renda")

    recorrente_invalido = await recorrente_repo.criar_recorrente(
        db_session,
        tipo="saida",
        categoria_id=categoria_invalida.id,
        titular_id=titular.id,
        valor=Decimal("-50.00"),  # dado inválido — deveria ter sido bloqueado na origem
        dia_do_mes=5,
    )
    await recorrente_repo.criar_recorrente(
        db_session,
        tipo="saida",
        categoria_id=categoria_saudavel.id,
        titular_id=titular.id,
        valor=Decimal("650.00"),
        dia_do_mes=8,
    )
    await db_session.commit()
    # Capturado em variável simples ANTES de invocar a função em teste: esta chama
    # session.rollback() no ramo de falha, o que expira TODOS os objetos ORM da sessão (mesmo
    # padrão de test_job_obrigacoes_falha_num_veiculo_nao_bloqueia_os_restantes em
    # test_scheduler.py) — ler recorrente_invalido.id depois disso rebentaria com MissingGreenlet.
    recorrente_invalido_id = recorrente_invalido.id

    # Não deve propagar ValorNaoPositivo — a exceção fica contida ao recorrente que falhou.
    criados = await gerar_movimentos_recorrentes_do_mes(db_session, referencia=date(2026, 7, 20))

    # só o recorrente saudável gerou o seu movimento.
    assert criados == 1
    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31)
    )
    assert len(movimentos) == 1
    assert movimentos[0].valor == Decimal("650.00")

    # a falha não ficou silenciosa: alerta ativo identificando o recorrente concreto.
    alertas_falha = [
        a for a in await alerta_repo.listar_nao_enviados(db_session) if a.tipo == "falha_recorrente"
    ]
    assert len(alertas_falha) == 1
    assert str(recorrente_invalido_id) in alertas_falha[0].mensagem


@pytest.mark.asyncio
async def test_recorrente_saudavel_antes_do_invalido_nao_e_desfeito_pelo_rollback_seguinte(db_session):
    # Achado 3 (revisão final de fecho da Fase A): o teste acima
    # (test_recorrente_com_valor_invalido_nao_bloqueia_os_restantes) só prova isolamento quando o
    # inválido vem PRIMEIRO na iteração — não há nada saudável antes dele para se perder. O cenário
    # que faltava, e que este teste prova: um recorrente SAUDÁVEL processado com sucesso primeiro
    # (criar_movimento faz só flush(), nunca commit()) e um recorrente INVÁLIDO processado a seguir,
    # no mesmo ciclo. Antes desta correção o único commit vivia no fim da função inteira — o
    # session.rollback() do except do inválido desfazia também o movimento do saudável, ainda por
    # commitar, mesmo sendo válido. A correção commita logo após cada sucesso (criados += 1), o
    # mesmo padrão de sincronizar_obrigacoes_dos_veiculos_ativos/sincronizar_obrigacoes_veiculo.
    #
    # dia_do_mes controla a ordem de iteração agora que recorrente_repo.listar_ativos tem
    # ORDER BY dia_do_mes determinístico — o saudável usa um dia menor para garantir que é
    # processado antes do inválido, independentemente da ordem de criação.
    titular = await _titular(db_session)
    categoria_saudavel = await _categoria(db_session, tipo="despesa", nome="Renda")
    categoria_invalida = await _categoria(db_session, tipo="despesa", nome="Mal configurado")

    await recorrente_repo.criar_recorrente(
        db_session,
        tipo="saida",
        categoria_id=categoria_saudavel.id,
        titular_id=titular.id,
        valor=Decimal("650.00"),
        dia_do_mes=5,  # processado primeiro
        descricao="Renda",
    )
    recorrente_invalido = await recorrente_repo.criar_recorrente(
        db_session,
        tipo="saida",
        categoria_id=categoria_invalida.id,
        titular_id=titular.id,
        valor=Decimal("-50.00"),  # dado inválido — deveria ter sido bloqueado na origem
        dia_do_mes=8,  # processado depois
    )
    await db_session.commit()
    # Capturado ANTES de invocar a função em teste — ver comentário equivalente no teste acima
    # sobre expiração de objetos ORM após rollback.
    recorrente_invalido_id = recorrente_invalido.id

    criados = await gerar_movimentos_recorrentes_do_mes(db_session, referencia=date(2026, 7, 20))

    # o movimento do saudável continua persistido depois do ciclo terminar, apesar de o
    # recorrente seguinte ter falhado e provocado um rollback.
    assert criados == 1
    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31)
    )
    assert len(movimentos) == 1
    assert movimentos[0].valor == Decimal("650.00")

    # a falha do inválido continua sinalizada, tal como no teste da ordem inversa.
    alertas_falha = [
        a for a in await alerta_repo.listar_nao_enviados(db_session) if a.tipo == "falha_recorrente"
    ]
    assert len(alertas_falha) == 1
    assert str(recorrente_invalido_id) in alertas_falha[0].mensagem
