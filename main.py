"""Orquestrador do pipeline de prospecção.

Ordem de execução:
    1. Sincroniza nichos (config/nichos.yaml) no banco.
    2. etapa1_busca: para cada nicho, busca empresas ativas por CNAE
       (Receita Federal via Apify) e insere as que ainda não existem.
    3. etapa2_validacao: para empresas sem Validacao, roda Places
       discovery (busca + verificação) e, se houver website confirmado,
       o scraper de contato (email / formulário).

As etapas 3 (scoring), 4 (e-mail) e 5 (envio) rodam por módulos próprios,
fora deste orquestrador (veja o README).
"""

from __future__ import annotations

import os
import unicodedata
import sys
from typing import Callable, Iterable, Optional

import yaml
from dotenv import load_dotenv

from db.models import Empresa, Nicho, Validacao, get_session_factory, init_db
from etapa1_busca.cnpj_client import CnpjClient
from etapa1_busca.osm_client import EmpresaOsm
from etapa2_validacao.places_discovery import DadosCnpj, PlacesDiscovery
from etapa2_validacao.duckduckgo_discovery import DuckDuckGoDiscovery
from etapa2_validacao.website_scraper import WebsiteScraper

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "nichos.yaml")


def carregar_nichos_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _somente_digitos(valor: Optional[str]) -> Optional[str]:
    if not valor:
        return None
    digitos = "".join(c for c in valor if c.isdigit())
    return digitos or None


def sincronizar_nichos(session, config: dict) -> dict[str, Nicho]:
    nichos_por_slug: dict[str, Nicho] = {}
    for slug, dados in config["nichos"].items():
        nicho = session.query(Nicho).filter_by(slug=slug).one_or_none()
        if nicho is None:
            nicho = Nicho(slug=slug)
            session.add(nicho)
        nicho.nome = dados["nome"]
        nicho.cnae = dados["cnae"]
        nicho.contexto_dores = dados.get("contexto_dores")
        nicho.argumentos_venda = dados.get("argumentos_venda")
        nicho.tom_abordagem = dados.get("tom_abordagem")
        nichos_por_slug[slug] = nicho
    session.commit()
    return nichos_por_slug


def etapa1_buscar_empresas(
    session,
    nicho: Nicho,
    cnpj_client: CnpjClient,
    max_items: int = 100,
    uf: Optional[str] = None,
) -> list[int]:
    print(f"[etapa1] Buscando empresas do nicho '{nicho.slug}' (CNAE {nicho.cnae})...")
    itens = cnpj_client.buscar_por_cnae(cnae=nicho.cnae, max_items=max_items, uf=uf)

    novos = 0
    duplicados = 0
    ids_novos: list[int] = []
    for item in itens:
        cnpj = _somente_digitos(item.get("cnpj"))
        if not cnpj:
            continue

        existente = session.query(Empresa).filter_by(cnpj=cnpj).one_or_none()
        if existente:
            duplicados += 1
            continue

        empresa = Empresa(
            nicho_id=nicho.id,
            cnpj=cnpj,
            razao_social=item.get("razaoSocial") or item.get("razao_social"),
            nome_fantasia=item.get("nomeFantasia") or item.get("nome_fantasia"),
            situacao_cadastral=item.get("situacaoCadastral") or item.get("situacao_cadastral"),
            data_situacao_cadastral=item.get("data_situacao_cadastral"),
            data_inicio_atividade=item.get("data_abertura"),
            cnae_principal=item.get("cnaePrincipal")
            or item.get("cnae_principal_codigo")
            or nicho.cnae,
            natureza_juridica_codigo=item.get("natureza_juridica_codigo"),
            natureza_juridica=item.get("natureza_juridica"),
            logradouro=item.get("logradouro"),
            numero=item.get("numero"),
            complemento=item.get("complemento"),
            bairro=item.get("bairro"),
            municipio=item.get("municipio"),
            uf=item.get("uf"),
            cep=item.get("cep"),
            telefone1=item.get("telefone1"),
            telefone2=item.get("telefone2"),
            email_receita=item.get("email"),
            porte=item.get("porte"),
        )
        session.add(empresa)
        session.flush()
        ids_novos.append(empresa.id)
        novos += 1

    session.commit()
    print(
        f"[etapa1] '{nicho.slug}': {novos} empresas novas inseridas, "
        f"{duplicados} descartadas por CNPJ já existente no banco "
        f"(descarte por natureza jurídica é reportado acima, pelo cnpj_client)."
    )
    return ids_novos


def etapa1_buscar_empresas_osm(
    session, nicho: Nicho, itens: Iterable[EmpresaOsm], fonte: str = "openstreetmap",
    deduplicar_nome_local: bool = False,
) -> list[tuple[int, EmpresaOsm]]:
    """Insere somente estabelecimentos locais ainda não vistos; não altera empresas Receita."""
    inseridas: list[tuple[int, EmpresaOsm]] = []
    chaves_existentes: set[tuple[str, str, str]] = set()
    if deduplicar_nome_local:
        existentes = session.query(Empresa.nome_fantasia, Empresa.municipio, Empresa.uf).filter(Empresa.nicho_id == nicho.id).all()
        chaves_existentes = {_chave_empresa_local(*linha) for linha in existentes}
    for item in itens:
        if session.query(Empresa.id).filter_by(fonte_externo_id=item.externo_id).first():
            continue
        chave = _chave_empresa_local(item.nome, item.municipio, item.uf)
        if deduplicar_nome_local and chave in chaves_existentes:
            continue
        empresa = Empresa(
            nicho_id=nicho.id, fonte=fonte, fonte_externo_id=item.externo_id,
            nome_fantasia=item.nome, municipio=item.municipio, uf=item.uf,
            logradouro=item.logradouro, numero=item.numero, bairro=item.bairro, cep=item.cep,
            telefone1=item.telefone,
        )
        session.add(empresa)
        session.flush()
        inseridas.append((empresa.id, item))
        chaves_existentes.add(chave)
    return inseridas


def _chave_empresa_local(nome: str | None, municipio: str | None, uf: str | None) -> tuple[str, str, str]:
    def normalizar(valor: str | None) -> str:
        base = unicodedata.normalize("NFKD", valor or "")
        return "".join(c for c in base if not unicodedata.combining(c)).casefold().strip()

    return normalizar(nome), normalizar(municipio), normalizar(uf)


def criar_places_discovery() -> PlacesDiscovery:
    """Cria o cliente Places somente quando ele de fato será usado.

    Sem GOOGLE_PLACES_API_KEY levanta ValueError("GOOGLE_PLACES_API_KEY não configurado").
    """
    return PlacesDiscovery(api_key=os.environ.get("GOOGLE_PLACES_API_KEY", ""))


def etapa2_validar_contato(session, places: PlacesDiscovery | Callable[[], PlacesDiscovery], scraper: WebsiteScraper) -> None:
    """`places` pode ser uma fábrica: só é chamada se houver empresas pendentes.

    O erro de chave ausente sobe ANTES do loop (não é engolido como `erro_places`).
    """
    empresas_pendentes = (
        session.query(Empresa).outerjoin(Validacao).filter(Validacao.id.is_(None)).all()
    )
    print(f"[etapa2] {len(empresas_pendentes)} empresas pendentes de validação de contato.")
    if empresas_pendentes and callable(places):
        places = places()

    for empresa in empresas_pendentes:
        validacao = Validacao(empresa_id=empresa.id)

        dados_cnpj = DadosCnpj(
            nome_fantasia=empresa.nome_fantasia,
            razao_social=empresa.razao_social,
            municipio=empresa.municipio or "",
            uf=empresa.uf or "",
            logradouro=empresa.logradouro,
            telefone1=empresa.telefone1,
            telefone2=empresa.telefone2,
        )

        try:
            resultado_places = places.descobrir(dados_cnpj)
        except Exception as exc:
            print(f"[etapa2] erro no Places para {empresa.cnpj}: {exc}")
            resultado_places = None

        if resultado_places and resultado_places.verificado:
            validacao.place_id = resultado_places.place_id
            validacao.places_verificado = True
            validacao.places_telefone_confirmado = resultado_places.telefone_bateu
            validacao.places_endereco_confirmado = resultado_places.endereco_bateu

            if resultado_places.website:
                validacao.site_url = resultado_places.website
                try:
                    resultado_scraping = scraper.extrair_contato(resultado_places.website)
                except Exception as exc:
                    print(f"[etapa2] erro no scraping de {resultado_places.website}: {exc}")
                    resultado_scraping = None

                if resultado_scraping:
                    validacao.site_ativo = resultado_scraping.site_ativo
                    validacao.email_final = resultado_scraping.email
                    validacao.formulario_contato_url = resultado_scraping.formulario_contato_url
                    validacao.formulario_contato_disponivel = bool(
                        resultado_scraping.formulario_contato_url
                    )
        else:
            validacao.places_verificado = False
            validacao.motivo_reprovacao = resultado_places.motivo if resultado_places else "erro_places"

        validacao.tem_pelo_menos_um_canal = bool(validacao.email_final or validacao.formulario_contato_url)
        validacao.passou_filtro = validacao.tem_pelo_menos_um_canal
        if not validacao.passou_filtro and not validacao.motivo_reprovacao:
            validacao.motivo_reprovacao = "sem_email_ou_formulario"

        session.add(validacao)
        session.commit()

        status = "OK" if validacao.passou_filtro else "REPROVADA"
        nome = empresa.nome_fantasia or empresa.razao_social
        print(f"[etapa2] {empresa.cnpj} ({nome}): {status}")


def etapa2_validar_lote_duckduckgo(
    session, empresas: Iterable[Empresa], discovery: DuckDuckGoDiscovery, scraper: WebsiteScraper
) -> Iterable[tuple[Empresa, object, object]]:
    """Valida apenas empresas novas do lote. Nunca altera validações legadas."""
    for empresa in empresas:
        dados = DadosCnpj(
            nome_fantasia=empresa.nome_fantasia,
            razao_social=empresa.razao_social,
            municipio=empresa.municipio or "",
            uf=empresa.uf or "",
            logradouro=empresa.logradouro,
            telefone1=empresa.telefone1,
            telefone2=empresa.telefone2,
        )
        resultado = discovery.descobrir(dados)
        # A associação com o lote e o registro de auditoria são feitos pelo worker.
        yield empresa, resultado, scraper.extrair_contato(resultado.website) if resultado.website else None


def main() -> int:
    load_dotenv()

    database_url = os.environ["DATABASE_URL"]
    apify_token = os.environ["APIFY_TOKEN"]

    engine = init_db(database_url)
    session_factory = get_session_factory(engine)
    session = session_factory()

    try:
        config = carregar_nichos_config()
        nichos = sincronizar_nichos(session, config)

        cnpj_client = CnpjClient(api_token=apify_token)
        scraper = WebsiteScraper()

        for nicho in nichos.values():
            etapa1_buscar_empresas(session, nicho, cnpj_client)

        # A chave do Places só é exigida aqui, se houver o que validar via Places.
        etapa2_validar_contato(session, criar_places_discovery, scraper)
    finally:
        session.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
