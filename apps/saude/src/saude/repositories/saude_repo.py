import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from saude.models.titular import Titular
from saude.models.perfil import PerfilSaude
from saude.models.consulta import ConsultaMedica
from saude.models.exame import ExameMedico
from saude.models.medicamento import MedicamentoAtivo
from saude.models.vacina import VacinaRegisto
from saude.models.biomarcador import BiomarcadorLeitura
from saude.models.documento import DocumentoSaude


async def garantir_titulares_e_perfis(session: AsyncSession) -> list[PerfilSaude]:
    """Garante a existência dos membros familiares principais (aa-stop-run, Member, Junior)."""
    membros_iniciais = [
        ("aa-stop-run", "proprio"),
        ("Member", "conjuge"),
        ("Junior", "filho"),
    ]

    for nome, tipo in membros_iniciais:
        stmt = select(Titular).where(Titular.nome == nome)
        res = await session.execute(stmt)
        titular = res.scalar_one_or_none()
        if not titular:
            titular = Titular(nome=nome, tipo=tipo)
            session.add(titular)
            await session.flush()

        stmt_p = select(PerfilSaude).where(PerfilSaude.titular_id == titular.id)
        res_p = await session.execute(stmt_p)
        perfil = res_p.scalar_one_or_none()
        if not perfil:
            perfil = PerfilSaude(titular_id=titular.id)
            session.add(perfil)
            await session.flush()

    await session.commit()
    return await listar_perfis(session)


async def listar_perfis(session: AsyncSession) -> list[PerfilSaude]:
    stmt = (
        select(PerfilSaude)
        .options(
            selectinload(PerfilSaude.titular),
            selectinload(PerfilSaude.consultas),
            selectinload(PerfilSaude.exames),
            selectinload(PerfilSaude.medicamentos),
            selectinload(PerfilSaude.vacinas),
            selectinload(PerfilSaude.biomarcadores),
            selectinload(PerfilSaude.documentos),
        )
        .join(Titular)
        .order_by(Titular.nome.asc())
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def obter_perfil_por_id(session: AsyncSession, perfil_id: uuid.UUID) -> PerfilSaude | None:
    stmt = (
        select(PerfilSaude)
        .options(
            selectinload(PerfilSaude.titular),
            selectinload(PerfilSaude.consultas),
            selectinload(PerfilSaude.exames),
            selectinload(PerfilSaude.medicamentos),
            selectinload(PerfilSaude.vacinas),
            selectinload(PerfilSaude.biomarcadores),
            selectinload(PerfilSaude.documentos),
        )
        .where(PerfilSaude.id == perfil_id)
        .execution_options(populate_existing=True)
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def obter_perfil_por_nome_titular(session: AsyncSession, nome_parcial: str) -> PerfilSaude | None:
    stmt = (
        select(PerfilSaude)
        .options(
            selectinload(PerfilSaude.titular),
            selectinload(PerfilSaude.consultas),
            selectinload(PerfilSaude.documentos),
        )
        .join(Titular)
        .where(Titular.nome.ilike(f"%{nome_parcial.strip()}%"))
    )
    res = await session.execute(stmt)
    return res.scalars().first()


async def atualizar_perfil(
    session: AsyncSession,
    perfil_id: uuid.UUID,
    *,
    numero_utente_sns: str | None = None,
    data_nascimento: date | None = None,
    grupo_sanguineo: str | None = None,
    alergias: str | None = None,
    condicoes_cronicas: str | None = None,
    notas: str | None = None,
) -> PerfilSaude | None:
    p = await obter_perfil_por_id(session, perfil_id)
    if p:
        p.numero_utente_sns = numero_utente_sns
        p.data_nascimento = data_nascimento
        p.grupo_sanguineo = grupo_sanguineo
        p.alergias = alergias
        p.condicoes_cronicas = condicoes_cronicas
        p.notas = notas
        await session.commit()
        await session.refresh(p)
    return p


async def listar_todas_consultas(session: AsyncSession, *, apenas_futuras: bool = False) -> list[ConsultaMedica]:
    stmt = (
        select(ConsultaMedica)
        .options(
            selectinload(ConsultaMedica.perfil).selectinload(PerfilSaude.titular),
        )
    )
    if apenas_futuras:
        agora = datetime.now(timezone.utc)
        stmt = stmt.where(ConsultaMedica.data_hora >= agora)
    stmt = stmt.order_by(ConsultaMedica.data_hora.asc())
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def registar_consulta(
    session: AsyncSession,
    *,
    perfil_id: uuid.UUID,
    data_hora: datetime,
    especialidade: str,
    medico: str | None = None,
    local_clinica: str | None = None,
    motivo: str | None = None,
    preparacao_instrucoes: str | None = None,
    diagnostico_notas: str | None = None,
    custo: Decimal = Decimal("0.00"),
    concluida: bool = False,
    codigo_confirmacao: str | None = None,
    documento_id: int | None = None,
) -> ConsultaMedica:
    c = ConsultaMedica(
        perfil_id=perfil_id,
        data_hora=data_hora,
        especialidade=especialidade,
        medico=medico,
        local_clinica=local_clinica,
        motivo=motivo,
        preparacao_instrucoes=preparacao_instrucoes,
        diagnostico_notas=diagnostico_notas,
        custo=custo,
        concluida=concluida,
        codigo_confirmacao=codigo_confirmacao,
        documento_id=documento_id,
    )
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return c


async def registar_exame(
    session: AsyncSession,
    *,
    perfil_id: uuid.UUID,
    data: date,
    tipo_exame: str,
    laboratorio_clinica: str | None = None,
    descricao: str | None = None,
    resultados_resumo: str | None = None,
    documento_id: int | None = None,
) -> ExameMedico:
    e = ExameMedico(
        perfil_id=perfil_id,
        data=data,
        tipo_exame=tipo_exame,
        laboratorio_clinica=laboratorio_clinica,
        descricao=descricao,
        resultados_resumo=resultados_resumo,
        documento_id=documento_id,
    )
    session.add(e)
    await session.commit()
    await session.refresh(e)
    return e


async def registar_medicamento(
    session: AsyncSession,
    *,
    perfil_id: uuid.UUID,
    nome: str,
    dosagem: str | None = None,
    posologia: str | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    ativo: bool = True,
    notas: str | None = None,
) -> MedicamentoAtivo:
    m = MedicamentoAtivo(
        perfil_id=perfil_id,
        nome=nome,
        dosagem=dosagem,
        posologia=posologia,
        data_inicio=data_inicio,
        data_fim=data_fim,
        ativo=ativo,
        notas=notas,
    )
    session.add(m)
    await session.commit()
    await session.refresh(m)
    return m


async def registar_vacina(
    session: AsyncSession,
    *,
    perfil_id: uuid.UUID,
    nome_vacina: str,
    data_toma: date,
    proxima_dose_data: date | None = None,
    lote_local: str | None = None,
) -> VacinaRegisto:
    v = VacinaRegisto(
        perfil_id=perfil_id,
        nome_vacina=nome_vacina,
        data_toma=data_toma,
        proxima_dose_data=proxima_dose_data,
        lote_local=lote_local,
    )
    session.add(v)
    await session.commit()
    await session.refresh(v)
    return v


async def registar_biomarcador(
    session: AsyncSession,
    *,
    perfil_id: uuid.UUID,
    data: date,
    parametro: str,
    valor: Decimal,
    unidade: str = "mg/dL",
    categoria: str = "Geral",
    valor_referencia_min: Decimal | None = None,
    valor_referencia_max: Decimal | None = None,
    laboratorio: str | None = None,
    notas: str | None = None,
    documento_id: int | None = None,
) -> BiomarcadorLeitura:
    # Evita duplicados exatos para o mesmo perfil, data e parâmetro
    stmt = (
        select(BiomarcadorLeitura)
        .where(
            BiomarcadorLeitura.perfil_id == perfil_id,
            BiomarcadorLeitura.data == data,
            BiomarcadorLeitura.parametro == parametro,
        )
    )
    res = await session.execute(stmt)
    existente = res.scalar_one_or_none()
    if existente:
        existente.valor = valor
        existente.unidade = unidade
        existente.categoria = categoria
        existente.valor_referencia_min = valor_referencia_min
        existente.valor_referencia_max = valor_referencia_max
        existente.laboratorio = laboratorio
        existente.notas = notas
        await session.commit()
        await session.refresh(existente)
        return existente

    b = BiomarcadorLeitura(
        perfil_id=perfil_id,
        data=data,
        parametro=parametro,
        valor=valor,
        unidade=unidade,
        categoria=categoria,
        valor_referencia_min=valor_referencia_min,
        valor_referencia_max=valor_referencia_max,
        laboratorio=laboratorio,
        notas=notas,
        documento_id=documento_id,
    )
    session.add(b)
    await session.commit()
    await session.refresh(b)
    return b


async def obter_historico_biomarcador(
    session: AsyncSession, perfil_id: uuid.UUID, parametro: str
) -> list[BiomarcadorLeitura]:
    stmt = (
        select(BiomarcadorLeitura)
        .where(
            BiomarcadorLeitura.perfil_id == perfil_id,
            BiomarcadorLeitura.parametro == parametro,
        )
        .order_by(BiomarcadorLeitura.data.asc())
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def gerar_insights_biomarcadores(session: AsyncSession, perfil_id: uuid.UUID) -> list[dict]:
    """Compara as últimas 2 leituras de cada biomarcador e gera insights de variação."""
    p = await obter_perfil_por_id(session, perfil_id)
    if not p or not p.biomarcadores:
        return []

    # Agrupa leituras por parâmetro
    parametros_map: dict[str, list[BiomarcadorLeitura]] = {}
    for b in p.biomarcadores:
        parametros_map.setdefault(b.parametro, []).append(b)

    insights = []
    for parametro, leituras in parametros_map.items():
        # Ordena por data descendente
        ordenadas = sorted(leituras, key=lambda x: x.data, reverse=True)
        recente = ordenadas[0]

        if len(ordenadas) >= 2:
            anterior = ordenadas[1]
            diff = recente.valor - anterior.valor
            percentual = ((diff / anterior.valor) * 100) if anterior.valor != 0 else 0
            sinal = "+" if diff > 0 else ""

            if abs(diff) < Decimal("0.5"):
                tendencia = "estavel"
                texto = f"{parametro}: Estável nos {recente.valor} {recente.unidade} (exame anterior: {anterior.valor} {anterior.unidade} em {anterior.data.strftime('%d/%m/%Y')})."
            elif diff > 0:
                tendencia = "subiu"
                texto = f"{parametro}: Subiu {sinal}{diff:.1f} {recente.unidade} ({sinal}{percentual:.1f}%) para {recente.valor} {recente.unidade} face a {anterior.data.strftime('%d/%m/%Y')}."
            else:
                tendencia = "desceu"
                texto = f"{parametro}: Desceu {diff:.1f} {recente.unidade} ({percentual:.1f}%) para {recente.valor} {recente.unidade} face a {anterior.data.strftime('%d/%m/%Y')}."

            insights.append({
                "parametro": parametro,
                "categoria": recente.categoria,
                "tendencia": tendencia,
                "recente_data": recente.data,
                "recente_valor": recente.valor,
                "anterior_data": anterior.data,
                "anterior_valor": anterior.valor,
                "diff": diff,
                "percentual": percentual,
                "unidade": recente.unidade,
                "estado": recente.estado,
                "texto": texto,
            })
        else:
            insights.append({
                "parametro": parametro,
                "categoria": recente.categoria,
                "tendencia": "primeiro_registo",
                "recente_data": recente.data,
                "recente_valor": recente.valor,
                "anterior_data": None,
                "anterior_valor": None,
                "diff": None,
                "percentual": None,
                "unidade": recente.unidade,
                "estado": recente.estado,
                "texto": f"{parametro}: {recente.valor} {recente.unidade} (Registo de {recente.data.strftime('%d/%m/%Y')} — {recente.estado.upper()}).",
            })

    return insights


async def registar_documento_saude(
    session: AsyncSession,
    *,
    perfil_id: uuid.UUID,
    nome_ficheiro: str,
    caminho_ficheiro: str,
    tamanho_bytes: int,
    data_documento: date,
    laboratorio_clinica: str | None = None,
    paperless_id: int | None = None,
) -> DocumentoSaude:
    doc = DocumentoSaude(
        perfil_id=perfil_id,
        nome_ficheiro=nome_ficheiro,
        caminho_ficheiro=caminho_ficheiro,
        tamanho_bytes=tamanho_bytes,
        data_documento=data_documento,
        laboratorio_clinica=laboratorio_clinica,
        paperless_id=paperless_id,
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return doc


async def obter_documento_por_id(session: AsyncSession, doc_id: int) -> DocumentoSaude | None:
    stmt = select(DocumentoSaude).where(DocumentoSaude.id == doc_id)
    res = await session.execute(stmt)
    return res.scalar_one_or_none()

