"""Testes que fixam regras de desenho, não comportamento.

Uma âncora é sempre uma declaração externa, nunca um cálculo sobre movimentos (spec 2026-08-08,
§7.3; estendida em 2026-08-09 §2.1 com uma terceira fonte, o ficheiro que o banco exporta). Esta
regra é fácil de violar por distração — foi violada duas vezes antes de existir — e uma violação
nova não faz falhar nenhum teste de comportamento, porque o número que aparece no ecrã continua
plausível. Daí este teste. A lista de ficheiros autorizados é a lista atual das fontes declaradas
— cresce quando uma spec futura adicionar uma fonte nova, o princípio em si não muda.
"""

import pathlib
import re

FICHEIROS_AUTORIZADOS = {
    "src/ava/ingestion/pipeline/extratos.py",   # o banco declara (extrato)
    "src/ava/api/configuracoes.py",             # o utilizador declara (manual)
    "src/ava/repositories/saldo_historico_repo.py",  # a própria implementação
    "src/ava/ingestion/importacao_ficheiro.py",  # o ficheiro do banco declara (spec 2026-08-09 §2.1)
}

# Criar uma âncora: chamar registar_saldo, ou construir um SaldoHistorico diretamente. Estes dois
# padrões são precisos — não há uso legítimo deles fora dos ficheiros autorizados.
#
# A MUTAÇÃO de uma âncora já gravada (`saldo_recente.valor -= x`, o que dashboard.py fazia) não é
# coberta aqui, e de propósito: o nome da variável é livre, e um regex como `\w+\.valor\s*=`
# apanharia dezenas de atribuições legítimas noutros modelos. Um teste que dá falsa confiança é
# pior do que nenhum. A mutação é coberta por comportamento, em
# test_registo_post_nao_altera_a_ancora (Task 1) — que verifica o valor da âncora depois de
# registar uma despesa, que é o que interessa mesmo.
_ESCRITAS = re.compile(r"registar_saldo\(|(?<!class )SaldoHistorico\(")


def test_so_fontes_declaradas_escrevem_uma_ancora():
    raiz = pathlib.Path(__file__).resolve().parents[1]
    infratores = []
    for ficheiro in (raiz / "src").rglob("*.py"):
        relativo = ficheiro.relative_to(raiz).as_posix()
        if relativo in FICHEIROS_AUTORIZADOS:
            continue
        for numero, linha in enumerate(ficheiro.read_text(encoding="utf-8").splitlines(), 1):
            if _ESCRITAS.search(linha):
                infratores.append(f"{relativo}:{numero}: {linha.strip()}")

    assert not infratores, (
        "Uma âncora é sempre uma declaração externa, nunca um cálculo sobre movimentos (spec "
        "§7.3). Se este ficheiro precisa mesmo de escrever uma, a spec tem de mudar primeiro:\n"
        + "\n".join(infratores)
    )
