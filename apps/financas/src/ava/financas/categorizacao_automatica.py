"""Correspondência de descrições de linhas de extrato para categorização automática.

Uma transação recorrente do mesmo comerciante (ex.: compras num supermercado, um débito
direto de subscrição) aparece tipicamente com o mesmo texto de descrição em cada mês, exceto
por um número de referência que varia por transação (ver a mesma observação em
ava.extraction.parsers.banco_bpi). `padrao_de_descricao` normaliza esse texto substituindo
sequências de dígitos por um marcador estável, para que o histórico de categorização já feito
pelo utilizador (ver ava.repositories.movimento_repo.obter_categoria_mais_recente_por_padrao)
possa reconhecer a mesma "espécie" de transação sem depender do número de referência exato.
"""

import re


def padrao_de_descricao(descricao: str) -> str:
    sem_digitos = re.sub(r"\d+", "#", descricao.upper())
    return re.sub(r"\s+", " ", sem_digitos).strip()
