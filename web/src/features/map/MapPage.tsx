import type L from "leaflet";
import { useMemo, useState } from "react";
import { useMapaLeads } from "../../api/hooks";
import type { Bbox, PontoMapa } from "../../api/types";
import { ActiveFilterChips, GlobalFilterBar } from "../../components/GlobalFilterBar";
import { ErroBox } from "../../components/states";
import { COR_COLUNA, COR_FAIXA, ROTULO_COLUNA, ROTULO_FAIXA } from "../../lib/cores";
import { paramsApi, useFiltros } from "../../lib/filtros";
import { localidade, titulo } from "../../lib/format";
import { corDoPonto, LeadMap, type ModoCor } from "./LeadMap";

function MapLegend({ modo }: { modo: ModoCor }) {
  const itens =
    modo === "estagio"
      ? (Object.keys(COR_COLUNA) as (keyof typeof COR_COLUNA)[]).map((k) => ({ cor: COR_COLUNA[k], rotulo: ROTULO_COLUNA[k] }))
      : (Object.keys(COR_FAIXA) as (keyof typeof COR_FAIXA)[]).map((k) => ({ cor: COR_FAIXA[k], rotulo: ROTULO_FAIXA[k] }));
  return (
    <div className="legenda" aria-label="Legenda do mapa">
      <ul>
        {itens.map((i) => (
          <li key={i.rotulo}>
            <span className="amostra" style={{ background: i.cor }} aria-hidden="true" /> {i.rotulo}
          </li>
        ))}
      </ul>
      <ul>
        <li><span className="amostra amostra-cep" aria-hidden="true" /> Posição aproximada pelo CEP</li>
        <li><span className="amostra amostra-mun" aria-hidden="true" /> Centro do município (não é o endereço)</li>
      </ul>
    </div>
  );
}

function MapColorModeControl({ modo, onChange }: { modo: ModoCor; onChange: (m: ModoCor) => void }) {
  return (
    <div role="group" aria-label="Colorir por" className="segmentado">
      <button className={modo === "estagio" ? "ativo" : ""} aria-pressed={modo === "estagio"} onClick={() => onChange("estagio")}>
        Cor por estágio
      </button>
      <button className={modo === "score" ? "ativo" : ""} aria-pressed={modo === "score"} onClick={() => onChange("score")}>
        Cor por score
      </button>
    </div>
  );
}

export function MapPage() {
  const { filtros, setLocal } = useFiltros();
  const params = paramsApi(filtros);
  const [modo, setModo] = useState<ModoCor>("estagio");
  const [bbox, setBbox] = useState<Bbox | null>(null);
  const [visivel, setVisivel] = useState<L.LatLngBounds | null>(null);
  const [selecionado, setSelecionado] = useState<number | null>(null);

  const { data, error, isFetching, refetch } = useMapaLeads(params, bbox);
  const pontos = useMemo(() => data?.itens ?? [], [data]);

  // lista lateral: só o que está na área visível agora (o mapa carrega com folga)
  const naArea = useMemo(
    () => (visivel ? pontos.filter((p) => visivel.contains([p.latitude, p.longitude])) : pontos),
    [pontos, visivel],
  );

  return (
    <>
      <GlobalFilterBar extras />
      <ActiveFilterChips />
      {error && <ErroBox erro={error} onTentar={() => refetch()} />}

      <div className="barra-mapa">
        <MapColorModeControl modo={modo} onChange={setModo} />
        {data && (
          <span className="muted" aria-live="polite">
            {data.com_coordenadas.toLocaleString("pt-BR")} no mapa · {data.por_precisao.estabelecimento.toLocaleString("pt-BR")} de estabelecimentos OSM · {data.por_precisao.cep.toLocaleString("pt-BR")} por CEP (aproximado) ·{" "}
            {data.por_precisao.municipio.toLocaleString("pt-BR")} no centro do município {isFetching ? "· atualizando…" : ""}
          </span>
        )}
      </div>

      {data && data.sem_coordenadas > 0 && (
        <p className="aviso-mapa" role="note">
          {data.sem_coordenadas.toLocaleString("pt-BR")} de {data.total_filtrado.toLocaleString("pt-BR")} empresas deste filtro{" "}
          <strong>não têm coordenadas</strong> e não aparecem no mapa.
        </p>
      )}
      {data?.excedeu_limite && (
        <p className="aviso" role="alert">
          Há {data.total_no_recorte.toLocaleString("pt-BR")} pontos nesta área (limite de {data.limite.toLocaleString("pt-BR")} por vez). Aproxime o
          mapa ou refine os filtros — nada foi omitido em silêncio, apenas não foi carregado.
        </p>
      )}
      <p className="muted nota-mapa">
        O mapa só exibe coordenadas já gravadas; abrir esta tela não faz nenhuma geocodificação. Pinos tracejados são o{" "}
        <strong>centro do município</strong> (várias empresas ficam empilhadas no mesmo ponto — aproxime para abrir o grupo).
      </p>

      <div className="mapa-layout">
        <div className="mapa-wrap">
          <LeadMap
            pontos={pontos}
            modo={modo}
            selecionadoId={selecionado}
            aoSelecionar={setSelecionado}
            aoAbrirDetalhes={(id) => setLocal("lead", id)}
            aoMudarVisivel={setVisivel}
            aoPedirRecorte={setBbox}
          />
          <MapLegend modo={modo} />
        </div>

        <aside className="mapa-lista" aria-label="Leads na área visível">
          <h3>Na área visível ({naArea.length.toLocaleString("pt-BR")})</h3>
          {naArea.length === 0 && <p className="muted">Nenhum lead com coordenadas nesta área e filtros.</p>}
          <ul>
            {naArea.slice(0, 100).map((p: PontoMapa) => (
              <li key={p.id}>
                <button
                  className={`item-mapa ${selecionado === p.id ? "sel" : ""}`}
                  aria-pressed={selecionado === p.id}
                  onClick={() => setSelecionado(p.id)}
                >
                  <span className="amostra" style={{ background: corDoPonto(p, modo) }} aria-hidden="true" />
                  <span>
                    <strong>{titulo(p.nome)}</strong>
                    <br />
                    <span className="muted">
                      {localidade(p.municipio, p.uf)} · {p.precisao === "estabelecimento" ? "estabelecimento OSM" : p.precisao === "cep" ? "CEP" : "centro do município"}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {naArea.length > 100 && <p className="muted">Mostrando 100 de {naArea.length}. Aproxime o mapa para ver os demais.</p>}
        </aside>
      </div>
    </>
  );
}
