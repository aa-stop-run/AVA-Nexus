import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from ava.extraction.schema_extrato import ExtratoBancario, MovimentoExtraido, SaldoFinal

logger = logging.getLogger("ava.extraction")

_BANCO = re.compile(r"Banco:\s*(.+)")
_CONTA = re.compile(r"Conta:\s*(.+)")
_SALDO = re.compile(r"Saldo em (\d{2}/\d{2}/\d{4}):\s*([\d.,\-]+)\s*EUR")
# Padrão pendente da Tarefa 10 (ficheiros reais do utilizador ainda não disponíveis): isolado
# aqui numa constante para ser fácil de ajustar depois de vermos o formato real do saldo inicial
# (ex. pode ser preciso adicionar uma variante "Saldo anterior:").
_SALDO_INICIAL = re.compile(r"Saldo inicial:\s*([\d.,\-]+)\s*EUR")
_MOVIMENTO = re.compile(r"(\d{2}/\d{2}/\d{4})\s*\|\s*([\d.,\-]+)\s*\|\s*(.+)")


def _valor_pt_para_decimal(valor_texto: str) -> Decimal:
    return Decimal(valor_texto.replace(".", "").replace(",", "."))


def _data_pt_para_date(data_texto: str) -> date:
    return datetime.strptime(data_texto, "%d/%m/%Y").date()


def _inferir_tipo_conta(texto_conta: str) -> str:
    texto_lower = texto_conta.lower()
    if "poupança" in texto_lower or "poupanca" in texto_lower:
        return "poupanca"
    if "crédito" in texto_lower or "credito" in texto_lower:
        return "divida"  # cartão de CRÉDITO representa uma dívida, não um ativo
    if (
        "refeição" in texto_lower
        or "refeicao" in texto_lower
        or "alimentação" in texto_lower
        or "alimentacao" in texto_lower
    ):
        return "cartao_refeicao"
    # Um "cartão" genérico (sem "crédito" nem "refeição/alimentação") é ambíguo — pode ser tanto
    # dívida quanto ativo, e Conta.tipo não tem um valor "unknown" para sinalizar incerteza (nem
    # existe ainda UI para corrigir o tipo depois de criada a conta). Segue o mesmo princípio de
    # "nunca adivinha" já aplicado em reconciliacao.conciliar_uma_linha e
    # _resolver_conta_mencionada: cai no mesmo fallback do caso sem palavra-chave nenhuma, em vez
    # de assumir cartao_refeicao por omissão como acontecia antes.
    return "a_ordem"


def _construir_movimento(data_texto: str, valor_texto: str, descricao: str) -> MovimentoExtraido | None:
    # Uma linha de movimento garbled (data/valor com a forma certa mas não convertível) não
    # deve derrubar o extrato inteiro — só esta linha é descartada (ver test_parser_banco_generico.py).
    try:
        return MovimentoExtraido(
            data=_data_pt_para_date(data_texto),
            valor=_valor_pt_para_decimal(valor_texto),
            descricao=descricao.strip(),
        )
    except (InvalidOperation, ValueError):
        # A-P6: a linha é descartada (best-effort, ver nota acima) mas nunca em silêncio —
        # regista-se a linha bruta para o operador poder investigar o extrato original.
        logger.warning(
            "Linha de movimento não reconhecida no extrato bancário (descartada): "
            "%r | %r | %r",
            data_texto,
            valor_texto,
            descricao,
        )
        return None


def parse_banco_generico(texto_ocr: str) -> ExtratoBancario | None:
    banco_match = _BANCO.search(texto_ocr)
    conta_match = _CONTA.search(texto_ocr)
    saldo_match = _SALDO.search(texto_ocr)
    if banco_match is None or conta_match is None or saldo_match is None:
        return None

    # O saldo é uma secção obrigatória do extrato: se a data/valor não forem convertíveis,
    # o documento inteiro é tratado como não reconhecido (mesma convenção de edp.py/agua.py).
    try:
        saldo_final = SaldoFinal(
            data=_data_pt_para_date(saldo_match.group(1)),
            valor=_valor_pt_para_decimal(saldo_match.group(2)),
        )
    except (InvalidOperation, ValueError):
        return None

    # Saldo inicial é opcional a este nível (secção pode não existir no extrato real, ver nota
    # na constante acima): sem ele, o checksum de validar_extrato (§7) não é calculável, e esse
    # extrato vai para revisão manual em vez de se confiar num parse não verificável (A-P3) — mas
    # isso não deve derrubar o resto do parse aqui, tal como um movimento individual garbled não
    # derruba o extrato inteiro.
    saldo_inicial: Decimal | None = None
    saldo_inicial_match = _SALDO_INICIAL.search(texto_ocr)
    if saldo_inicial_match is not None:
        try:
            saldo_inicial = _valor_pt_para_decimal(saldo_inicial_match.group(1))
        except InvalidOperation:
            saldo_inicial = None

    movimentos_construidos = [
        _construir_movimento(data_texto, valor_texto, descricao)
        for data_texto, valor_texto, descricao in _MOVIMENTO.findall(texto_ocr)
    ]
    movimentos = [movimento for movimento in movimentos_construidos if movimento is not None]
    linhas_nao_reconhecidas = len(movimentos_construidos) - len(movimentos)

    return ExtratoBancario(
        instituicao=banco_match.group(1).strip(),
        tipo_conta=_inferir_tipo_conta(conta_match.group(1)),
        nome_conta=conta_match.group(1).strip(),
        saldo_final=saldo_final,
        saldo_inicial=saldo_inicial,
        movimentos=movimentos,
        linhas_nao_reconhecidas=linhas_nao_reconhecidas,
    )
