"""Saldo de uma conta derivado dos movimentos, a partir da última âncora declarada.

Uma **âncora** é o que uma fonte externa declarou: o banco num extrato, ou o utilizador a
registá-lo à mão. Nunca é um número que o sistema calcule — se fosse, deixava de poder desmentir
os movimentos, e a reconciliação passava a comparar um número consigo próprio (spec 2026-08-08,
§7).

Módulo puro de propósito — sem sessão, sem I/O — pelo mesmo motivo de `valorizacao.py`: a
aritmética fica testável sem Postgres.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

# Contas onde o saldo representa o que se DEVE, e não o que se tem. Dinheiro que entra reduz o
# saldo (amortizar reduz a dívida); dinheiro que sai aumenta-o (gastar no cartão aumenta a
# dívida). É a mesma divisão que `/patrimonio` já faz para separar `total_dividas` de
# `total_ativos`, e passa a viver aqui por ser a única fonte de verdade.
TIPOS_PASSIVO: tuple[str, ...] = ("divida", "emprestimo", "cartao_credito")

# Tolerância de datas ao casar uma linha de extrato com um movimento registado à mão. Mede o
# atraso entre gastar e o banco lançar, NÃO o intervalo entre extratos: os extratos são mensais,
# mas uma janela de trinta dias casaria a mensalidade do ginásio de setembro com a de outubro.
# Simétrica, porque o utilizador também pode datar uma despesa pelo talão e ficar aquém da data
# real.
JANELA_CASAMENTO_DIAS = 7

# A partir de quando é que as divergências são listadas. Anteriores a esta data não aparecem —
# decisão explícita de não rever o passado (spec §11). Baixar esta data faz aparecer o histórico.
RECONCILIACAO_DESDE = date(2026, 8, 8)


def sinal_de(tipo: str) -> int:
    """+1 se o saldo cresce com entradas, −1 se cresce com saídas.

    Um tipo desconhecido conta como ativo. É a omissão menos perigosa: um falso "ativo" aparece
    inflacionado no `/patrimonio` e vê-se; um falso "passivo" subtrairia em silêncio.
    """
    return -1 if tipo in TIPOS_PASSIVO else 1


def parse_valor_pt(texto: str) -> Decimal:
    """Interpreta um valor monetário escrito por um humano num formulário, em português.

    O separador decimal é sempre a vírgula (todos os formulários usam o placeholder "0,00", e
    `format_pt` mostra os valores assim em toda a app). Só quando há vírgula é que um ponto é
    tratado como separador de milhares e removido antes de trocar a vírgula por ponto — sem esta
    condição, "4.281,55" (o que `format_pt` já escreve) rebentava com `InvalidOperation` ao
    tentar interpretar dois separadores decimais. Sem vírgula, um eventual ponto fica intocado
    (é o próprio separador decimal, ex. "4281.55" digitado à americana).

    Mesma convenção incondicional que `extraction/parsers/edp.py` e `banco_generico.py` já usam
    para o texto de um extrato — aqui é condicional porque a entrada é escrita por uma pessoa,
    não gerada por um banco, e uma pessoa também pode escrever sem separador de milhares.

    Levanta `InvalidOperation` em texto que não é um número, tal como `Decimal(...)` diretamente
    — quem chama já apanha essa exceção. O mesmo acontece se houver um ponto DEPOIS da vírgula
    (ex. "1,234.56"): isso é formato americano, não português, e não há como adivinhar se quem
    escreveu quis dizer 1234.56 ou outra coisa — sem esta recusa, o ponto sobrevivia ao
    `.replace(".", "")` (que só tira pontos ANTES da vírgula) e `Decimal("1.23456")` era gravado
    silenciosamente como âncora, ~1000× menor do que o valor real (achado 1 da re-revisão).
    """
    texto = texto.strip()
    if "," in texto:
        if "." in texto[texto.index(","):]:
            raise InvalidOperation(f"formato de valor não reconhecido: {texto!r}")
        texto = texto.replace(".", "").replace(",", ".")
    return Decimal(texto)


def derivar(ancora: Decimal, entradas: Decimal, saidas: Decimal, *, tipo: str) -> Decimal:
    """Saldo = âncora + sinal × (entradas − saídas).

    `entradas` e `saidas` são ambas positivas — o sinal vem do tipo da conta, não do chamador.
    Quem passa uma saída como número negativo obtém silenciosamente o dobro do efeito, por isso
    a convenção fica escrita aqui e é a mesma em `movimento_repo.fluxo_entre`.
    """
    return ancora + sinal_de(tipo) * (entradas - saidas)
