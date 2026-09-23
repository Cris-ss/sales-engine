export type Faixa = "sem_score" | "baixo" | "neutro" | "medio" | "alto";
export type Coluna = "novo" | "qualificado" | "contatado" | "ganho" | "descartado";
export type EmailStatus = "enviado" | "pendente" | "falhou" | "nenhum";

export interface Pagina<T> {
  itens: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface LeadResumo {
  id: number;
  cnpj: string | null;
  nome: string;
  nicho_id: number;
  nicho_slug: string;
  nicho_nome: string;
  municipio: string | null;
  uf: string | null;
  consulta_busca: string;
  fonte: string | null;
  score: number | null;
  faixa_score: Faixa;
  estagio: string;
  estagio_derivado: boolean;
  coluna: Coluna;
  funil_id: number | null;
  email_confirmado: boolean;
  formulario_confirmado: boolean;
  whatsapp_apto: boolean;
  telefone: string | null;
  site_url: string | null;
  site_ddg_status: string;
  motivo_reprovacao: string | null;
  email_status: EmailStatus;
  qtd_emails_enviados: number;
  email_enviado_em: string | null;
  tem_localizacao: boolean;
  precisao_geo: "municipio" | "cep" | null;
}

export interface Localizacao {
  latitude: number;
  longitude: number;
  precisao: string;
  fonte: string;
}

export interface LeadDetalhe extends LeadResumo {
  razao_social: string | null;
  nome_fantasia: string | null;
  logradouro: string | null;
  numero: string | null;
  complemento: string | null;
  bairro: string | null;
  cep: string | null;
  telefone1: string | null;
  telefone2: string | null;
  porte: string | null;
  natureza_juridica: string | null;
  cnae_principal: string | null;
  data_inicio_atividade: string | null;
  criado_em: string | null;
  email_final: string | null;
  formulario_contato_url: string | null;
  site_ativo: boolean | null;
  places_verificado: boolean | null;
  places_telefone_confirmado: boolean | null;
  places_endereco_confirmado: boolean | null;
  tem_pelo_menos_um_canal: boolean | null;
  score_em: string | null;
  modelo_usado: string | null;
  prompt_versao: string | null;
  dores_identificadas: string | null;
  justificativa: string | null;
  localizacao: Localizacao | null;
}

export interface ScoreItem {
  id: number;
  score: number;
  faixa_score: Faixa;
  modelo_usado: string;
  prompt_versao: string;
  dores_identificadas: string | null;
  justificativa: string | null;
  criado_em: string | null;
}

export interface ContatoItem {
  id: number;
  canal: string;
  destino: string;
  assunto: string | null;
  corpo: string | null;
  status: string;
  status_envio: string;
  sucesso_envio: boolean | null;
  erro: string | null;
  gerado_em: string | null;
  enviado_em: string | null;
}

export interface FunilItem {
  id: number;
  estagio: string;
  coluna: Coluna;
  observacao: string | null;
  criado_em: string | null;
}

export interface WhatsAppLink {
  apto: boolean;
  verificado: boolean;
  telefone_original: string | null;
  telefone_normalizado: string | null;
  tipo_telefone: string;
  nono_digito_acrescentado: boolean;
  motivo_inapto: string | null;
  mensagem: string | null;
  link: string | null;
}

export interface Opcao {
  codigo: string;
  rotulo: string;
  total?: number;
}

export interface OpcoesFiltros {
  ufs: Opcao[];
  municipios: { municipio: string; uf: string; total: number }[];
  empresas_sem_municipio: number;
  faixas: Opcao[];
  cortes_score: { neutro: number; alto_min: number };
  canais: Opcao[];
  colunas: { codigo: Coluna; rotulo: string; estagios: string[]; estagio_canonico: string }[];
  estagios: { codigo: string; rotulo: string; coluna: Coluna }[];
  email_status: Opcao[];
  site_ddg: Opcao[];
  page_size_max: number;
}

export interface Nicho {
  id: number;
  slug: string;
  nome: string;
  total: number;
}

export interface KanbanResumo {
  colunas: { codigo: Coluna; rotulo: string; total: number; por_estagio: Record<string, number> }[];
  total: number;
}

export interface TransicaoResposta {
  funil_id: number;
  lead: LeadResumo;
}

export interface MetricasResumo {
  total_empresas: number;
  com_email_confirmado: number;
  com_formulario: number;
  com_telefone_apto: number;
  com_score: number;
  empresas_com_email_enviado: number;
  mensagens_email_enviadas: number;
  em_ganho_atual: number;
  por_estagio: { estagio: string; rotulo: string; coluna: Coluna; total: number }[];
  por_nicho_e_coluna: { nicho_slug: string; nicho_nome: string; colunas: Record<Coluna, number> }[];
  definicoes: Record<string, string>;
}

export interface MetricasFunil {
  total_empresas: number;
  atual: { estagio: string; rotulo: string; total: number }[];
  atual_por_coluna: { coluna: Coluna; rotulo: string; total: number }[];
  historico_passagem: { estagio: string; rotulo: string; empresas_distintas: number }[];
  definicoes: Record<string, string>;
}

export interface ConversaoItem {
  chave: string;
  rotulo: string;
  municipio: string | null;
  uf: string | null;
  sem_dado: boolean;
  empresas: number;
  ganhos: number;
  taxa_pct: number | null;
}

export interface Conversao {
  nivel: "nicho" | "cidade";
  itens: ConversaoItem[];
  total_grupos: number;
  truncado: boolean;
  definicao: string;
}

export interface PontoMapa {
  id: number;
  nome: string;
  latitude: number;
  longitude: number;
  precisao: "municipio" | "cep" | "estabelecimento";
  score: number | null;
  faixa_score: Faixa;
  coluna: Coluna;
  estagio: string;
  nicho_slug: string;
  municipio: string | null;
  uf: string | null;
}

export interface RespostaMapa {
  itens: PontoMapa[];
  total_no_recorte: number;
  excedeu_limite: boolean;
  limite: number;
  total_filtrado: number;
  com_coordenadas: number;
  sem_coordenadas: number;
  por_precisao: { municipio: number; cep: number; estabelecimento: number };
  legenda_precisao: { municipio: string; cep: string; estabelecimento: string };
}

export interface Bbox {
  min_lat: number;
  min_lng: number;
  max_lat: number;
  max_lng: number;
}

export interface LoteProspeccao {
  id: number;
  nicho_id: number;
  uf: string;
  fonte: "osm" | "apify" | "google_places"; // google_places só em lotes históricos; não criável
  cidade: string | null;
  raio_km: number | null;
  limite: number;
  total_encontrado: number;
  total_duplicado: number;
  status: string;
  erro: string | null;
  criado_em: string | null;
  iniciado_em: string | null;
  concluido_em: string | null;
  empresas_novas: number;
  validacoes_concluidas: number;
}

export interface CidadeSugestao {
  nome: string;
  uf: string;
  rotulo: string;
  latitude: number;
  longitude: number;
}
