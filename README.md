*[Read in English](README.en.md)*

# sales-engine

Pipeline de prospecção B2B ponta a ponta: descoberta de empresas por
segmento, enriquecimento e verificação de contato, qualificação por IA,
primeiro contato por e-mail com warm-up de reputação, e uma etapa de
WhatsApp assistida por IA (copiloto humano-no-loop ou automática,
conforme configuração) — tudo sobre um único banco Postgres, com API e
interface web para acompanhar o funil (lista, Kanban, mapa, métricas,
exportação).

Projeto pessoal de prospecção B2B, configurável por nicho
(`config/nichos.yaml`). A política comercial (pacotes, preços,
descontos) é definida em `etapa7_whatsapp/politica.py` — veja a seção
"Política comercial" mais abaixo.

## Arquitetura

```
Etapa 1 — Busca            CNPJ ativo por CNAE (Receita Federal via Apify)
Etapa 2 — Validação         Google Places (existe? telefone/endereço batem?) + scraping do site (email / form)
Etapa 3 — Scoring           Fit do lead por IA (DeepSeek), a partir do conteúdo do site e do nicho
Etapa 4 — E-mail            Geração do e-mail de primeiro contato por IA (DeepSeek)
Etapa 5 — Envio             SMTP com curva de warm-up por data (evita queimar reputação de domínio novo)
Etapa 6 — WhatsApp manual   Gera link wa.me para abertura manual (sem automação)
Etapa 7 — WhatsApp com IA   Copiloto (sugere, operador aprova e envia) ou automático (gateway envia), com política comercial versionada
```

```
                       CNPJ (nome + cidade + UF, via CNAE)
                                    │
                          Google Places Text Search
                                    │
                  telefone OU rua batem com a Receita?
                    │ sim                        │ não
           Google Place Details            descartado
             extrai "website"           (fica só telefone da Receita)
                    │
              tem website?
           │ sim              │ não
    scraper de contato   fica só o telefone
   (email / form)          verificado
```

A verificação contra os dados da Receita é obrigatória: parte dos
resultados do Google Places são falsos positivos (nome parecido,
endereço/telefone diferentes).

### Etapa 7 — WhatsApp

A etapa mais elaborada do pipeline. Três processos coordenados por um
único Postgres:

| Processo | O que faz |
|---|---|
| **API** (FastAPI) | autorização de números, política comercial, comandos, caixa de entrada (`/api/v1/whatsapp/*`) |
| **Worker** (Python) | ingere eventos, decide o escopo da conversa, chama o LLM (DeepSeek) e grava a saída |
| **Gateway** (Node + Baileys) | sessão do WhatsApp, eventos brutos, envio da fila de saída |

Pontos de design:

- **Modo copiloto por padrão**: o modelo só *sugere* uma resposta; um
  humano revisa, edita se quiser e envia manualmente pelo próprio
  WhatsApp. O modo automático (o gateway envia direto) é opt-in e por
  política, nunca hardcoded.
- **Preço nunca vem do modelo de linguagem.** O LLM escolhe pacote e
  itens; o valor final é sempre calculado por um módulo à parte, e
  qualquer preço que apareça no texto gerado é validado contra esse
  módulo antes de sair — se não bater, a resposta é descartada e a
  conversa escala para um humano.
- **Autorização explícita por número**: o sistema nunca inicia contato
  automatizado sem um operador autorizar aquele telefone; trocar o
  telefone do cadastro não herda autorização.
- **Guardrails de conteúdo**: horário comercial, limite de novos
  contatos por dia, limite de desconto, "já paguei" nunca vira
  confirmação de pagamento (não existe esse campo), aceite fica
  registrado mas contrato/pagamento seguem fora do sistema.
- **Kill switch** local (arquivo `PAUSA` em `services/whatsapp-gateway/`)
  interrompe o envio automatizado sem depender da API estar de pé.

Mais detalhes de operação em [`docs/whatsapp-etapa7.md`](docs/whatsapp-etapa7.md).

#### Política comercial

`etapa7_whatsapp/politica.py` define a política comercial — pacotes,
preços, regras de desconto e o cálculo do orçamento — seguindo a
interface documentada em
[`etapa7_whatsapp/politica.example.py`](etapa7_whatsapp/politica.example.py)
(assinaturas de função, o que cada uma deve fazer e garantir). Para
usar a etapa 7, copie o exemplo para `politica.py` e implemente a
política do seu negócio; o texto do prompt de atendimento segue o
mesmo modelo, em `etapa7_whatsapp/roteiro.py` (veja
`roteiro.example.py`). A etapa 7 é registrada na API quando esse
módulo está presente; o restante (leads, Kanban, mapa, métricas,
exportação) não depende dele.

## Interface web

Uma tela sobre o mesmo banco para acompanhar o funil: lista com filtros,
Kanban por estágio, mapa dos leads geolocalizados, métricas de conversão
por nicho/cidade e exportação (CSV/XLSX). Detalhes em
[`docs/web-interface.md`](docs/web-interface.md).

## Stack técnica

| Camada | Tecnologia |
|---|---|
| Linguagem principal | Python 3.11 |
| API | FastAPI |
| Banco | PostgreSQL + SQLAlchemy + Alembic (migrações) |
| Frontend | React + TypeScript + Vite |
| WhatsApp | Node.js + Baileys (biblioteca não-oficial de WhatsApp Web) |
| IA | DeepSeek (scoring, geração de e-mail, conversa de WhatsApp) |
| Descoberta de empresas | Apify (actor de scraping de CNPJ) |
| Verificação de local | Google Places API |
| Scraping de site | Playwright (fallback para sites JS-heavy) |
| Processos em produção | PM2 (API + worker + gateway) |
| Testes | pytest (unitário + integração + e2e com Playwright) |

## Rodando localmente

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env        # preencha as variáveis (veja a tabela abaixo)
alembic upgrade head
```

### Variáveis de ambiente (`.env`)

| Variável | Descrição |
|---|---|
| `DATABASE_URL` | Conexão Postgres |
| `APIFY_TOKEN` | Token da conta Apify (actor de CNPJ) |
| `GOOGLE_PLACES_API_KEY` | Places API (Text Search + Place Details) |
| `DEEPSEEK_API_KEY` | Scoring, e-mail e conversa de WhatsApp |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | Envio de e-mail (etapa 5) |
| `WARMUP_START_DATE` | Data do primeiro envio real; controla a curva de warm-up |
| `WHATSAPP_AUTH_KEY` | Chave que criptografa a sessão do WhatsApp no banco |
| `WHATSAPP_NOTIFICACAO_OPERADOR` | WhatsApp que recebe aviso de aceite comercial |

### Etapas 1–2 (descoberta e validação)

```bash
python main.py
```

1. Sincroniza os nichos definidos em `config/nichos.yaml`.
2. Busca empresas ativas por CNAE via Apify e insere as novas (dedupe
   por CNPJ). O plano gratuito da Apify limita a 100 itens por
   execução — para volumes maiores, `CnpjClient.buscar_por_cnae_paginado`
   pagina por UF.
3. Para cada empresa sem validação: Google Places + verificação, e se
   houver site confirmado, scraping de contato.

### Etapas 3–5 (scoring, e-mail, envio)

Executadas por seus próprios módulos, fora do `main.py`:

```bash
python -m etapa3_scoring.scoring
python -m etapa4_email.email_writer
python -m etapa5_envio.smtp_sender
```

### Etapa 6 — links de WhatsApp manuais

```bash
python -m etapa6_whatsapp.gerar_links --amostra 5
```

### Etapa 7 — WhatsApp com IA

```bash
# API
uvicorn api.app:app --host 127.0.0.1 --port 8000

# Worker
python -m etapa7_whatsapp.worker

# Gateway (uma vez: npm install)
cd services/whatsapp-gateway && npm install && npm run build && npm start
```

Ou os três de uma vez via PM2 — veja [`docs/pm2.md`](docs/pm2.md).

### Interface web

```bash
cd web && npm install && npm run build
uvicorn api.app:app --host 127.0.0.1 --port 8000
```

### Testes

```bash
pytest                 # unitário + integração (etapas 1–6, API de leads/kanban/mapa/métricas/exportação)
pytest tests/e2e        # ponta a ponta com Playwright (sobe a interface web)
```

## Estrutura

```
sales-engine/
├── config/
│   └── nichos.yaml          # dores, argumentos e tom por nicho
├── db/
│   └── models.py            # schema SQLAlchemy (Postgres)
├── migrations/               # Alembic
├── etapa1_busca/             # Apify (CNPJ por CNAE)
├── etapa2_validacao/         # Google Places + scraping de contato
├── etapa3_scoring/           # fit do lead via IA
├── etapa4_email/             # geração do e-mail de primeiro contato
├── etapa5_envio/             # SMTP com warm-up
├── etapa6_whatsapp/          # links wa.me manuais
├── etapa7_whatsapp/          # copiloto/automação de WhatsApp com IA
│   ├── politica.example.py  # interface da política comercial (implementada em politica.py)
│   └── roteiro.example.py   # interface do texto do prompt (implementada em roteiro.py)
├── services/whatsapp-gateway/  # gateway Node + Baileys
├── api/                       # FastAPI
├── web/                       # React + TypeScript
├── maintenance/               # scripts de manutenção (geolocalização, prospecção adicional)
└── main.py                    # orquestrador das etapas 1–2
```
