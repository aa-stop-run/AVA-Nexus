"""Pipeline de ingestão: faturas, extratos bancários e recibos de vencimento.

Este pacote substitui o antigo módulo único `pipeline.py` (677 linhas, quatro domínios de
ingestão e três pares de funções quase duplicadas — ver o review final da branch). A divisão:

- `_comum.py`: helpers genuinamente partilhados por fatura e extrato (FalhaValidacao,
  atribuição por tags do Paperless, alerta de revisão manual).
- `faturas.py`: ingestão de faturas de fornecedores.
- `extratos.py`: ingestão de extratos bancários.
- `aprovacao.py`: aprovação manual, que faz dispatch entre faturas e extratos.

Este `__init__` reexporta todos os nomes que já eram públicos em `pipeline.py` para que os
consumidores existentes (`ava.alerts.scheduler`, `ava.api.dashboard`, `ava.api.fila`,
`tests/test_ingestion/test_pipeline.py`) continuem a funcionar sem alterar as suas
declarações de import.
"""

from ava.ingestion.pipeline._comum import FalhaValidacao, _alertar_revisao_manual, _extrair_atribuicao_por_tags
from ava.ingestion.pipeline.aprovacao import aprovar_documento_manualmente
from ava.ingestion.pipeline.extratos import (
    TAG_EXTRATO_POR_ESTRUTURAR,
    _aprovar_extrato_manualmente,
    _persistir_extrato,
    _processar_extrato_extraido,
    finalizar_extrato_nivel1,
    processar_extratos_pendentes,
    validar_extrato,
)
from ava.ingestion.pipeline.faturas import (
    PARSERS_NIVEL0,
    TAG_POR_ESTRUTURAR,
    _inferir_tipo_fornecedor,
    _persistir_fatura,
    _processar_fatura_extraida,
    finalizar_documento_nivel1,
    processar_documentos_pendentes,
    validar_fatura,
)
from ava.ingestion.pipeline.recibos import (
    processar_recibos_pendentes,
    finalizar_recibo_vencimento,
    TAG_RECIBO_POR_ESTRUTURAR
)

__all__ = [
    "FalhaValidacao",
    "PARSERS_NIVEL0",
    "TAG_EXTRATO_POR_ESTRUTURAR",
    "TAG_POR_ESTRUTURAR",
    "_alertar_revisao_manual",
    "_aprovar_extrato_manualmente",
    "_extrair_atribuicao_por_tags",
    "_inferir_tipo_fornecedor",
    "_persistir_extrato",
    "_persistir_fatura",
    "_processar_extrato_extraido",
    "_processar_fatura_extraida",
    "aprovar_documento_manualmente",
    "finalizar_documento_nivel1",
    "finalizar_extrato_nivel1",
    "finalizar_recibo_vencimento",
    "processar_documentos_pendentes",
    "processar_extratos_pendentes",
    "processar_recibos_pendentes",
    "validar_extrato",
    "validar_fatura",
    "TAG_RECIBO_POR_ESTRUTURAR",
]
