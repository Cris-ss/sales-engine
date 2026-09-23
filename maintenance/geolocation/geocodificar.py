"""Enriquecimento geográfico EXPLÍCITO (fora das 6 etapas do pipeline).

    python -m maintenance.geolocation.geocodificar municipio [--dry-run]
    python -m maintenance.geolocation.geocodificar cep --limite 30 [--dry-run]
    python -m maintenance.geolocation.geocodificar corrigir-cep-geral [--dry-run]
    python -m maintenance.geolocation.geocodificar relatorio

- `municipio`: preenche TODAS as empresas com a sede do município (sem API paga,
  sem consulta por empresa). Idempotente: não mexe em quem já tem linha.
- `cep`: refina por CEP via AwesomeAPI, com pausa entre chamadas, cache (o próprio
  banco + memo por CEP), retomável e sem repetir o que já foi resolvido. Um ponto de
  CEP a mais de 60 km da sede do município é marcado "ambigua" e NÃO substitui a posição
  municipal. Para o lote na primeira vez use --limite 30 e confira antes de ampliar.

Usa apenas a tabela `empresa_geolocalizacoes` (criada pela migração 0002).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from api import settings
from api.persistence.geo_models import FONTE_CEP, FONTE_MUNICIPIO, EmpresaGeolocalizacao
from db.models import Empresa, get_engine
from maintenance.geolocation.fontes import (
    DISTANCIA_MAX_KM_CEP_X_MUNICIPIO, USER_AGENT, carregar_indice_municipios, consultar_cep, haversine_km, normalizar,
)

PAUSA_ENTRE_CHAMADAS_S = 0.6
MAX_TENTATIVAS_CEP = 3
MAX_ERROS_SEGUIDOS = 3
NOTA_CEP_GERAL = "CEP geral do município (termina em 000): sem precisão de rua; mantida a posição municipal"


def _hash(*partes: str) -> str:
    return hashlib.sha256("|".join(partes).encode("utf-8")).hexdigest()


def etapa_municipio(s: Session, dry_run: bool) -> None:
    indice = carregar_indice_municipios()
    ja = set(s.execute(select(EmpresaGeolocalizacao.empresa_id)).scalars())
    novos, sem_match = 0, Counter()
    for e in s.execute(select(Empresa)).scalars():
        if e.id in ja:
            continue
        chave = (normalizar(e.municipio), (e.uf or "").upper())
        ponto = indice.get(chave)
        if ponto:
            reg = EmpresaGeolocalizacao(
                empresa_id=e.id, latitude=ponto[0], longitude=ponto[1], fonte=FONTE_MUNICIPIO,
                precisao="municipio", status="localizada", endereco_hash=_hash(*chave),
            )
        else:
            sem_match[f"{e.municipio or '(vazio)'}/{e.uf}"] += 1
            reg = EmpresaGeolocalizacao(
                empresa_id=e.id, fonte=FONTE_MUNICIPIO, precisao="municipio", status="nao_encontrada",
                endereco_hash=_hash(*chave),
            )
        novos += 1
        if not dry_run:
            s.add(reg)
    if not dry_run:
        s.commit()
    print(f"[municipio] {'(dry-run) ' if dry_run else ''}linhas novas: {novos} | já existiam: {len(ja)}")
    print(f"[municipio] sem correspondência: {sum(sem_match.values())} empresas em {len(sem_match)} municípios")
    for nome, n in sem_match.most_common(15):
        print(f"   - {nome}: {n}")


def etapa_cep(s: Session, limite: int, dry_run: bool) -> None:
    pendentes = s.execute(
        select(EmpresaGeolocalizacao, Empresa.cep)
        .join(Empresa, Empresa.id == EmpresaGeolocalizacao.empresa_id)
        .where(
            EmpresaGeolocalizacao.status == "localizada",
            (EmpresaGeolocalizacao.cep_status == "pendente")
            | ((EmpresaGeolocalizacao.cep_status == "erro") & (EmpresaGeolocalizacao.cep_tentativas < MAX_TENTATIVAS_CEP)),
        )
        .order_by(func.md5(Empresa.cep), Empresa.id)  # amostra pseudo-aleatória porém determinística
        .limit(limite)
    ).all()
    print(f"[cep] {len(pendentes)} empresa(s) a consultar (limite {limite}){' — dry-run: nada será chamado' if dry_run else ''}")
    if dry_run:
        return

    memo: dict[str, object] = {}
    stats, erros_seguidos = Counter(), 0
    distancias: list[float] = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}) as http:
        for geo, cep in pendentes:
            chave = "".join(ch for ch in (cep or "") if ch.isdigit())
            if chave.endswith("000") and len(chave) == 8:
                # CEP geral do município: não localiza rua/bairro. Sem chamada; mantém a sede.
                geo.cep_status, geo.cep_erro = "ambigua", NOTA_CEP_GERAL
                geo.cep_consultado_em = func.now()
                stats["cep_geral_mantido_municipal"] += 1
                s.commit()
                continue
            if chave in memo:
                res = memo[chave]
            else:
                res = consultar_cep(cep, http)
                memo[chave] = res
                time.sleep(PAUSA_ENTRE_CHAMADAS_S)

            agora = func.now()
            geo.cep_consultado_em = agora
            if res.status == "erro":
                geo.cep_tentativas += 1
                geo.cep_erro = res.erro
                geo.cep_status = "erro"
                erros_seguidos += 1
                stats["erro"] += 1
                s.commit()
                if res.fatal or erros_seguidos >= MAX_ERROS_SEGUIDOS:
                    print(f"[cep] PARANDO: {res.erro} (erros seguidos: {erros_seguidos}). Nada mais será chamado.")
                    break
                continue
            erros_seguidos = 0

            if res.status != "localizada":
                geo.cep_status, geo.cep_erro = res.status, res.erro
                stats[res.status] += 1
            else:
                dist = haversine_km(geo.latitude, geo.longitude, res.latitude, res.longitude)
                distancias.append(dist)
                if dist > DISTANCIA_MAX_KM_CEP_X_MUNICIPIO:
                    geo.cep_status = "ambigua"
                    geo.cep_erro = f"ponto do CEP a {dist:.0f} km da sede do município; mantida a posição municipal"
                    stats["ambigua"] += 1
                else:
                    geo.latitude, geo.longitude = res.latitude, res.longitude
                    geo.fonte, geo.precisao = FONTE_CEP, "cep"
                    geo.endereco_hash = _hash(chave)
                    geo.cep_status, geo.cep_erro = "localizada", None
                    stats["localizada"] += 1
            s.commit()

    print(f"[cep] resultado: {dict(stats)}")
    if distancias:
        d = sorted(distancias)
        print(f"[cep] distância CEP x sede do município (km): mín {d[0]:.1f} | mediana {d[len(d)//2]:.1f} | máx {d[-1]:.1f}")
        print(f"[cep] a menos de 1 km da sede (provável 'centro da cidade'): {sum(x < 1 for x in d)}/{len(d)}")


def corrigir_ceps_gerais(s: Session, dry_run: bool) -> None:
    """Reverte para a sede do município os pontos "cep" gravados para CEPs gerais (…000)."""
    indice = carregar_indice_municipios()
    linhas = s.execute(
        select(EmpresaGeolocalizacao, Empresa)
        .join(Empresa, Empresa.id == EmpresaGeolocalizacao.empresa_id)
        .where(EmpresaGeolocalizacao.precisao == "cep", Empresa.cep.like("%000"))
    ).all()
    for geo, emp in linhas:
        chave = (normalizar(emp.municipio), (emp.uf or "").upper())
        if dry_run:
            continue
        geo.latitude, geo.longitude = indice[chave]
        geo.fonte, geo.precisao, geo.endereco_hash = FONTE_MUNICIPIO, "municipio", _hash(*chave)
        geo.cep_status, geo.cep_erro = "ambigua", NOTA_CEP_GERAL
    if not dry_run:
        s.commit()
    print(f"[corrigir] {'(dry-run) ' if dry_run else ''}pontos revertidos para a sede do município: {len(linhas)}")


def relatorio(s: Session) -> None:
    linhas = s.execute(text(
        "select precisao, status, cep_status, count(*) from empresa_geolocalizacoes group by 1,2,3 order by 4 desc"
    )).all()
    total = s.execute(text("select count(*) from empresas")).scalar()
    com = s.execute(text("select count(*) from empresa_geolocalizacoes where status='localizada'")).scalar()
    print(f"empresas: {total} | com coordenadas: {com} | sem: {total - com}")
    for p, st, cs, n in linhas:
        print(f"  precisao={p:9} status={st:15} cep_status={cs:14} {n}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("etapa", choices=["municipio", "cep", "corrigir-cep-geral", "relatorio"])
    ap.add_argument("--limite", type=int, default=30, help="(cep) quantas empresas consultar nesta rodada")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    url = settings.database_url()
    print(f"[geo] banco: {settings.nome_do_banco(url)}")
    engine = get_engine(url)
    with Session(engine) as s:
        if args.etapa == "municipio":
            etapa_municipio(s, args.dry_run)
        elif args.etapa == "cep":
            etapa_cep(s, args.limite, args.dry_run)
        elif args.etapa == "corrigir-cep-geral":
            corrigir_ceps_gerais(s, args.dry_run)
        else:
            relatorio(s)


if __name__ == "__main__":
    main()
