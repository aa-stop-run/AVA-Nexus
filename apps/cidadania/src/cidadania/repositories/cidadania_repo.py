import uuid
from datetime import date
from decimal import Decimal
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from cidadania.models.documento_identificacao import DocumentoIdentificacao
from cidadania.models.obrigacao_fiscal import ObrigacaoFiscal


async def obter_documentos(
    session: AsyncSession,
    titular: str | None = None
) -> list[DocumentoIdentificacao]:
    stmt = select(DocumentoIdentificacao).where(DocumentoIdentificacao.ativo.is_(True))
    if titular:
        stmt = stmt.where(DocumentoIdentificacao.titular_nome.ilike(f"%{titular}%"))
    stmt = stmt.order_by(DocumentoIdentificacao.titular_nome.asc(), DocumentoIdentificacao.data_validade.asc().nulls_last())
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def criar_documento(
    session: AsyncSession,
    *,
    titular_nome: str,
    tipo: str,
    numero: str,
    data_emissao: date | None = None,
    data_validade: date | None = None,
    entidade_emissora: str = "República Portuguesa",
    paperless_document_id: int | None = None,
    notas: str | None = None,
) -> DocumentoIdentificacao:
    doc = DocumentoIdentificacao(
        titular_nome=titular_nome,
        tipo=tipo,
        numero=numero,
        data_emissao=data_emissao,
        data_validade=data_validade,
        entidade_emissora=entidade_emissora,
        paperless_document_id=paperless_document_id,
        notas=notas,
        ativo=True,
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return doc


async def obter_obrigacoes_fiscais(
    session: AsyncSession,
    ano: int = 2026
) -> list[ObrigacaoFiscal]:
    stmt = (
        select(ObrigacaoFiscal)
        .where(ObrigacaoFiscal.ano_fiscal == ano)
        .order_by(ObrigacaoFiscal.data_limite.asc())
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def criar_obrigacao_fiscal(
    session: AsyncSession,
    *,
    nome: str,
    categoria: str,
    ano_fiscal: int = 2026,
    data_limite: date,
    valor_estimado: Decimal | None = None,
    pago: bool = False,
    detalhes: str | None = None,
) -> ObrigacaoFiscal:
    ob = ObrigacaoFiscal(
        nome=nome,
        categoria=categoria,
        ano_fiscal=ano_fiscal,
        data_limite=data_limite,
        valor_estimado=valor_estimado,
        pago=pago,
        detalhes=detalhes,
    )
    session.add(ob)
    await session.commit()
    await session.refresh(ob)
    return ob


async def garantir_dados_iniciais(session: AsyncSession) -> None:
    """Popula documentos conhecidos da família e o calendário fiscal padrão português."""
    res_doc = await session.execute(select(func.count(DocumentoIdentificacao.id)))
    if (res_doc.scalar() or 0) == 0:
        # aa-stop-run
        await criar_documento(
            session,
            titular_nome="aa-stop-run",
            tipo="nif",
            numero="219606595",
            notas="Número de Identificação Fiscal — Autoridade Tributária e Aduaneira.",
        )
        await criar_documento(
            session,
            titular_nome="aa-stop-run",
            tipo="cartao_cidadao",
            numero="13849204 4 ZY2",
            data_validade=date(2028, 5, 14),
            entidade_emissora="IRN, IP",
            notas="Cartão de Cidadão Nacional.",
        )
        await criar_documento(
            session,
            titular_nome="aa-stop-run",
            tipo="carta_conducao",
            numero="P-4820194 8",
            data_validade=date(2035, 11, 20),
            entidade_emissora="IMT, IP",
            notas="Categorias B, B1 (Ligeiros).",
        )

        # Member
        await criar_documento(
            session,
            titular_nome="Member",
            tipo="nif",
            numero="225075830",
            notas="NIF Demo Member.",
        )
        await criar_documento(
            session,
            titular_nome="Member",
            tipo="niss",
            numero="11324949345",
            entidade_emissora="Segurança Social",
            notas="Beneficiária Segurança Social.",
        )
        await criar_documento(
            session,
            titular_nome="Member",
            tipo="cartao_cidadao",
            numero="14201958 1 ZZ9",
            data_validade=date(2027, 9, 28),
            entidade_emissora="IRN, IP",
        )

        # Junior
        await criar_documento(
            session,
            titular_nome="Junior",
            tipo="nif",
            numero="279828373",
            notas="NIF Junior (Exemplo).",
        )
        await criar_documento(
            session,
            titular_nome="Junior",
            tipo="cartao_cidadao",
            numero="30363390 8 ZX1",
            data_validade=date(2029, 3, 10),
            entidade_emissora="IRN, IP",
            notas="Cartão de Cidadão Pediátrico.",
        )

    # Calendário Fiscal
    res_ob = await session.execute(select(func.count(ObrigacaoFiscal.id)))
    if (res_ob.scalar() or 0) == 0:
        await criar_obrigacao_fiscal(
            session,
            nome="Validação de Faturas no e-fatura",
            categoria="efatura",
            ano_fiscal=2026,
            data_limite=date(2027, 2, 25),
            detalhes="Prazo limite para associar e validar faturas pendentes de Saúde, Educação, Restauração e Imóveis no Portal das Finanças.",
        )
        await criar_obrigacao_fiscal(
            session,
            nome="Entrega da Declaração de IRS (Modelo 3)",
            categoria="irs",
            ano_fiscal=2026,
            data_limite=date(2027, 6, 30),
            detalhes="Período legal de entrega da declaração de rendimentos do agregado familiar relativa ao ano fiscal.",
        )
        await criar_obrigacao_fiscal(
            session,
            nome="Pagamento de IMI — 1ª Prestação (ou Pagamento Único)",
            categoria="imi",
            ano_fiscal=2026,
            data_limite=date(2027, 5, 31),
            valor_estimado=Decimal("180.00"),
            detalhes="Imposto Municipal sobre Imóveis da habitação de Baguim do Monte.",
        )
        await criar_obrigacao_fiscal(
            session,
            nome="Pagamento de IMI — 2ª Prestação",
            categoria="imi",
            ano_fiscal=2026,
            data_limite=date(2027, 11, 30),
            valor_estimado=Decimal("180.00"),
            detalhes="Segunda prestação do IMI anual.",
        )
