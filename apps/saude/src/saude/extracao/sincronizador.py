import logging
from sqlalchemy.ext.asyncio import AsyncSession

from saude.config import get_settings
from saude.extracao.parser_email_saude import extrair_marcacao_saude
from saude.repositories import saude_repo

logger = logging.getLogger("saude.sincronizador")


class SincronizadorSaude:
    def __init__(self, paperless_url: str, paperless_token: str) -> None:
        self.paperless_url = paperless_url.rstrip("/")
        self.paperless_token = paperless_token

    async def sincronizar_documentos_paperless(self, session: AsyncSession) -> dict[str, int]:
        """Procura documentos no Paperless relacionados com saúde e cria consultas/exames."""
        import httpx

        headers = {"Authorization": f"Token {self.paperless_token}"}
        contagem = {"processados": 0, "consultas_criadas": 0, "exames_criados": 0}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Procura documentos que contenham termos de saúde ou confirmações
                url = f"{self.paperless_url}/api/documents/"
                params = {"query": "consulta OR agendamento OR marcacao OR exame OR cuf OR luz OR hospital", "page_size": "50"}
                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code != 200:
                    logger.warning("Paperless respondeu com status %s", resp.status_code)
                    return contagem

                docs = resp.json().get("results", [])
                for doc in docs:
                    doc_id = doc.get("id")
                    conteudo = doc.get("content", "")
                    if not conteudo:
                        continue

                    marcacao = extrair_marcacao_saude(conteudo)
                    if not marcacao:
                        continue

                    contagem["processados"] += 1
                    perfil = None
                    if marcacao.nome_paciente:
                        perfil = await saude_repo.obter_perfil_por_nome_titular(session, marcacao.nome_paciente)
                    if not perfil:
                        # Fallback para o titular principal
                        perfil = await saude_repo.obter_perfil_por_nome_titular(session, "aa-stop-run")

                    if not perfil:
                        continue

                    if marcacao.tipo == "consulta":
                        # Verifica se já existe consulta semelhante
                        todas_c = await saude_repo.listar_todas_consultas(session)
                        ja_existe = any(
                            c.perfil_id == perfil.id
                            and c.data_hora == marcacao.data_hora
                            and c.especialidade == marcacao.especialidade
                            for c in todas_c
                        )
                        if not ja_existe:
                            await saude_repo.registar_consulta(
                                session,
                                perfil_id=perfil.id,
                                data_hora=marcacao.data_hora,
                                especialidade=marcacao.especialidade,
                                medico=marcacao.medico,
                                local_clinica=marcacao.local_clinica,
                                preparacao_instrucoes=marcacao.preparacao_instrucoes,
                                codigo_confirmacao=marcacao.codigo_confirmacao,
                                documento_id=doc_id,
                            )
                            contagem["consultas_criadas"] += 1
                    else:
                        await saude_repo.registar_exame(
                            session,
                            perfil_id=perfil.id,
                            data=marcacao.data_hora.date(),
                            tipo_exame=marcacao.especialidade,
                            laboratorio_clinica=marcacao.local_clinica,
                            descricao=marcacao.preparacao_instrucoes,
                            documento_id=doc_id,
                        )
                        contagem["exames_criados"] += 1

        except Exception as e:
            logger.error("Erro ao sincronizar com Paperless: %s", e)

        return contagem
