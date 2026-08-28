import pytest
from saude.models.medicamento import Medicamento, MedicamentoTomaHorario, MedicamentoRegistoToma
from saude.models.prescricao import PrescricaoMedica


def test_instanciacao_medicamento():
    med = Medicamento(
        titular="aa-stop-run",
        nome="Sertralina",
        principio_ativo="Cloridrato de Sertralina",
        dosagem="50 mg",
        forma_farmaceutica="pill",
        stock_atual=30,
        stock_minimo_alerta=7,
        unidade_medida="pills",
        instrucoes_toma="Tomar de manhã com água"
    )
    assert med.titular == "aa-stop-run"
    assert med.nome == "Sertralina"
    assert med.dosagem == "50 mg"
    assert med.stock_atual == 30
    assert med.stock_minimo_alerta == 7
    assert med.ativo is True


def test_instanciacao_horario_e_registo():
    horario = MedicamentoTomaHorario(hora="08:30", quantidade_dose=1.0, dias_semana="todos")
    assert horario.hora == "08:30"
    assert horario.quantidade_dose == 1.0
    assert horario.dias_semana == "todos"


def test_instanciacao_prescricao():
    presc = PrescricaoMedica(
        titular="aa-stop-run",
        numero_receita_sns="123456789",
        codigo_acesso="1234",
        codigo_opcao="5678",
        medico_prescritor="Dra. Mariana Silva",
        estado="ativa"
    )
    assert presc.titular == "aa-stop-run"
    assert presc.numero_receita_sns == "123456789"
    assert presc.codigo_acesso == "1234"
    assert presc.codigo_opcao == "5678"
