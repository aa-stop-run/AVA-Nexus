from datetime import date, timedelta
from decimal import Decimal


def soma_linhas_igual_total(
    linhas: list[Decimal], total: Decimal, *, tolerancia: Decimal = Decimal("0.01")
) -> bool:
    soma = sum(linhas, Decimal("0"))
    return abs(soma - total) <= tolerancia


def nif_valido(nif: str) -> bool:
    nif = nif.strip()
    if len(nif) != 9 or not nif.isdigit():
        return False

    digitos = [int(c) for c in nif]
    soma = sum(digito * peso for digito, peso in zip(digitos[:8], range(9, 1, -1)))
    resto = soma % 11
    digito_controlo = 0 if resto < 2 else 11 - resto
    return digito_controlo == digitos[8]


def iban_valido(iban: str) -> bool:
    iban = iban.replace(" ", "").upper()
    if len(iban) < 15:
        return False

    rearranjado = iban[4:] + iban[:4]
    try:
        convertido = "".join(str(int(caractere, 36)) for caractere in rearranjado)
    except ValueError:
        return False
    return int(convertido) % 97 == 1


def data_plausivel(
    data: date, referencia: date, *, margem_passado_dias: int = 730, margem_futura_dias: int = 7
) -> bool:
    mais_antiga_aceite = referencia - timedelta(days=margem_passado_dias)
    mais_recente_aceite = referencia + timedelta(days=margem_futura_dias)
    return mais_antiga_aceite <= data <= mais_recente_aceite


def valor_dentro_magnitude_historica(
    valor: Decimal,
    historico: list[Decimal],
    *,
    multiplicador_max: Decimal = Decimal("3"),
    verificar_minimo: bool = True,
) -> bool:
    # verificar_minimo=True (default) mantém a banda simétrica original, correta para faturas de
    # fornecedor: uma fatura de 1€ contra uma média histórica de 60€ É uma anomalia genuína (o
    # cenário que esta função foi desenhada para apanhar). Para despesas/rendimentos avulsos por
    # registados à mão, a variação dia-a-dia do valor é normal, não um sinal de erro — só o teto
    # (um engano que multiplique "20,00" por 100) corresponde à ameaça real nesse contexto, por
    # isso ava.financas.registo_rapido passa verificar_minimo=False para desligar o piso.
    if not historico:
        return True  # primeira fatura deste fornecedor — nada para comparar ainda

    media = sum(historico, Decimal("0")) / len(historico)
    if media == 0:
        return True

    limite_superior = media * multiplicador_max
    if not verificar_minimo:
        return valor <= limite_superior

    limite_inferior = media / multiplicador_max
    return limite_inferior <= valor <= limite_superior
