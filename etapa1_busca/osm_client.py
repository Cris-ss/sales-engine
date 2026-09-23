"""Descoberta gratuita de estabelecimentos via Nominatim + Overpass/OSM."""

from __future__ import annotations

from dataclasses import dataclass

import re
import time
import unicodedata

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
HEADERS = {"User-Agent": "sales-engine/1.0 (local prospecting)"}

# Cada nicho usa tags OSM, não CNAE. Tags ausentes retornam lista vazia de modo seguro.
TAGS = {
    "contabilidade": [("office", "accountant")], "imobiliarias": [("office", "estate_agent")],
    "advocacia": [("office", "lawyer")],
    # saloes_beauty x barbearias_estetica compartilham as tags; a separação é feita pelo nome
    # (NOME_EXCLUIR de um = NOME_REGEX do outro), para o mesmo estabelecimento não cair nos dois.
    "saloes_beauty": [("shop", "beauty"), ("shop", "hairdresser")],
    "barbearias_estetica": [("shop", "hairdresser"), ("shop", "beauty"), ("shop", "massage"), ("leisure", "spa")],
    # Só construtoras/empreiteiras; ofícios (eletricista, encanador...) e shop=trade (material) ficaram de fora.
    "construtoras": [("office", "construction_company"), ("craft", "builder")],
    "oficinas_mecanicas": [("shop", "car_repair"), ("craft", "car_repair")],
    "odontologia": [("amenity", "dentist"), ("healthcare", "dentist")],
    "clinicas_medicas": [("amenity", "clinic"), ("healthcare", "clinic"), ("amenity", "doctors")],
    "psicologia": [("healthcare", "psychotherapist"), ("office", "therapist")],
    # Sem amenity=doctors: a tag inclui qualquer consultório médico.
    # healthcare=nutrition quase não existe no OSM BR; o resultado real vem do fallback textual.
    "nutricao": [("healthcare", "nutrition")],
    "fisioterapia": [("healthcare", "physiotherapist")],
    "academias": [("leisure", "fitness_centre"), ("leisure", "sports_centre")],
    "petshops_veterinaria": [("amenity", "veterinary"), ("shop", "pet")],
    "restaurantes": [("amenity", "restaurant")], "lanchonetes": [("amenity", "fast_food")], "padarias": [("shop", "bakery")],
}
# Filtro por nome (aplicado sobre o nome SEM acento e em minúsculas).
# NOME_REGEX: o nome precisa casar. NOME_EXCLUIR: o nome não pode casar.
# Sempre vale no fallback textual (Nominatim, que não tem tag). Nos resultados por tag só vale para
# os nichos de FILTRO_EM_TAGS, onde a tag é ampla demais para identificar o nicho sozinha.
# Nichos de tag específica (contabilidade, advocacia, oficinas, ...) confiam na tag: filtrar por nome
# descartaria negócios legítimos com nome próprio (ex.: "Silva & Associados").
_SEM_SPA = r"barbe|barber|estetic|\bspa\b|massag|depil|micropigment|podolog|cosmetolog|laser"
NOME_REGEX = {
    "advocacia": r"advog|advoc|juridic|direito|\boab\b",
    "odontologia": r"odont|dent|sorri|implant",
    "fisioterapia": r"fisio|reabilit|pilates|\brpg\b|quiropra|osteopat",
    "nutricao": r"nutri|dietist|dietetic|nutrolog",
    "psicologia": r"psic|terapeut|terapia|psicanal|comportamental",
    "clinicas_medicas": (
        r"clinic|medic|consultorio|derma|plastic|ortho|\borto|hemo|cardio|uro|pediatr|ortoped|ginecolog|obstet|dermat|oftalm|otorrino|urolog|gastro"
        r"|neurolog|endocrin|reumat|oncolog|pneumo|proctolog|alergi|geriatr|mastolog|angiolog|vascular|psiquiatr"
        r"|\bdr\b|\bdra\b|doutor|doutora"
    ),
    "academias": (
        r"academia|fitness|\bfit\b|gym|crossfit|muscula|treino|training|funcional|pilates|spinning|ginastica|studio"
        r"|smart ?fit|bluefit|selfit|bio ?ritmo|body ?tech|curves|athletica|club ?4|4move|malhart"
    ),
    "barbearias_estetica": _SEM_SPA + r"|sobrancelh|bronze",
}
NOME_EXCLUIR = {
    "clinicas_medicas": r"psicolog|psicoterap|fisioter|nutri|odont|dentis|veterin|laborat|\bubs\b|centro de saude|unidade (basica )?de saude|estetic",
    "psicologia": r"fisioter|massoter|massag|quiropra",
    "academias": r"quadra|ginasio|campo|arena|society|futebol|futsal|tenis|padel|beach|clube|estadio|escola|colegio|prefeitura|associacao|\bsesc\b|\bsesi\b",
    "saloes_beauty": _SEM_SPA,
}
FILTRO_EM_TAGS = {
    "clinicas_medicas", "psicologia", "nutricao", "academias",
    "barbearias_estetica", "saloes_beauty",
}


def _sem_acento(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in base if not unicodedata.combining(c)).lower()


def chave_local(nome: str, lat: float, lon: float) -> tuple[str, float, float]:
    """Mesmo estabelecimento mapeado como nó e como polígono:
    nome normalizado + coordenadas com 4 casas (~11 m). Filiais em endereços diferentes não colidem."""
    return _sem_acento(nome).strip(), round(float(lat), 4), round(float(lon), 4)


def passa_filtro_nome(nicho_slug: str | None, nome: str) -> bool:
    texto = _sem_acento(nome)
    incluir, excluir = NOME_REGEX.get(nicho_slug or ""), NOME_EXCLUIR.get(nicho_slug or "")
    if incluir and not re.search(incluir, texto):
        return False
    return not (excluir and re.search(excluir, texto))


TERMOS_BUSCA = {
    "advocacia": "advogado", "psicologia": "psicólogo", "nutricao": "nutricionista",
    "fisioterapia": "fisioterapeuta", "odontologia": "dentista", "clinicas_medicas": "clínica médica",
}


@dataclass
class EmpresaOsm:
    externo_id: str
    nome: str
    municipio: str | None
    uf: str | None
    logradouro: str | None
    numero: str | None
    bairro: str | None
    cep: str | None
    telefone: str | None
    website: str | None
    latitude: float
    longitude: float


@dataclass
class CidadeOsm:
    nome: str
    uf: str
    rotulo: str
    latitude: float
    longitude: float


class OsmClient:
    @staticmethod
    def _sigla_uf(endereco: dict) -> str | None:
        iso = endereco.get("ISO3166-2-lvl4") or endereco.get("ISO3166-2-lvl3") or ""
        sigla = iso.rsplit("-", 1)[-1].upper()
        return sigla if len(sigla) == 2 else None

    def buscar_cidades(self, termo: str, limite: int = 8) -> list[CidadeOsm]:
        with httpx.Client(headers=HEADERS, timeout=httpx.Timeout(15.0, connect=8.0)) as client:
            resposta = client.get(NOMINATIM_URL, params={
                "q": termo, "format": "jsonv2", "countrycodes": "br", "addressdetails": 1,
                "limit": limite, "dedupe": 1,
            })
            resposta.raise_for_status()
        cidades: list[CidadeOsm] = []
        vistos: set[tuple[str, str]] = set()
        for item in resposta.json():
            endereco = item.get("address") or {}
            nome = endereco.get("city") or endereco.get("town") or endereco.get("municipality") or endereco.get("village")
            uf = self._sigla_uf(endereco)
            if not nome or not uf or (nome.casefold(), uf) in vistos:
                continue
            vistos.add((nome.casefold(), uf))
            cidades.append(CidadeOsm(nome, uf, f"{nome}, {uf}", float(item["lat"]), float(item["lon"])))
        return cidades

    @staticmethod
    def _converter_nominatim(
        itens: list[dict], cidade: str, uf: str, limite: int, nicho_slug: str | None = None, filtrar_nome: bool = True
    ) -> list[EmpresaOsm]:
        empresas: list[EmpresaOsm] = []
        locais: set[tuple[str, float, float]] = set()
        for item in itens:
            if len(empresas) >= limite:
                break
            nome = (item.get("name") or item.get("display_name", "").split(",", 1)[0]).strip()
            if not nome or not item.get("osm_id"):
                continue
            if filtrar_nome and not passa_filtro_nome(nicho_slug, nome):
                continue
            local = chave_local(nome, item["lat"], item["lon"])
            if local in locais:
                continue
            locais.add(local)
            endereco = item.get("address") or {}
            extras = item.get("extratags") or {}
            empresas.append(EmpresaOsm(
                externo_id=f"{item.get('osm_type', 'node')}/{item['osm_id']}", nome=nome,
                municipio=endereco.get("city") or endereco.get("town") or endereco.get("municipality") or cidade,
                uf=(endereco.get("ISO3166-2-lvl4") or "").split("-")[-1] or uf,
                logradouro=endereco.get("road"), numero=endereco.get("house_number"),
                bairro=endereco.get("suburb") or endereco.get("neighbourhood"), cep=endereco.get("postcode"),
                telefone=extras.get("contact:phone") or extras.get("phone"),
                website=extras.get("contact:website") or extras.get("website"),
                latitude=float(item["lat"]), longitude=float(item["lon"]),
            ))
        return empresas

    def _buscar_textual(
        self, client: httpx.Client, nicho_slug: str, cidade: str, uf: str, limite: int, filtrar_nome: bool = True
    ) -> list[EmpresaOsm]:
        termo = TERMOS_BUSCA.get(nicho_slug)
        if not termo:
            return []
        resposta = client.get(NOMINATIM_URL, params={
            "q": f"{termo}, {cidade}, {uf}, Brasil", "format": "jsonv2", "limit": min(limite, 50),
            "addressdetails": 1, "extratags": 1,
        })
        resposta.raise_for_status()
        return self._converter_nominatim(resposta.json(), cidade, uf, limite, nicho_slug, filtrar_nome)

    def buscar(
        self, nicho_slug: str, cidade: str, uf: str, raio_km: int, limite: int, filtrar_nome: bool = True
    ) -> list[EmpresaOsm]:
        """`filtrar_nome=False` existe só para simulações (dry-run); o fluxo real usa sempre o filtro."""
        tags = TAGS.get(nicho_slug)
        if not tags:
            raise ValueError(f"Nicho {nicho_slug!r} ainda não possui tags OSM configuradas")
        with httpx.Client(headers=HEADERS, timeout=httpx.Timeout(45.0, connect=10.0)) as client:
            geo = client.get(NOMINATIM_URL, params={"q": f"{cidade}, {uf}, Brasil", "format": "jsonv2", "limit": 1})
            geo.raise_for_status()
            locais = geo.json()
            if not locais:
                raise ValueError(f"Cidade não encontrada no OSM: {cidade}/{uf}")
            lat, lon = float(locais[0]["lat"]), float(locais[0]["lon"])
            clausulas = "".join(f'nw["{k}"="{v}"](around:{raio_km * 1000},{lat},{lon});' for k, v in tags)
            query = f"[out:json][timeout:{40 if raio_km > 15 else 25}];({clausulas});out center {200 if raio_km > 15 else 150};"
            ultimo_erro: Exception | None = None
            resposta = None
            for url in OVERPASS_URLS:
                try:
                    tentativa = client.post(url, data={"data": query})
                    if tentativa.status_code < 500:
                        tentativa.raise_for_status()
                        resposta = tentativa
                        break
                    ultimo_erro = httpx.HTTPStatusError(
                        f"Overpass retornou HTTP {tentativa.status_code}", request=tentativa.request, response=tentativa
                    )
                except httpx.HTTPError as exc:
                    ultimo_erro = exc
                time.sleep(1)
            if resposta is None:
                fallback = self._buscar_textual(client, nicho_slug, cidade, uf, limite, filtrar_nome)
                if fallback:
                    return fallback
                raise RuntimeError(f"Nenhum servidor Overpass respondeu: {ultimo_erro}")
        vistos: set[str] = set()
        locais: set[tuple[str, float, float]] = set()
        empresas: list[EmpresaOsm] = []
        conteudo = resposta.json()
        if "runtime error" in (conteudo.get("remark") or "").lower():
            raise RuntimeError(f"Overpass runtime error: {conteudo['remark']}")
        for item in conteudo.get("elements", []):
            dados = item.get("tags", {})
            nome = (dados.get("name") or "").strip()
            if not nome:
                continue
            externo_id = f"{item['type']}/{item['id']}"
            if externo_id in vistos:
                continue
            vistos.add(externo_id)
            if filtrar_nome and nicho_slug in FILTRO_EM_TAGS and not passa_filtro_nome(nicho_slug, nome):
                continue
            centro = item.get("center", item)
            if "lat" not in centro or "lon" not in centro:
                continue
            local = chave_local(nome, centro["lat"], centro["lon"])
            if local in locais:
                continue
            locais.add(local)
            empresas.append(EmpresaOsm(
                externo_id=externo_id, nome=nome, municipio=dados.get("addr:city") or cidade,
                uf=(dados.get("addr:state") if len(dados.get("addr:state", "")) == 2 else uf),
                logradouro=dados.get("addr:street"), numero=dados.get("addr:housenumber"),
                bairro=dados.get("addr:suburb"), cep=dados.get("addr:postcode"),
                telefone=dados.get("contact:phone") or dados.get("phone"),
                website=dados.get("contact:website") or dados.get("website"),
                latitude=float(centro["lat"]), longitude=float(centro["lon"]),
            ))
            if len(empresas) >= limite:
                break
        if not empresas:
            with httpx.Client(headers=HEADERS, timeout=httpx.Timeout(30.0, connect=10.0)) as client:
                return self._buscar_textual(client, nicho_slug, cidade, uf, limite, filtrar_nome)
        return empresas
