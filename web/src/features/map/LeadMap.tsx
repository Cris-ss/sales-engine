import L from "leaflet";
import "leaflet.markercluster";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";
import { useEffect, useRef } from "react";
import { MapContainer, TileLayer, useMap, useMapEvents } from "react-leaflet";
import type { Bbox, PontoMapa } from "../../api/types";
import { COR_COLUNA, COR_FAIXA, ROTULO_COLUNA, ROTULO_FAIXA } from "../../lib/cores";
import { localidade, titulo } from "../../lib/format";

export type ModoCor = "estagio" | "score";

export function corDoPonto(p: PontoMapa, modo: ModoCor): string {
  return modo === "estagio" ? COR_COLUNA[p.coluna] : COR_FAIXA[p.faixa_score];
}

/** Município = borda tracejada e miolo quase vazio (posição do CENTRO da cidade); CEP = pino cheio. */
function estilo(p: PontoMapa, modo: ModoCor, selecionado: boolean): L.CircleMarkerOptions {
  const cor = corDoPonto(p, modo);
  const cep = p.precisao === "cep";
  const estabelecimento = p.precisao === "estabelecimento";
  return {
    radius: selecionado ? 11 : 8,
    color: selecionado ? "#111" : cep ? "#ffffff" : cor,
    weight: selecionado ? 3 : 2,
    dashArray: estabelecimento || cep ? undefined : "3 3",
    fillColor: cor,
    fillOpacity: estabelecimento || cep ? 0.92 : 0.3,
  };
}

function criarPopup(p: PontoMapa, aoAbrirDetalhes: (id: number) => void): HTMLElement {
  // DOM + textContent (nunca innerHTML com dado do banco).
  const raiz = document.createElement("div");
  raiz.className = "popup-lead";
  const linha = (texto: string, forte = false) => {
    const el = document.createElement(forte ? "strong" : "div");
    el.textContent = texto;
    raiz.appendChild(el);
    return el;
  };
  linha(titulo(p.nome), true);
  linha(localidade(p.municipio, p.uf));
  linha(p.score === null ? ROTULO_FAIXA.sem_score : `Score ${Math.round(p.score)} — ${ROTULO_FAIXA[p.faixa_score]}`);
  linha(`Coluna: ${ROTULO_COLUNA[p.coluna]} (${p.estagio.replace("_", " ")})`);
  const prec = linha(
    p.precisao === "estabelecimento"
      ? "Posição cadastrada no OpenStreetMap para o estabelecimento."
      : p.precisao === "cep"
      ? "Posição aproximada pelo CEP (não é o endereço exato)."
      : "Centro do município — NÃO é o endereço da empresa.",
  );
  prec.className = "popup-precisao";
  const b = document.createElement("button");
  b.className = "btn btn-pequeno";
  b.textContent = "Ver detalhes";
  b.onclick = () => aoAbrirDetalhes(p.id);
  raiz.appendChild(b);
  return raiz;
}

/** Camada de pinos com clustering. Atualiza por diferença (não recria tudo), para não fechar o popup aberto. */
function CamadaPinos(props: {
  pontos: PontoMapa[];
  modo: ModoCor;
  selecionadoId: number | null;
  aoSelecionar: (id: number) => void;
  aoAbrirDetalhes: (id: number) => void;
}) {
  const map = useMap();
  const grupo = useRef<L.MarkerClusterGroup | null>(null);
  const marcadores = useRef(new Map<number, { m: L.CircleMarker; p: PontoMapa }>());
  const cb = useRef(props);
  cb.current = props;

  useEffect(() => {
    const g = L.markerClusterGroup({ chunkedLoading: true, showCoverageOnHover: false, maxClusterRadius: 45 });
    map.addLayer(g);
    grupo.current = g;
    return () => {
      map.removeLayer(g);
      grupo.current = null;
      marcadores.current.clear();
    };
  }, [map]);

  // adiciona/remove/atualiza por diferença
  useEffect(() => {
    const g = grupo.current;
    if (!g) return;
    const novos = new Map(props.pontos.map((p) => [p.id, p]));
    for (const [id, { m }] of marcadores.current) {
      if (!novos.has(id)) {
        g.removeLayer(m);
        marcadores.current.delete(id);
      }
    }
    const adicionar: L.CircleMarker[] = [];
    for (const p of props.pontos) {
      const existente = marcadores.current.get(p.id);
      if (existente) {
        existente.p = p;
        existente.m.setStyle(estilo(p, props.modo, p.id === props.selecionadoId));
      } else {
        const m = L.circleMarker([p.latitude, p.longitude], estilo(p, props.modo, false));
        const reg = { m, p };
        m.bindPopup(() => criarPopup(reg.p, (id) => cb.current.aoAbrirDetalhes(id)), { minWidth: 230 });
        m.on("click", () => cb.current.aoSelecionar(p.id));
        marcadores.current.set(p.id, reg);
        adicionar.push(m);
      }
    }
    if (adicionar.length) g.addLayers(adicionar);
  }, [props.pontos, props.modo, props.selecionadoId]);

  // seleção vinda da lista lateral: aproxima e abre o popup
  useEffect(() => {
    if (props.selecionadoId === null) return;
    const reg = marcadores.current.get(props.selecionadoId);
    const g = grupo.current;
    if (reg && g) g.zoomToShowLayer(reg.m, () => reg.m.openPopup());
  }, [props.selecionadoId]);

  return null;
}

/**
 * Observa a área visível. Só pede dados novos quando a área sai do que já foi carregado
 * (carrega com folga de 50% em cada lado): navegar dentro da área não dispara requisições.
 */
function VigiaDeArea(props: { aoMudarVisivel: (b: L.LatLngBounds) => void; aoPedirRecorte: (b: Bbox) => void }) {
  const carregado = useRef<L.LatLngBounds | null>(null);
  const map = useMapEvents({
    moveend: () => avaliar(),
    zoomend: () => avaliar(),
  });

  function avaliar() {
    const visivel = map.getBounds();
    props.aoMudarVisivel(visivel);
    if (carregado.current && carregado.current.contains(visivel)) return;
    const folga = visivel.pad(0.5);
    carregado.current = folga;
    // clamp: em zoom baixo a folga pode passar de ±90/±180 e a API recusaria (422)
    const lim = (v: number, max: number) => Number(Math.max(-max, Math.min(max, v)).toFixed(4));
    props.aoPedirRecorte({
      min_lat: lim(folga.getSouth(), 90),
      min_lng: lim(folga.getWest(), 180),
      max_lat: lim(folga.getNorth(), 90),
      max_lng: lim(folga.getEast(), 180),
    });
  }

  useEffect(() => {
    avaliar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
}

export function LeadMap(props: {
  pontos: PontoMapa[];
  modo: ModoCor;
  selecionadoId: number | null;
  aoSelecionar: (id: number) => void;
  aoAbrirDetalhes: (id: number) => void;
  aoMudarVisivel: (b: L.LatLngBounds) => void;
  aoPedirRecorte: (b: Bbox) => void;
}) {
  return (
    <MapContainer center={[-14.2, -51.9]} zoom={4} minZoom={3} className="mapa" scrollWheelZoom>
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        maxZoom={19}
      />
      <VigiaDeArea aoMudarVisivel={props.aoMudarVisivel} aoPedirRecorte={props.aoPedirRecorte} />
      <CamadaPinos
        pontos={props.pontos}
        modo={props.modo}
        selecionadoId={props.selecionadoId}
        aoSelecionar={props.aoSelecionar}
        aoAbrirDetalhes={props.aoAbrirDetalhes}
      />
    </MapContainer>
  );
}
