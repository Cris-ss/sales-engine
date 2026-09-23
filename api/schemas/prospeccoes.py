from datetime import datetime

from pydantic import BaseModel, Field, field_validator


UFS_BRASIL = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
    "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}


class CriarLoteProspeccao(BaseModel):
    nicho_id: int
    uf: str = Field(min_length=2, max_length=2)
    fonte: str = Field(default="osm", pattern="^(osm|apify|google_places)$")
    cidade: str | None = Field(default=None, max_length=120)
    raio_km: int | None = Field(default=None, ge=1, le=50)
    limite: int = Field(ge=1, le=500)
    confirmar: bool = False

    @field_validator("uf")
    @classmethod
    def validar_uf(cls, valor: str) -> str:
        uf = valor.strip().upper()
        if uf not in UFS_BRASIL:
            raise ValueError("Informe uma UF brasileira válida")
        return uf


class LoteProspeccaoResposta(BaseModel):
    id: int
    nicho_id: int
    uf: str
    fonte: str
    cidade: str | None = None
    raio_km: int | None = None
    limite: int
    total_encontrado: int = 0
    total_duplicado: int = 0
    status: str
    erro: str | None = None
    criado_em: datetime | None = None
    iniciado_em: datetime | None = None
    concluido_em: datetime | None = None
    empresas_novas: int = 0
    validacoes_concluidas: int = 0


class CidadeSugestao(BaseModel):
    nome: str
    uf: str
    rotulo: str
    latitude: float
    longitude: float
