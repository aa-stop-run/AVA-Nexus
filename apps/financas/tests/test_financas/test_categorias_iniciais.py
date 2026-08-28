import pytest
from sqlalchemy import text

from ava.financas.categorias_iniciais import GRUPOS_INICIAIS, mover_categoria_de_grupo, semear_categorias


@pytest.mark.asyncio
async def test_semear_cria_grupos_e_categorias(db_session):
    conn = await db_session.connection()
    criadas = await conn.run_sync(semear_categorias)

    total_esperado = sum(len(g.categorias) for g in GRUPOS_INICIAIS)
    assert criadas == total_esperado

    grupos = (await db_session.execute(text("SELECT nome FROM grupo_categoria"))).scalars().all()
    assert "Habitação" in grupos
    assert "Rendimentos" in grupos


@pytest.mark.asyncio
async def test_semear_marca_o_contador_nas_categorias_que_o_tem(db_session):
    conn = await db_session.connection()
    await conn.run_sync(semear_categorias)

    linha = (
        await db_session.execute(
            text("SELECT unidade_contador FROM categoria WHERE nome = 'Eletricidade'")
        )
    ).scalar_one()
    assert linha == "kWh"

    sem_contador = (
        await db_session.execute(text("SELECT unidade_contador FROM categoria WHERE nome = 'Renda'"))
    ).scalar_one()
    assert sem_contador is None


@pytest.mark.asyncio
async def test_semear_e_idempotente(db_session):
    conn = await db_session.connection()
    await conn.run_sync(semear_categorias)
    criadas_segunda_vez = await conn.run_sync(semear_categorias)

    assert criadas_segunda_vez == 0
    total = (await db_session.execute(text("SELECT count(*) FROM categoria"))).scalar_one()
    assert total == sum(len(g.categorias) for g in GRUPOS_INICIAIS)


@pytest.mark.asyncio
async def test_semear_categorias_cria_grupo_encargos_financeiros(db_session):
    from ava.repositories import categoria_repo

    conn = await db_session.connection()
    await conn.run_sync(semear_categorias)
    await db_session.commit()

    juros = await categoria_repo.obter_por_nomes(
        db_session, grupo="Encargos financeiros", nome="Juros de crédito"
    )
    assert juros is not None
    assert juros.tipo == "despesa"


@pytest.mark.asyncio
async def test_semear_categorias_cria_pagamento_de_credito_e_grupos_animais_profissional(db_session):
    from ava.repositories import categoria_repo

    conn = await db_session.connection()
    await conn.run_sync(semear_categorias)
    await db_session.commit()

    pagamento_credito = await categoria_repo.obter_por_nomes(
        db_session, grupo="Encargos financeiros", nome="Pagamento de crédito"
    )
    assert pagamento_credito is not None

    veterinario = await categoria_repo.obter_por_nomes(db_session, grupo="Animais", nome="Veterinário")
    assert veterinario is not None

    profissional = await categoria_repo.obter_por_nomes(db_session, grupo="Profissional", nome="Profissional")
    assert profissional is not None


@pytest.mark.asyncio
async def test_semear_cria_seguro_de_vida_ja_em_habitacao_numa_bd_nova(db_session):
    # Numa BD nova, "Seguro de vida" já nasce em "Habitação" (ver GRUPOS_INICIAIS) — não em
    # "Impostos e seguros" (onde nasceu historicamente, antes do pedido do utilizador de a
    # mudar). A migração f57babb7aacc só precisa de mover_categoria_de_grupo para BDs antigas
    # que já tinham a categoria semeada no grupo antigo.
    from ava.repositories import categoria_repo

    conn = await db_session.connection()
    await conn.run_sync(semear_categorias)
    await db_session.commit()

    em_habitacao = await categoria_repo.obter_por_nomes(db_session, grupo="Habitação", nome="Seguro de vida")
    assert em_habitacao is not None

    em_impostos = await categoria_repo.obter_por_nomes(db_session, grupo="Impostos e seguros", nome="Seguro de vida")
    assert em_impostos is None


@pytest.mark.asyncio
async def test_mover_antes_de_semear_nao_duplica_seguro_de_vida_numa_bd_ja_seeded(db_session):
    # Reproduz o estado real de produção: uma BD que já correu a sementeira ORIGINAL (antes
    # deste pedido do utilizador), com "Seguro de vida" ainda em "Impostos e seguros" — não em
    # "Habitação", que GRUPOS_INICIAIS só passou a listar depois. Se semear_categorias corresse
    # ANTES de mover_categoria_de_grupo (ordem que a migração f57babb7aacc chegou a ter),
    # criaria uma "Seguro de vida" nova em "Habitação" — e mover_categoria_de_grupo a seguir
    # colidiria com essa cópia fresca ao tentar mover lá a categoria antiga. Este teste prova que
    # a ordem correta (mover primeiro, semear depois — a mesma da migração) evita a colisão.
    from ava.repositories import categoria_repo

    grupo_impostos = await categoria_repo.criar_grupo(db_session, nome="Impostos e seguros", ordem=1)
    await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo_impostos.id, nome="Seguro de vida", tipo="despesa", natureza="variavel"
    )
    # "Habitação" já existe em produção (criado há muito por d6f0ed375db0) — sem esta linha, o
    # guard de mover_categoria_de_grupo (grupo destino inexistente) desactiva-se sozinho e o
    # teste deixaria de reproduzir o cenário real.
    await categoria_repo.criar_grupo(db_session, nome="Habitação", ordem=2)
    await db_session.commit()

    conn = await db_session.connection()
    await conn.run_sync(
        lambda c: mover_categoria_de_grupo(
            c,
            categoria_nome="Seguro de vida",
            grupo_origem_nome="Impostos e seguros",
            grupo_destino_nome="Habitação",
        )
    )
    await conn.run_sync(semear_categorias)
    await db_session.commit()

    total = (
        await db_session.execute(text("SELECT count(*) FROM categoria WHERE nome = 'Seguro de vida'"))
    ).scalar_one()
    assert total == 1

    em_habitacao = await categoria_repo.obter_por_nomes(db_session, grupo="Habitação", nome="Seguro de vida")
    assert em_habitacao is not None


@pytest.mark.asyncio
async def test_mover_categoria_de_grupo_preserva_id_e_e_idempotente(db_session):
    # Simula o cenário real da migração f57babb7aacc: uma categoria com histórico (id já usado
    # por movimento_linha.categoria_id) que precisa de mudar de grupo sem ser recriada.
    from ava.repositories import categoria_repo

    grupo_origem = await categoria_repo.criar_grupo(db_session, nome="Grupo Origem Teste")
    grupo_destino = await categoria_repo.criar_grupo(db_session, nome="Grupo Destino Teste")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo_origem.id, nome="Categoria Móvel", tipo="despesa", natureza="variavel"
    )
    await db_session.commit()
    id_original = categoria.id
    id_grupo_destino = grupo_destino.id  # capturado antes do expire_all() abaixo

    conn = await db_session.connection()
    moveu = await conn.run_sync(
        lambda c: mover_categoria_de_grupo(
            c,
            categoria_nome="Categoria Móvel",
            grupo_origem_nome="Grupo Origem Teste",
            grupo_destino_nome="Grupo Destino Teste",
        )
    )
    await db_session.commit()
    assert moveu is True

    # A sessão ORM ainda tem `categoria` em cache com o grupo_id antigo (expire_on_commit=False
    # neste conftest — ver tests/conftest.py) — mover_categoria_de_grupo mexe na BD através de
    # uma Connection Core, por fora do identity map da sessão. Sem isto, obter_por_id devolveria
    # o objeto em cache, não o valor real na BD.
    db_session.expire_all()
    movida = await categoria_repo.obter_por_id(db_session, id_original)
    assert movida is not None
    assert movida.id == id_original  # preserva o id — histórico de categoria_id continua válido
    assert movida.grupo_id == id_grupo_destino

    # Correr outra vez (ex.: migração reaplicada) não duplica nem rebenta.
    conn = await db_session.connection()
    moveu_outra_vez = await conn.run_sync(
        lambda c: mover_categoria_de_grupo(
            c,
            categoria_nome="Categoria Móvel",
            grupo_origem_nome="Grupo Origem Teste",
            grupo_destino_nome="Grupo Destino Teste",
        )
    )
    await db_session.commit()
    assert moveu_outra_vez is False

    total = (
        await db_session.execute(text("SELECT count(*) FROM categoria WHERE nome = 'Categoria Móvel'"))
    ).scalar_one()
    assert total == 1
