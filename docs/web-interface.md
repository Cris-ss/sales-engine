# Interface web do Sales Engine

Camada de leitura e operação comercial sobre o **mesmo Postgres e os mesmos models** do pipeline.
A interface **não executa etapas do pipeline nem envia emails**. WhatsApp é só um link `wa.me`
aberto manualmente.

```
Navegador (React + TS + Vite) ── /api/v1 ──> FastAPI ──> SQLAlchemy (db/models.py) ──> Postgres
```

## Como rodar (uso local, um operador, sem autenticação)

A API escuta somente em `127.0.0.1`. **Se algum dia for exposta em rede, é preciso adicionar autenticação antes.**

```bash
# 1) dependências (uma vez)
pip install -r requirements.txt
cd web && npm install && npm run build && cd ..

# 2) subir tudo em um processo só: API + interface na mesma origem
uvicorn api.app:app --host 127.0.0.1 --port 8000
# abra http://127.0.0.1:8000        (documentação da API: /api/docs)
```

Desenvolvimento do frontend com recarga automática: `uvicorn ...` em um terminal e `npm run dev`
em `web/` (o Vite encaminha `/api` para a porta 8000; abra http://127.0.0.1:5173).

## Testes

```bash
pytest tests/api          # API contra o banco de teste (sales_engine_test)
pytest tests/e2e          # navegador (Playwright/Chromium) — exige `npm run build` antes
pytest                    # tudo
```

Os testes **recusam rodar** em qualquer banco cujo nome não termine em `_test` (trava em `tests/conftest.py`).
Banco de teste: `sales_engine_test`, no mesmo container Postgres.

## Migrações (Alembic)

- Baseline `0001` é vazio e foi só **carimbado** (`alembic stamp 0001`) — o schema já existia.
- Daqui em diante: só migrações **aditivas**, validadas antes no banco de teste
  (`ALEMBIC_DATABASE_URL=.../sales_engine_test alembic upgrade head`) e depois aplicadas no real.
- Um banco novo/de teste é criado com `Base.metadata.create_all` e depois carimbado.

## Prospecção de novos leads e DuckDuckGo

A aba **Procurar leads** só cria um lote pendente; ela não executa consultas externas dentro do processo HTTP.
Escolha nicho, fonte, UF e limite. Para a fonte padrão **OpenStreetMap**, informe também cidade e raio; execute um lote no terminal:

```bash
python -m maintenance.prospeccao.worker
```

O worker usa OpenStreetMap/Nominatim/Overpass por padrão e processa **somente os IDs inseridos naquele lote**.
Leads OSM não exigem CNPJ: são deduplicados pelo identificador do objeto OSM e recebem sua posição de estabelecimento
no mapa. Caso o OSM já informe um site, o scraper o processa diretamente; caso contrário, consulta DuckDuckGo HTML
com `"nome" "cidade" site`, analisa no máximo cinco resultados e grava a evidência em `validacoes_site_ddg`.
Domínios de redes sociais, mapas e diretórios são descartados. Um domínio institucional sem evidência textual
suficiente fica como `ambiguo`, nunca como site confirmado.

**Apify** permanece uma alternativa explícita no seletor de fonte, para buscar CNPJs por CNAE. Os registros Receita
existentes continuam como estão; a migração apenas permite `cnpj` nulo para novos leads OpenStreetMap.

Essa trilha é aditiva: nenhuma linha já existente em `empresas` ou `validacoes` é atualizada, removida ou
reclassificada. Para novos leads com email ou formulário extraído, uma `validacoes` compatível também é criada para
que as etapas posteriores continuem funcionando; os campos de Google Places permanecem vazios.

O filtro **Status do site** diferencia `Histórico (sem DuckDuckGo)`, site encontrado, sem site nos cinco resultados,
ambíguo, erro e rate limit. “Sem site” significa apenas que a busca não encontrou domínio institucional confiável,
não uma prova de inexistência. O filtro **Início da atividade** usa `empresas.data_inicio_atividade`; ele é diferente
da data de entrada no banco.

## Regras de dados que a interface aplica

| Tema | Regra |
|---|---|
| Uma linha por empresa | Projeção única (`api/queries/lead_projection.py`): score/estágio vigentes por função de janela, contatos agregados; nada de join multiplicador. |
| Score vigente | `criado_em DESC, id DESC`. Ausente = "Sem score" (nunca 0). |
| Faixas de score | Sem score · Baixo (< 55) · **Neutro (= 55, sentinela)** · Médio (55–65) · Alto (≥ 65). Cortes em `api/dominio.py`. O 55 é o padrão conservador do prompt da etapa 3 (sem sinal específico), não "fit médio". |
| Estágio atual | Último `funil_status` (`criado_em DESC, id DESC`). **Sem histórico é derivado na leitura** (email realmente enviado ⇒ *contatada*; senão *encontrada*) e marcado como derivado; nada é gravado. |
| 8 estágios → 5 colunas | Novo=encontrada · Qualificado=qualificada · Contatado=contatada/respondeu/em_negociacao/proposta · Ganho=venda · Descartado=perdida. Arrastar grava o estágio canônico da coluna; soltar na mesma coluna não faz nada. |
| Funil é append-only | Cada mudança **acrescenta** uma linha; nenhuma linha existente é alterada. |
| Concorrência | O cliente envia o id do histórico que viu (`null` se não havia). Na transação a empresa é travada (`FOR UPDATE`), o histórico é relido e, se mudou, responde **409**. |
| Email | `data_envio` = envio real; `enviado_em` = geração do registro. "Enviado" = aceito pelo SMTP (não prova entrega/leitura/resposta). |
| WhatsApp | "Apto" = formato de celular (etapa6). **Nunca** significa WhatsApp verificado. Abrir o link não registra envio, não cria contato, não move o funil. |
| Email confirmado | Só conta se o canal está ativo (`tem_pelo_menos_um_canal`); as empresas retiradas do fluxo por site não confirmado não aparecem como "email confirmado". |
| Conversão | Empresas atualmente em `venda` ÷ empresas do grupo no universo filtrado (numerador e denominador sempre exibidos; grupo vazio = N/A). |
| Distribuição x trajetória | "Onde estão hoje" (estoque) e "já passaram por" (histórico real) são métricas separadas. |

### Convivência com o pipeline

Nenhuma etapa do pipeline grava em `funil_status` hoje. Se uma etapa futura passar a gravar
(ex.: etapa5 marcando *contatada*), ela **só pode acrescentar linhas**, nunca alterar as existentes.
A API só garante exclusão mútua entre escritas feitas por ela mesma; o controle otimista (409)
detecta mudanças de outros escritores na tentativa seguinte, mas não há bloqueio com eles.

## Exportação

`GET /api/v1/exportacoes/leads?formato=csv|xlsx` + os mesmos filtros da lista. Exporta **todos** os
resultados filtrados. CNPJ/CEP/telefones saem formatados como texto (zeros à esquerda preservados);
células que começariam com `= + - @` recebem apóstrofo (evita injeção de fórmula). CSV com `;` e
UTF-8 com BOM. XLSX com cabeçalho, filtro e primeira linha congelada. Não exporta erros internos.

## Mapa e geolocalização (abordagem híbrida)

O mapa **só lê** coordenadas já gravadas na tabela `empresa_geolocalizacoes` (migração `0002`, aditiva).
Abrir ou navegar no mapa **nunca** geocodifica nem chama API externa; o único tráfego externo é o
do navegador buscando os tiles do OpenStreetMap (com atribuição).

**Precisão é sempre explícita** (campo `precisao`, mostrado na legenda, no popup e no painel do lead):

| `precisao` | Significa | Fonte |
|---|---|---|
| `municipio` | Sede do município. **Não é o endereço da empresa** (várias ficam empilhadas no mesmo ponto). | Dataset público derivado do IBGE (`kelvins/municipios-brasileiros`) — coordenada da *sede*, não centroide do polígono. |
| `cep` | Ponto aproximado devolvido para o CEP; **não é o endereço exato**. | AwesomeAPI (gratuita, sem chave, sem SLA). |

Regras aplicadas:
- CEP terminado em `000` é "CEP geral do município": o ponto devolvido não ganha precisão (chegou a cair 6 km fora
  da sede). Essas empresas **ficam com a posição municipal** e não gastam chamada (`cep_status = ambigua`).
- Ponto de CEP a mais de 60 km da sede do município também é descartado como `ambigua`.
- Em cidades pequenas com CEP único o ponto do CEP pode coincidir com o centro da cidade; mesmo assim é rotulado `cep`.

Comandos de manutenção (fora das 6 etapas; retomáveis; o próprio banco é o cache):

```bash
python -m maintenance.geolocation.geocodificar municipio [--dry-run]   # todas as empresas, sede do município
python -m maintenance.geolocation.geocodificar cep --limite 30         # refina por CEP (comece pela amostra)
python -m maintenance.geolocation.geocodificar cep --limite 5000       # o restante
python -m maintenance.geolocation.geocodificar corrigir-cep-geral      # reverte CEP geral gravado por engano
python -m maintenance.geolocation.geocodificar relatorio
```

A API do mapa (`GET /api/v1/mapa/leads`) aceita os mesmos filtros da lista + `min_lat,min_lng,max_lat,max_lng`,
devolve no máximo 5.000 pontos por vez e, se houver mais, responde `excedeu_limite=true` **sem pontos** (nunca
trunca em silêncio). Sempre informa quantas empresas do filtro estão sem coordenadas. Não usa PostGIS: o clustering
no navegador basta para o volume atual.

Termos de uso a ter em mente: o dataset de municípios e a AwesomeAPI são de terceiros (verifique a licença/limites
antes de reutilizar em escala ou redistribuir); os tiles do OSM exigem atribuição e uso leve.
