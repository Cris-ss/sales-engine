"""Executa um lote pendente sem rodar dentro do processo HTTP.

Uso: python -m maintenance.prospeccao.worker
O comando processa um único lote por vez; execute novamente para o próximo.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import select

from api.persistence.geo_models import EmpresaGeolocalizacao
from api.persistence.prospeccao_models import LoteProspeccao, LoteProspeccaoEmpresa, ValidacaoSiteDdg
from db.models import Empresa, Nicho, Validacao, get_session_factory, init_db
from etapa1_busca.cnpj_client import CnpjClient
from etapa1_busca.google_places_client import GooglePlacesClient
from etapa1_busca.osm_client import OsmClient
from etapa2_validacao.duckduckgo_discovery import DuckDuckGoDiscovery, ResultadoDdg
from etapa2_validacao.website_scraper import WebsiteScraper
from main import carregar_nichos_config, etapa1_buscar_empresas, etapa1_buscar_empresas_osm, sincronizar_nichos


def _proximo_lote(session):
    lote = session.execute(
        select(LoteProspeccao).where(LoteProspeccao.status == "pendente").order_by(LoteProspeccao.id).with_for_update(skip_locked=True).limit(1)
    ).scalar_one_or_none()
    if lote is None:
        return None
    lote.status = "executando"
    from sqlalchemy import func

    lote.iniciado_em = func.clock_timestamp()
    session.commit()
    return lote


def executar_um_lote() -> int:
    load_dotenv()
    engine = init_db(os.environ["DATABASE_URL"])
    session = get_session_factory(engine)()
    try:
        lote = _proximo_lote(session)
        if lote is None:
            print("Nenhum lote pendente.")
            return 0
        try:
            nichos = sincronizar_nichos(session, carregar_nichos_config())
            nicho = session.get(Nicho, lote.nicho_id)
            if nicho is None:
                raise RuntimeError(f"Nicho {lote.nicho_id} não existe")
            sites_fonte: dict[int, str] = {}
            if lote.fonte in ("osm", "google_places"):
                if not lote.cidade or (lote.fonte == "osm" and not lote.raio_km):
                    raise RuntimeError("Lote local sem cidade ou raio")
                if lote.fonte == "google_places":
                    # Fonte Google Places desativada.
                    raise RuntimeError("A fonte Google Places está desativada neste projeto.")
                    itens_osm = GooglePlacesClient(os.environ.get("GOOGLE_PLACES_API_KEY", "")).buscar(
                        nicho.nome, lote.cidade, lote.uf, lote.limite,
                    )
                    fonte_empresa = "google_places"
                else:
                    itens_osm = OsmClient().buscar(nicho.slug, lote.cidade, lote.uf, lote.raio_km, lote.limite)
                    fonte_empresa = "openstreetmap"
                lote.total_encontrado = len(itens_osm)
                inseridas = etapa1_buscar_empresas_osm(
                    session, nicho, itens_osm, fonte=fonte_empresa,
                    deduplicar_nome_local=lote.fonte == "google_places",
                )
                lote.total_duplicado = len(itens_osm) - len(inseridas)
                novos_ids = [empresa_id for empresa_id, _ in inseridas]
                sites_fonte = {empresa_id: item.website for empresa_id, item in inseridas if item.website}
                for empresa_id, item in inseridas:
                    session.add(LoteProspeccaoEmpresa(lote_id=lote.id, empresa_id=empresa_id))
                    session.add(EmpresaGeolocalizacao(
                        empresa_id=empresa_id, latitude=item.latitude, longitude=item.longitude,
                        fonte=fonte_empresa, precisao="estabelecimento", status="localizada",
                    ))
                session.commit()
            else:
                novos_ids = etapa1_buscar_empresas(
                    session, nicho, CnpjClient(api_token=os.environ["APIFY_TOKEN"]), max_items=lote.limite, uf=lote.uf
                )
                lote.total_encontrado = len(novos_ids)
                lote.total_duplicado = 0
                for empresa_id in novos_ids:
                    session.add(LoteProspeccaoEmpresa(lote_id=lote.id, empresa_id=empresa_id))
                session.commit()

            empresas = session.execute(select(Empresa).where(Empresa.id.in_(novos_ids))).scalars().all()
            scraper = WebsiteScraper()
            discovery = DuckDuckGoDiscovery()
            for empresa in empresas:
                if empresa.id in sites_fonte:
                    origem = "Google Places" if lote.fonte == "google_places" else "OpenStreetMap"
                    resultado = "encontrado" if lote.fonte == "google_places" else "site_osm"
                    ddg = ResultadoDdg(consulta=f"site informado pelo {origem}", resultado=resultado, website=sites_fonte[empresa.id], confianca="media")
                else:
                    from etapa2_validacao.places_discovery import DadosCnpj
                    ddg = discovery.descobrir(DadosCnpj(empresa.nome_fantasia, empresa.razao_social or empresa.nome_fantasia or "", empresa.municipio or "", empresa.uf or "", empresa.logradouro, empresa.telefone1, empresa.telefone2))
                scraping = scraper.extrair_contato(ddg.website) if ddg.website else None
                registro = ValidacaoSiteDdg(
                    empresa_id=empresa.id, lote_id=lote.id, consulta=ddg.consulta, resultado=ddg.resultado,
                    dominio_candidato=ddg.dominio_candidato, site_url=ddg.website,
                    posicao_resultado=ddg.posicao_resultado, confianca=ddg.confianca,
                    resultados_resumo=ddg.resultados_resumo, erro=ddg.erro,
                    site_ativo=scraping.site_ativo if scraping else None,
                    email_final=scraping.email if scraping else None,
                    formulario_contato_url=scraping.formulario_contato_url if scraping else None,
                )
                session.add(registro)
                # Mantém os estágios seguintes compatíveis somente para novos leads.
                if scraping and scraping.tem_pelo_menos_um_canal:
                    session.add(Validacao(
                        empresa_id=empresa.id, site_url=ddg.website, site_ativo=scraping.site_ativo,
                        email_final=scraping.email, formulario_contato_url=scraping.formulario_contato_url,
                        formulario_contato_disponivel=bool(scraping.formulario_contato_url),
                        tem_pelo_menos_um_canal=True, passou_filtro=True,
                        motivo_reprovacao="origem_duckduckgo",
                    ))
                session.commit()
            lote.status = "concluido"
            from sqlalchemy import func

            lote.concluido_em = func.clock_timestamp()
            session.commit()
            print(f"Lote {lote.id} concluído ({lote.fonte}): {len(novos_ids)} empresas novas.")
            return 0
        except Exception as exc:
            session.rollback()
            lote = session.get(LoteProspeccao, lote.id)
            lote.status = "falhou"
            lote.erro = str(exc)
            session.commit()
            raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(executar_um_lote())
