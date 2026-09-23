# Etapa 7 — WhatsApp (modo COPILOTO por padrão)

> **Modo atual: copiloto** (`modo_envio: "manual"`, padrão na política; ausente = manual). A IA gera a resposta com todo o contexto e as
> validações, mas **nada é enviado pelo sistema**: nem a resposta da IA, nem o "envio manual" da interface, nem o aviso de aceite ao operador.
> O Baileys serve **só para receber**. Você copia a sugestão, envia pelo app do WhatsApp e confirma na tela.
> O gateway também recusa enviar (garantia dupla): com `modo_envio` diferente de `"automatico"` ele cancela qualquer saída.
> Ativar o modo automático exige `confirmar_envio_automatico` na política.

## Fluxo do copiloto

1. Autorizar um número (por lead, atalho "Autorizar novo número" ou telefone manual) → a IA **sugere** o primeiro contato.
2. Aba WhatsApp → conversa: cartão **Resposta sugerida — aguardando envio manual** com **Copiar**, **Abrir no WhatsApp** (wa.me com o texto),
   **Enviei (texto exato)**, **Enviei outra versão** (registra o que você realmente mandou) e **Descartar**.
3. A IA só considera dito o que você confirmou. Se o cliente escrever antes, a sugestão fica *desatualizada* e uma nova é gerada com tudo.
4. Se você enviar pelo app e o texto for igual à sugestão, o Baileys (que recebe as mensagens do próprio aparelho) **reconcilia sozinho**.
5. Uma proposta só vira "enviada" quando você confirma o envio; o aceite do cliente é registrado na hora (ato dele).
6. Barra do topo: contador de primeiros contatos enviados hoje (lembrete, não bloqueia). Horário e limites da política valem só para envio automático.

# (Modo automático) WhatsApp automatizado (Baileys + DeepSeek)

Estado inicial seguro: **nada é conectado, nada é enviado e a IA não conversa**. A automação de venda só liga
quando VOCÊ altera `vendas_ativas` na política (com confirmação explícita) e conecta o número.

## Peças

| Processo | Onde | Faz |
|---|---|---|
| API | `uvicorn api.app:app ...` | autorização, política, comandos, caixa de entrada (`/api/v1/whatsapp/*`) |
| Worker | `python -m etapa7_whatsapp.worker` | ingere eventos, decide escopo, chama DeepSeek, grava a outbox |
| Gateway | `services/whatsapp-gateway` (Node + Baileys 7.0.0-rc14, versão fixa) | sessão, eventos brutos, envio da outbox |

Comunicação só pelo PostgreSQL (fila com `FOR UPDATE SKIP LOCKED`, lease, versões). Migração: `0007` (aditiva, 18 tabelas).

## Rodar (recomendado: PM2, um comando — veja `docs/pm2.md`)

`pm2 start ecosystem.config.cjs` sobe API + worker + gateway em segundo plano; `pm2 status` e `pm2 logs` mostram o estado e os logs.

## Rodar manualmente (3 terminais, a partir da raiz)

```bash
# 1) API (já existente)
source .venv/Scripts/activate && uvicorn api.app:app --host 127.0.0.1 --port 8000

# 2) Worker (sem `vendas_ativas`, nunca chama o DeepSeek)
source .venv/Scripts/activate && python -m etapa7_whatsapp.worker

# 3) Gateway (uma vez: npm install; WHATSAPP_AUTH_KEY já está no .env)
cd services/whatsapp-gateway && npm install && npm run build && npm start
```

O gateway só conecta sozinho se já houver sessão pareada. Sem sessão ele espera o botão **Conectar** (WhatsApp → Conexão).

## Primeiro uso, na ordem

1. Suba os três processos. Em **WhatsApp → Conexão** o gateway deve aparecer como "rodando".
2. Marque a caixa de ciência e clique **Conectar / gerar QR**; leia o QR com o aparelho dedicado.
   (Isso pareia um número real. O sistema nunca faz isso sozinho.)
3. Em um lead, botão **Autorizar e iniciar conversa** (por número). Sem autorização: nada sai e nada é respondido.
4. Com `vendas_ativas = false` (padrão) a conversa autorizada vai para atendimento **humano**: use a caixa de entrada para escrever manualmente.
   Esse é o "envio de teste" seguro.
5. Só depois de revisar os valores (política) e fazer um teste supervisionado: **Política comercial → vendas_ativas: true** (pede confirmação).

## Salvaguardas (todas testadas)

- Número não autorizado: mensagem gravada como *Fora do escopo automatizado*, **zero** chamadas ao DeepSeek, zero respostas.
- Autorização é por número exato; trocar o telefone do cadastro não herda nada. Receber mensagem nunca autoriza.
- Antes de gerar, ao gravar na outbox e imediatamente antes de enviar: autorização, supressão, pausa, versões (autorização, conversa, política), horário e limites.
- Kill switch (botão global): invalida o que está pendente e bloqueia o envio. O gateway repete o teste antes de cada envio; a parada local funciona **sem a API**: crie um arquivo chamado `PAUSA` em `services/whatsapp-gateway/`.
- Envio incerto (processo caiu no meio) **nunca** é reenviado automaticamente. Só falhas com certeza de "não saiu" (sem conexão) voltam para a fila.
- Pedido de parar / número errado → supressão permanente, sem resposta e sem chamar o modelo. Áudio/imagem → humano.
- Preço: o código calcula (`etapa7_whatsapp/politica.py`); o texto do modelo só pode citar valores do catálogo ou da proposta calculada. "Já paguei" nunca vira pagamento confirmado (não existe campo de pagamento). Aceite é registrado, contrato/pagamento seguem com você.
- Demanda fora do catálogo → registrada em **Política → Necessidades** e escalada.

## Limites iniciais (todos em `commercial_policies`, editáveis na interface)

Seg–sex 09h–18h (America/Sao_Paulo) · 10 novos contatos/dia · 3 min entre primeiros contatos · 6 saídas/min · 12 respostas/hora/conversa
· sem follow-up automático · DeepSeek: 500 chamadas e 2 M tokens por dia (estourou → pausa a automação).

## Aviso de aceite para o operador

Ao registrar um aceite o worker grava um aviso (template fixo, sem IA) em `whatsapp_operator_notifications` e o **gateway** o envia
para o número da variável `WHATSAPP_NOTIFICACAO_OPERADOR` (no `.env`, só dígitos com DDI, ex.: `5511999998888`; reinicie o gateway
depois de preencher). Fluxo separado dos leads: não exige autorização, não usa política nem kill switch e não conta nos limites de
saída (a tabela é outra). O destino vem só do ambiente do gateway. Falha no envio (gateway offline, sem destino) não afeta o aceite:
o aviso fica pendente e é reenviado (até 5 tentativas, espera crescente); a barra da aba WhatsApp mostra pendentes/falhas.
Só o arquivo `PAUSA` (parada local) bloqueia esses avisos.

## Ritmo de resposta

Só respostas da IA esperam antes de sair: leitura (2,5 s; 1 s no primeiro contato) + digitação a 40 caracteres/s, ±15%, piso 4 s, teto 25 s
(`atrasoDeDigitacaoMs` em `services/whatsapp-gateway/src/outbox.ts`). Durante a espera o gateway mostra "digitando..." (melhor esforço) e
repete todas as checagens de segurança ao final: kill switch ou revogação durante a espera cancelam o envio. Mensagens do operador saem na hora.
O prompt (`wa-v2`) pede variação natural de fraseado; temperatura 0,6.

## Limitações conhecidas

- Integração de pagamento/contrato e evento no funil do Kanban ao aceitar.
- Transcrição de áudio; alerta por e-mail (só painel).
- Retenção automática (180 dias conversas / 30 dias anexos): nada é apagado sozinho.
- Autenticação da API: segue o modelo local de um operador (127.0.0.1, sem login).
- A conexão com o WhatsApp real exige pareamento do aparelho; os testes automatizados usam transporte simulado.
