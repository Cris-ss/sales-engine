"""Projeção única de lead: UMA linha por empresa, compartilhada por lista,
Kanban, métricas, mapa e exportação.

Nada aqui faz join direto com todos os scores/contatos/históricos (isso
multiplicaria linhas e distorceria paginação e métricas). Score e estágio
vigentes vêm de funções de janela (row_number = 1); contatos de email são
agregados por empresa em uma subconsulta.
"""

from __future__ import annotations

from sqlalchemy import Date, Float, String, and_, case, cast, func, select

from api.dominio import COLUNA_ESTAGIOS, SCORE_ALTO_MIN, SCORE_NEUTRO
from api.persistence.geo_models import EmpresaGeolocalizacao
from api.persistence.prospeccao_models import ValidacaoSiteDdg
from db.models import CanalContato, ContatoEnviado, Empresa, FunilStatus, LeadScore, Nicho, Validacao


def _mais_recente(model, colunas: dict):
    """Linha mais recente por empresa: criado_em DESC, id DESC (nulos por último)."""
    rn = func.row_number().over(
        partition_by=model.empresa_id,
        order_by=(model.criado_em.desc().nulls_last(), model.id.desc()),
    )
    sub = select(model.empresa_id.label("empresa_id"), *[e.label(n) for n, e in colunas.items()], rn.label("rn")).subquery()
    return select(sub).where(sub.c.rn == 1).subquery()


class LeadProjection:
    def __init__(self) -> None:
        E, N, V = Empresa, Nicho, Validacao

        self.ls = _mais_recente(
            LeadScore,
            {
                "score": LeadScore.score,
                "score_id": LeadScore.id,
                "score_em": LeadScore.criado_em,
                "modelo_usado": LeadScore.modelo_usado,
                "prompt_versao": LeadScore.prompt_versao,
                "dores_identificadas": LeadScore.dores_identificadas,
                "justificativa": LeadScore.justificativa,
            },
        )
        self.fs = _mais_recente(
            FunilStatus,
            {"funil_id": FunilStatus.id, "estagio_real": func.lower(cast(FunilStatus.estagio, String)), "funil_em": FunilStatus.criado_em},
        )

        ce = ContatoEnviado
        enviado = and_(ce.status_envio == "enviado", ce.sucesso_envio.is_(True))
        self.em = (
            select(
                ce.empresa_id.label("empresa_id"),
                func.count().filter(enviado).label("qtd_enviados"),
                func.max(ce.data_envio).filter(enviado).label("ultimo_envio"),
                func.count().filter(ce.status_envio == "pendente").label("qtd_pendentes"),
                func.count().filter(and_(ce.status_envio == "pendente", ce.erro.isnot(None))).label("qtd_erro"),
            )
            .where(ce.canal == CanalContato.EMAIL)
            .group_by(ce.empresa_id)
            .subquery("em")
        )

        # Geolocalização: 1 linha por empresa (unique), então o join não multiplica linhas.
        self.geo = EmpresaGeolocalizacao.__table__
        self.ddg = ValidacaoSiteDdg.__table__

        self.E, self.N, self.V = E, N, V
        self.join = (
            E.__table__.join(N.__table__, N.id == E.nicho_id)
            .outerjoin(V.__table__, V.empresa_id == E.id)
            .outerjoin(self.ls, self.ls.c.empresa_id == E.id)
            .outerjoin(self.fs, self.fs.c.empresa_id == E.id)
            .outerjoin(self.em, self.em.c.empresa_id == E.id)
            .outerjoin(self.geo, self.geo.c.empresa_id == E.id)
            .outerjoin(self.ddg, self.ddg.c.empresa_id == E.id)
        )
        self.tem_localizacao = func.coalesce(self.geo.c.status == "localizada", False)

        # --- expressões derivadas (reutilizadas em filtros, ordenação e métricas) ---
        self.nome = func.coalesce(func.nullif(E.nome_fantasia, ""), func.nullif(E.razao_social, ""), E.cnpj)
        # Consulta do botão "Buscar" (Google). Com endereço: "nome" rua número – bairro – município/UF
        # (sem complemento nem CEP). Sem logradouro (ex.: leads OSM só com nome/cidade), o nome
        # não basta para identificar a empresa: vira busca por categoria, com o nicho explícito.
        rua = func.nullif(func.trim(func.concat_ws(" ", E.logradouro, E.numero)), "")
        cidade_uf = func.nullif(func.concat_ws("/", func.nullif(E.municipio, ""), func.nullif(E.uf, "")), "")
        nome_aspas = func.concat('"', self.nome, '"')
        self.consulta_busca = case(
            (
                func.nullif(func.trim(E.logradouro), "").is_not(None),
                func.concat_ws(" ", nome_aspas, func.concat_ws(" – ", rua, func.nullif(E.bairro, ""), cidade_uf)),
            ),
            else_=func.concat_ws(" ", nome_aspas, func.concat("(nicho: ", Nicho.nome, ")"), cidade_uf),
        )
        self.score = self.ls.c.score
        self.qtd_enviados = func.coalesce(self.em.c.qtd_enviados, 0)
        self.qtd_pendentes = func.coalesce(self.em.c.qtd_pendentes, 0)
        self.qtd_erro = func.coalesce(self.em.c.qtd_erro, 0)

        # Estágio efetivo: o último FunilStatus manda. Sem histórico, é DERIVADO
        # (nada é gravado na leitura): email realmente enviado => contatada,
        # caso contrário encontrada.
        self.estagio_derivado = self.fs.c.funil_id.is_(None)
        self.estagio = case(
            (self.fs.c.funil_id.isnot(None), self.fs.c.estagio_real),
            (self.qtd_enviados > 0, "contatada"),
            else_="encontrada",
        )
        self.coluna = case(
            *[(self.estagio.in_(ests), col) for col, ests in COLUNA_ESTAGIOS.items()],
            else_="novo",
        )

        self.faixa = case(
            (self.score.is_(None), "sem_score"),
            (func.abs(cast(self.score, Float) - SCORE_NEUTRO) < 1e-9, "neutro"),
            (self.score < SCORE_NEUTRO, "baixo"),
            (self.score >= SCORE_ALTO_MIN, "alto"),
            else_="medio",
        )

        canal_ok = V.tem_pelo_menos_um_canal.is_(True)
        self.email_confirmado = and_(canal_ok, V.email_final.isnot(None), V.email_final != "")
        self.formulario_confirmado = and_(canal_ok, V.formulario_contato_url.isnot(None), V.formulario_contato_url != "")

        self.email_status = case(
            (self.qtd_enviados > 0, "enviado"),
            (self.qtd_erro > 0, "falhou"),
            (self.qtd_pendentes > 0, "pendente"),
            else_="nenhum",
        )
        self.site_ddg = func.coalesce(self.ddg.c.resultado, "legado")
        # A Receita pode devolver ISO ou DD/MM/AAAA. Dados antigos inválidos ficam
        # sem data para filtro, em vez de fazer a consulta falhar.
        self.data_inicio_atividade = case(
            (E.data_inicio_atividade.op("~")(r"^\d{4}-\d{2}-\d{2}$"), cast(E.data_inicio_atividade, Date)),
            (E.data_inicio_atividade.op("~")(r"^\d{2}/\d{2}/\d{4}$"), func.to_date(E.data_inicio_atividade, "DD/MM/YYYY")),
            else_=None,
        )

    # --- selects -----------------------------------------------------------------
    def colunas_lista(self):
        E, N, V = self.E, self.N, self.V
        return [
            E.id.label("id"),
            E.cnpj.label("cnpj"),
            self.nome.label("nome"),
            E.nicho_id.label("nicho_id"),
            N.slug.label("nicho_slug"),
            N.nome.label("nicho_nome"),
            E.municipio.label("municipio"),
            E.uf.label("uf"),
            self.consulta_busca.label("consulta_busca"),
            E.fonte.label("fonte"),
            E.telefone1.label("telefone1"),
            E.telefone2.label("telefone2"),
            self.score.label("score"),
            self.faixa.label("faixa_score"),
            self.estagio.label("estagio"),
            self.estagio_derivado.label("estagio_derivado"),
            self.coluna.label("coluna"),
            self.fs.c.funil_id.label("funil_id"),
            self.email_confirmado.label("email_confirmado"),
            self.formulario_confirmado.label("formulario_confirmado"),
            func.coalesce(V.site_url, self.ddg.c.site_url).label("site_url"),
            self.site_ddg.label("site_ddg_status"),
            V.motivo_reprovacao.label("motivo_reprovacao"),
            self.email_status.label("email_status"),
            self.qtd_enviados.label("qtd_emails_enviados"),
            self.em.c.ultimo_envio.label("email_enviado_em"),
            self.tem_localizacao.label("tem_localizacao"),
            case((self.tem_localizacao, self.geo.c.precisao), else_=None).label("precisao_geo"),
        ]

    def colunas_detalhe(self):
        E, V = self.E, self.V
        return self.colunas_lista() + [
            E.razao_social.label("razao_social"),
            E.nome_fantasia.label("nome_fantasia"),
            E.logradouro.label("logradouro"),
            E.numero.label("numero"),
            E.complemento.label("complemento"),
            E.bairro.label("bairro"),
            E.cep.label("cep"),
            E.porte.label("porte"),
            E.natureza_juridica.label("natureza_juridica"),
            E.cnae_principal.label("cnae_principal"),
            E.data_inicio_atividade.label("data_inicio_atividade"),
            E.criado_em.label("criado_em"),
            V.email_final.label("email_final"),
            V.formulario_contato_url.label("formulario_contato_url"),
            V.site_ativo.label("site_ativo"),
            V.places_verificado.label("places_verificado"),
            V.places_telefone_confirmado.label("places_telefone_confirmado"),
            V.places_endereco_confirmado.label("places_endereco_confirmado"),
            V.tem_pelo_menos_um_canal.label("tem_pelo_menos_um_canal"),
            self.ls.c.score_em.label("score_em"),
            self.ls.c.modelo_usado.label("modelo_usado"),
            self.ls.c.prompt_versao.label("prompt_versao"),
            self.ls.c.dores_identificadas.label("dores_identificadas"),
            self.ls.c.justificativa.label("justificativa"),
            case((self.tem_localizacao, self.geo.c.latitude), else_=None).label("latitude"),
            case((self.tem_localizacao, self.geo.c.longitude), else_=None).label("longitude"),
            case((self.tem_localizacao, self.geo.c.fonte), else_=None).label("fonte_geo"),
        ]

    def select(self, colunas=None):
        return select(*(colunas or self.colunas_lista())).select_from(self.join)

    def count(self):
        return select(func.count(self.E.id)).select_from(self.join)

    def ordenacao(self, campo: str, direcao: str):
        expr = {
            "nome": func.lower(self.nome),
            "score": self.score,
            "uf": self.E.uf,
            "municipio": func.lower(self.E.municipio),
            "nicho": self.N.nome,
            "estagio": self.estagio,
            "email_enviado_em": self.em.c.ultimo_envio,
            "criado_em": self.E.criado_em,
            "data_inicio_atividade": self.data_inicio_atividade,
        }[campo]
        ordenado = expr.asc().nulls_last() if direcao == "asc" else expr.desc().nulls_last()
        return [ordenado, self.E.id.asc()]  # desempate estável por id
