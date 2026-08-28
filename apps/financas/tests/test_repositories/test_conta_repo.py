import pytest

from ava.repositories import conta_repo, titular_repo


@pytest.mark.asyncio
async def test_criar_e_listar_por_titular(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")

    await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem CGD"
    )
    await conta_repo.criar_conta(
        db_session,
        titular_id=titular.id,
        instituicao="Edenred",
        tipo="cartao_refeicao",
        nome="Cartão Edenred",
    )

    contas = await conta_repo.listar_por_titular(db_session, titular.id)

    assert len(contas) == 2
    assert {c.tipo for c in contas} == {"a_ordem", "cartao_refeicao"}


@pytest.mark.asyncio
async def test_criar_conta_categoria_divida_default_none(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")

    conta_sem_categoria = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem CGD"
    )

    assert conta_sem_categoria.categoria_divida is None


@pytest.mark.asyncio
async def test_criar_conta_armazena_categoria_divida(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")

    conta_divida = await conta_repo.criar_conta(
        db_session,
        titular_id=titular.id,
        instituicao="CGD",
        tipo="divida",
        nome="Mortgage & Loans",
        categoria_divida="habitacao",
    )

    assert conta_divida.categoria_divida == "habitacao"


@pytest.mark.asyncio
async def test_obter_ou_criar_por_instituicao_e_idempotente(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")

    primeira = await conta_repo.obter_ou_criar_por_instituicao(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    segunda = await conta_repo.obter_ou_criar_por_instituicao(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )

    assert primeira.id == segunda.id


@pytest.mark.asyncio
async def test_obter_ou_criar_por_instituicao_resolve_ambiguidade_por_nome(db_session):
    # Achado real (aprovação manual de extratos em produção): com 2+ contas já existentes do
    # mesmo tipo na mesma instituição (ex.: Crédito Pessoal + Cartão BPI Classic, ambas
    # instituicao="BPI", tipo="divida"), a query por (titular, instituicao, tipo) apanha as duas —
    # isto rebentava com MultipleResultsFound. Este teste prova que, com ambiguidade genuína, a
    # função agora desempata pelo nome em vez de rebentar — e que NÃO cria uma terceira conta.
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")

    pessoal = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Crédito Pessoal"
    )
    cartao = await conta_repo.criar_conta(
        db_session,
        titular_id=titular.id,
        instituicao="BPI",
        tipo="divida",
        nome="Cartão BPI Classic 123",
    )
    await db_session.commit()

    encontrada = await conta_repo.obter_ou_criar_por_instituicao(
        db_session,
        titular_id=titular.id,
        instituicao="BPI",
        tipo="divida",
        nome="Cartão BPI Classic 123",
    )

    assert encontrada.id == cartao.id
    assert encontrada.id != pessoal.id
    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 2  # nenhuma conta nova foi criada por engano


@pytest.mark.asyncio
async def test_obter_ou_criar_por_instituicao_cria_nova_quando_ambiguidade_sem_nome_correspondente(
    db_session,
):
    # Mesma ambiguidade do teste acima, mas o nome pedido não bate certo com NENHUMA das contas
    # já existentes — mesma decisão de desenho que obter_ou_criar_por_nome já toma no caminho
    # multi-conta: criar uma conta nova em vez de escolher às cegas entre as candidatas.
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")

    await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Crédito Pessoal"
    )
    await conta_repo.criar_conta(
        db_session,
        titular_id=titular.id,
        instituicao="BPI",
        tipo="divida",
        nome="Cartão BPI Classic 123",
    )
    await db_session.commit()

    nova = await conta_repo.obter_ou_criar_por_instituicao(
        db_session,
        titular_id=titular.id,
        instituicao="BPI",
        tipo="divida",
        nome="Mortgage & Loans",
    )

    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 3
    assert nova.nome == "Mortgage & Loans"


@pytest.mark.asyncio
async def test_obter_ou_criar_por_nome_e_idempotente(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")

    primeira = await conta_repo.obter_ou_criar_por_nome(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Crédito Pessoal"
    )
    segunda = await conta_repo.obter_ou_criar_por_nome(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Crédito Pessoal"
    )

    assert primeira.id == segunda.id


@pytest.mark.asyncio
async def test_obter_ou_criar_por_nome_distingue_contas_com_mesmo_tipo_e_nome_diferente(db_session):
    # Tarefa 10 — a armadilha central: obter_ou_criar_por_instituicao combina por
    # (titular_id, instituicao, tipo), sem "nome", o que fundiria "Crédito Pessoal" e "Crédito
    # Habitação/Hipotecário" (ambos tipo="divida", mesma instituicao="BPI") numa só conta.
    # obter_ou_criar_por_nome acrescenta "nome" ao critério de combinação precisamente para
    # evitar isso — este teste prova que ficam como duas Conta distintas.
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")

    pessoal = await conta_repo.obter_ou_criar_por_nome(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Crédito Pessoal"
    )
    habitacao = await conta_repo.obter_ou_criar_por_nome(
        db_session,
        titular_id=titular.id,
        instituicao="BPI",
        tipo="divida",
        nome="Mortgage & Loans/Hipotecário",
    )

    assert pessoal.id != habitacao.id
    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 2


@pytest.mark.asyncio
async def test_obter_ou_criar_por_nome_encontra_conta_emprestimo_existente_ao_pedir_tipo_divida(db_session):
    # Incidente real em produção (2026-08-15): o Extracto Integrado do BPI passa sempre
    # tipo_conta="divida" (genérico) a obter_ou_criar_por_nome, mas as contas de crédito reais já
    # estavam classificadas com o tipo mais específico "emprestimo" (categoria "habitacao"/
    # "pessoal"). A comparação Conta.tipo == tipo (exata, sem a família TIPOS_PASSIVO que
    # obter_ou_criar_por_instituicao já respeitava) nunca batia, apesar de nome/instituicao/
    # titular serem idênticos — criava uma conta "fantasma" nova a cada importação, duplicando o
    # saldo de dívida mostrado em /patrimonio (332 mil € em vez de 167 mil €, no incidente real).
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")

    existente = await conta_repo.criar_conta(
        db_session,
        titular_id=titular.id,
        instituicao="BPI",
        tipo="emprestimo",
        nome="Mortgage & Loans/Hipotecário",
        categoria_divida="habitacao",
    )
    await db_session.commit()

    encontrada = await conta_repo.obter_ou_criar_por_nome(
        db_session,
        titular_id=titular.id,
        instituicao="BPI",
        tipo="divida",
        nome="Mortgage & Loans/Hipotecário",
    )

    assert encontrada.id == existente.id
    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 1  # nenhuma conta fantasma foi criada


@pytest.mark.asyncio
async def test_conta_aceita_categoria_investimento(db_session):
    from ava.models.conta import Conta

    titular = await titular_repo.criar_titular(db_session, nome="Teste", tipo="adulto")
    await db_session.flush()

    conta = Conta(
        titular_id=titular.id,
        instituicao="XTB",
        tipo="investimento",
        categoria_investimento="etf",
        nome="ETF Mundial",
    )
    db_session.add(conta)
    await db_session.flush()

    assert conta.categoria_investimento == "etf"


@pytest.mark.asyncio
async def test_criar_conta_aceita_ativo_id(db_session):
    from ava.repositories import ativo_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    casa = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Casa", tipo="casa"
    )
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida",
        nome="Mortgage & Loans", categoria_divida="habitacao", ativo_id=casa.id,
    )
    await db_session.commit()

    assert conta.ativo_id == casa.id


@pytest.mark.asyncio
async def test_conta_sem_bem_ligado_tem_ativo_id_none(db_session):
    # O caso normal: contas à ordem, cartões e o crédito pessoal não pertencem a bem nenhum.
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await db_session.commit()

    assert conta.ativo_id is None


@pytest.mark.asyncio
async def test_definir_ativo_liga_e_desliga(db_session):
    from ava.repositories import ativo_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    casa = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Casa", tipo="casa"
    )
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida",
        nome="Mortgage & Loans", categoria_divida="habitacao",
    )
    await db_session.commit()

    assert await conta_repo.definir_ativo(db_session, conta.id, casa.id) is True
    await db_session.commit()
    await db_session.refresh(conta)
    assert conta.ativo_id == casa.id

    # Desligar é como se corrige um engano.
    assert await conta_repo.definir_ativo(db_session, conta.id, None) is True
    await db_session.commit()
    await db_session.refresh(conta)
    assert conta.ativo_id is None


@pytest.mark.asyncio
async def test_definir_ativo_em_conta_inexistente_devolve_false(db_session):
    import uuid as _uuid

    assert await conta_repo.definir_ativo(db_session, _uuid.uuid4(), None) is False


@pytest.mark.asyncio
async def test_listar_dividas_do_ativo_traz_so_as_ligadas(db_session):
    # Um bem pode ter varias dividas (hipoteca + credito para obras) — N:1, ver spec §2.
    from ava.repositories import ativo_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    casa = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Casa", tipo="casa"
    )
    carro = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="City Hatchback 1.2", tipo="carro"
    )
    hipoteca = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida",
        nome="Mortgage & Loans", ativo_id=casa.id,
    )
    obras = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida",
        nome="Crédito Obras", ativo_id=casa.id,
    )
    await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BBVA", tipo="divida",
        nome="Crédito Automóvel", ativo_id=carro.id,
    )
    await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida",
        nome="Crédito Pessoal",
    )
    await db_session.commit()

    dividas = await conta_repo.listar_dividas_do_ativo(db_session, casa.id)

    assert sorted(c.id for c in dividas) == sorted([hipoteca.id, obras.id])
