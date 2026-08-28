"""A que espécie de fluxo pertence um movimento, e que naturezas uma categoria pode ter.

Dois eixos independentes (spec 2026-08-13, §2):

- **Eixo 1**, aqui: *que espécie de fluxo é este?* — sai dos tipos das contas envolvidas e não
  exige marcação nenhuma, porque o dado já existe.
- **Eixo 2**, na coluna `categoria.natureza`: *isto é fiável / é compromisso?* — vem de uma marca
  feita uma vez pelo utilizador.

Separá-los é o que faz o desenho funcionar: o tipo de conta sabe distinguir consumo de movimento
patrimonial, a categoria sabe distinguir salário de prémio, e nenhum dos dois sabe o do outro.

Módulo puro de propósito — sem sessão, sem I/O — pela mesma razão de `saldos.py`: a classificação
fica testável sem Postgres.
"""

from ava.financas.saldos import TIPOS_PASSIVO

# Valores válidos de `categoria.natureza`, por `categoria.tipo`. A base de dados garante o mesmo
# em ck_categoria_natureza (ver ava.models.categoria); isto existe para a validação dar um erro
# amigável antes de lá chegar.
NATUREZAS_RECEITA: tuple[str, ...] = ("recorrente", "extraordinario")
NATUREZAS_DESPESA: tuple[str, ...] = ("fixa", "variavel", "poupanca")

# Classes de conta. É sobre estas que as regras de `classificar_fluxo` decidem — não sobre o
# `conta.tipo` cru: "a_ordem", "cartao_refeicao" e "investimento" comportam-se todos da mesma
# maneira num fluxo, e enumerá-los um a um convidava a esquecer o próximo que aparecesse.
#
# Públicas porque quem agrega precisa delas para o SINAL: sair de uma conta de poupança é
# despoupar, e sair de um passivo é pedir emprestado. Sem isto, `margem_repo` reimplementava a
# mesma divisão à mão e passava a haver duas noções de "conta passiva" a divergir com o tempo —
# exatamente a dívida que TIPOS_PASSIVO já teve de pagar uma vez.
CLASSE_CORRENTE = "corrente"
CLASSE_POUPANCA = "poupanca"
CLASSE_PASSIVO = "passivo"
CLASSE_AUSENTE = "ausente"


def naturezas_de(tipo: str) -> tuple[str, ...]:
    """As naturezas que uma categoria deste `tipo` pode ter. Vazio se o tipo for desconhecido."""
    if tipo == "receita":
        return NATUREZAS_RECEITA
    if tipo == "despesa":
        return NATUREZAS_DESPESA
    return ()


def natureza_valida(*, tipo: str, natureza: str) -> bool:
    """Se esta natureza pode ser atribuída a uma categoria deste tipo."""
    return natureza in naturezas_de(tipo)


def classe_de_conta(tipo_conta: str | None) -> str:
    """A classe de fluxo a que este `conta.tipo` pertence.

    `None` (transferência sem conta de destino) é uma classe própria e não "corrente": significa
    que o dinheiro saiu do sistema, não que foi para uma conta à ordem.
    """
    if tipo_conta is None:
        return CLASSE_AUSENTE
    if tipo_conta in TIPOS_PASSIVO:
        return CLASSE_PASSIVO
    if tipo_conta == "poupanca":
        return CLASSE_POUPANCA
    return CLASSE_CORRENTE


def classificar_fluxo(
    *,
    tipo_movimento: str,
    tipo_conta_origem: str | None,
    tipo_conta_destino: str | None,
) -> str:
    """A que espécie de fluxo este movimento pertence.

    Devolve `"rendimento"`, `"despesa"`, `"poupanca"`, `"divida"` ou `"interno"`.

    Para transferências o fluxo manda e a categoria não é consultada; para `entrada` e `saida` é
    ao contrário. Uma transferência para um empréstimo é serviço da dívida mesmo que esteja
    categorizada como "Habitação / Renda".

    As regras são avaliadas por ORDEM e a primeira que corresponder decide. A ordem é a
    especificação, não um detalhe (spec §4):

    - A verificação de "mesma classe" vem antes de tudo o resto. Sem ela,
      `cartao_credito -> cartao_credito` era contado como serviço da dívida, quando é apenas
      dívida a mudar de sítio — existem 3 movimentos assim em produção, 59,17 €. O mesmo protege
      `poupanca -> poupanca`, que de outro modo inflava a poupança do mês sem nada ter sido
      poupado.
    - A dívida vem antes da poupança. Uma transferência `poupanca -> emprestimo` é as duas coisas
      ao mesmo tempo, e só um valor pode ser devolvido: a amortização é o que a margem tem de
      cobrir; de onde saiu o dinheiro é uma pergunta separada.

    O SINAL não é devolvido aqui — quem agrega é que sabe a direção, por comparação entre a
    classe de origem e a de destino. Ver `margem_repo.margem_estrutural`.
    """
    if tipo_movimento == "entrada":
        return "rendimento"
    if tipo_movimento == "saida":
        return "despesa"

    origem = classe_de_conta(tipo_conta_origem)
    destino = classe_de_conta(tipo_conta_destino)

    if destino == CLASSE_AUSENTE:
        return "despesa"
    if origem == destino:
        return "interno"
    if CLASSE_PASSIVO in (origem, destino):
        return "divida"
    if CLASSE_POUPANCA in (origem, destino):
        return "poupanca"
    return "interno"
