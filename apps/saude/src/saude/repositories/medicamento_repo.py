from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from saude.models.medicamento import Medicamento, MedicamentoTomaHorario, MedicamentoRegistoToma
from saude.models.prescricao import PrescricaoMedica


class MedicamentoRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def criar_medicamento(
        self,
        titular: str,
        nome: str,
        dosagem: str,
        stock_atual: int = 0,
        stock_minimo_alerta: int = 7,
        principio_ativo: str | None = None,
        forma_farmaceutica: str = "pill",
        unidade_medida: str = "unidades",
        instrucoes_toma: str | None = None,
        medico_prescritor: str | None = None,
        horarios: list[dict] | None = None,
    ) -> Medicamento:
        med = Medicamento(
            titular=titular,
            nome=nome,
            dosagem=dosagem,
            stock_atual=stock_atual,
            stock_minimo_alerta=stock_minimo_alerta,
            principio_ativo=principio_ativo,
            forma_farmaceutica=forma_farmaceutica,
            unidade_medida=unidade_medida,
            instrucoes_toma=instrucoes_toma,
            medico_prescritor=medico_prescritor,
            ativo=True,
        )
        self.session.add(med)
        await self.session.flush()

        if horarios:
            for h in horarios:
                horario_obj = MedicamentoTomaHorario(
                    medicamento_id=med.id,
                    hora=h.get("hora", "08:00"),
                    quantidade_dose=float(h.get("quantidade_dose", 1.0)),
                    dias_semana=h.get("dias_semana", "todos"),
                    ativo=h.get("ativo", True),
                )
                self.session.add(horario_obj)
            await self.session.flush()

        await self.session.commit()
        return await self.obter_por_id(med.id)

    async def obter_por_id(self, medicamento_id: int) -> Medicamento | None:
        stmt = (
            select(Medicamento)
            .where(Medicamento.id == medicamento_id)
            .options(
                selectinload(Medicamento.horarios),
                selectinload(Medicamento.registos_toma),
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def listar_todos(self) -> list[Medicamento]:
        stmt = (
            select(Medicamento)
            .where(Medicamento.ativo == True)
            .options(
                selectinload(Medicamento.horarios),
                selectinload(Medicamento.registos_toma),
            )
            .order_by(Medicamento.titular, Medicamento.nome)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def listar_por_titular(self, titular: str | None = None) -> list[Medicamento]:
        stmt = select(Medicamento).where(Medicamento.ativo == True)
        if titular:
            stmt = stmt.where(Medicamento.titular.ilike(f"%{titular}%"))
        stmt = stmt.options(
            selectinload(Medicamento.horarios),
            selectinload(Medicamento.registos_toma),
        ).order_by(Medicamento.nome)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def registar_toma(
        self,
        medicamento_id: int,
        data_hora_prevista: datetime | None = None,
        data_hora_tomada: datetime | None = None,
        registado_via: str = "mobile_notification",
        observacoes: str | None = None,
        quantidade_dose: float | None = None,
    ) -> MedicamentoRegistoToma:
        med = await self.obter_por_id(medicamento_id)
        if not med:
            raise ValueError(f"Medicamento com ID {medicamento_id} não encontrado")

        agora = datetime.now(timezone.utc)
        prevista = data_hora_prevista or agora
        tomada = data_hora_tomada or agora

        dose = quantidade_dose or 1.0
        if med.horarios:
            dose = float(med.horarios[0].quantidade_dose)

        # Decrementar stock
        novo_stock = max(0, med.stock_atual - int(dose))
        med.stock_atual = novo_stock
        med.atualizado_em = agora

        registo = MedicamentoRegistoToma(
            medicamento_id=med.id,
            data_hora_prevista=prevista,
            data_hora_tomada=tomada,
            estado="tomado",
            registado_via=registado_via,
            observacoes=observacoes,
        )
        self.session.add(registo)
        await self.session.commit()
        return registo

    async def repor_stock(self, medicamento_id: int, quantidade: int) -> Medicamento:
        med = await self.obter_por_id(medicamento_id)
        if not med:
            raise ValueError(f"Medicamento com ID {medicamento_id} não encontrado")

        med.stock_atual += max(0, quantidade)
        med.atualizado_em = datetime.now(timezone.utc)
        await self.session.commit()
        return med

    async def ajustar_stock(self, medicamento_id: int, novo_stock: int) -> Medicamento:
        med = await self.obter_por_id(medicamento_id)
        if not med:
            raise ValueError(f"Medicamento com ID {medicamento_id} não encontrado")

        med.stock_atual = max(0, novo_stock)
        med.atualizado_em = datetime.now(timezone.utc)
        await self.session.commit()
        return med

    async def obter_medicamentos_stock_baixo(self) -> list[dict]:
        meds = await self.listar_todos()
        resultado = []
        for m in meds:
            doses_dia = sum(float(h.quantidade_dose) for h in m.horarios if h.ativo) if m.horarios else 1.0
            if doses_dia <= 0:
                doses_dia = 1.0
            dias_autonomia = int(m.stock_atual / doses_dia)

            if m.stock_atual <= m.stock_minimo_alerta:
                resultado.append({
                    "id": m.id,
                    "titular": m.titular,
                    "nome": m.nome,
                    "dosagem": m.dosagem,
                    "stock_atual": m.stock_atual,
                    "stock_minimo_alerta": m.stock_minimo_alerta,
                    "dias_autonomia": dias_autonomia,
                    "urgente": dias_autonomia <= 3,
                })
        return resultado

    async def obter_schedule_sync(self, dias: int = 7) -> list[dict]:
        """Gera lista de alarmes programados para sincronização local com o Android AlarmManager."""
        meds = await self.listar_todos()
        hoje = date.today()
        dias_semana_map = {0: "seg", 1: "ter", 2: "qua", 3: "qui", 4: "sex", 5: "sab", 6: "dom"}

        schedule = []
        for offset in range(dias):
            dia_alvo = hoje + timedelta(days=offset)
            dia_sem_str = dias_semana_map[dia_alvo.weekday()]

            for m in meds:
                for h in m.horarios:
                    if not h.ativo:
                        continue
                    
                    # Verificar dia da semana
                    dias_config = h.dias_semana.lower()
                    if dias_config != "todos" and dia_sem_str not in dias_config:
                        continue

                    parts = h.hora.split(":")
                    hora_int = int(parts[0]) if len(parts) > 0 else 8
                    minuto_int = int(parts[1]) if len(parts) > 1 else 0

                    dt_programada = datetime(
                        dia_alvo.year, dia_alvo.month, dia_alvo.day,
                        hora_int, minuto_int, 0, tzinfo=timezone.utc
                    )

                    doses_dia = sum(float(hor.quantidade_dose) for hor in m.horarios if hor.ativo) or 1.0
                    dias_autonomia = int(m.stock_atual / doses_dia)

                    schedule.append({
                        "id": f"med-{m.id}-{dia_alvo.isoformat()}-{h.hora.replace(':', '')}",
                        "medicamento_id": m.id,
                        "titular": m.titular,
                        "nome": m.nome,
                        "dosagem": m.dosagem,
                        "hora": h.hora,
                        "quantidade_dose": float(h.quantidade_dose),
                        "data_hora_prevista": dt_programada.isoformat(),
                        "stock_atual": m.stock_atual,
                        "dias_autonomia": dias_autonomia,
                        "instrucoes": m.instrucoes_toma or "",
                    })

        schedule.sort(key=lambda x: x["data_hora_prevista"])
        return schedule

    async def criar_prescricao(
        self,
        titular: str,
        numero_receita_sns: str | None = None,
        codigo_acesso: str | None = None,
        codigo_opcao: str | None = None,
        data_emissao: date | None = None,
        data_validade: date | None = None,
        medico_prescritor: str | None = None,
        especialidade: str | None = None,
        notas: str | None = None,
    ) -> PrescricaoMedica:
        presc = PrescricaoMedica(
            titular=titular,
            numero_receita_sns=numero_receita_sns,
            codigo_acesso=codigo_acesso,
            codigo_opcao=codigo_opcao,
            data_emissao=data_emissao,
            data_validade=data_validade,
            medico_prescritor=medico_prescritor,
            especialidade=especialidade,
            notas=notas,
            estado="ativa",
        )
        self.session.add(presc)
        await self.session.commit()
        return presc

    async def listar_prescricoes(self, titular: str | None = None) -> list[PrescricaoMedica]:
        stmt = select(PrescricaoMedica)
        if titular:
            stmt = stmt.where(PrescricaoMedica.titular.ilike(f"%{titular}%"))
        stmt = stmt.order_by(PrescricaoMedica.data_validade.desc())
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
