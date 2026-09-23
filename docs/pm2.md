# Rodar tudo em segundo plano com PM2

O `ecosystem.config.cjs` (na raiz) define 3 processos:

| Nome | O que roda | Log |
|---|---|---|
| `sales-api` | `uvicorn api.app:app` em 127.0.0.1:8000 (interface web + API) | `logs/api.out.log` / `api.err.log` |
| `sales-worker` | `python -m etapa7_whatsapp.worker` | `logs/worker.*.log` |
| `sales-gateway` | `node dist/src/index.js` (Baileys) em `services/whatsapp-gateway` | `logs/gateway.*.log` |

Os processos Python usam o interpretador de `.venv\Scripts\python.exe` **direto**: não precisa ativar o ambiente virtual.
O PM2 **não sobe nada sozinho ao ligar o computador** (não usamos `pm2 startup` nem `pm2 save`): você decide quando o sistema fica ativo.

## Instalar (uma vez)

```powershell
npm install -g pm2
pm2 -v        # deve mostrar a versão (testado com 7.0.4)
```

> **PowerShell:** se aparecer "a execução de scripts foi desabilitada" ao rodar `pm2`, use `pm2.cmd` no lugar (ex.: `pm2.cmd status`)
> ou libere para o seu usuário: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. No Git Bash `pm2` funciona direto.

## Primeira execução

1. Feche os terminais do **worker** e do **gateway** (Ctrl+C) e pare a API que estiver rodando na porta 8000
   (terminal do `uvicorn`, ou, se ela foi iniciada em segundo plano por fora do PM2):
   `Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess -Force`
2. Confira que o gateway está compilado: `cd services\whatsapp-gateway; npm run build; cd ..\..`
3. Na raiz do projeto: `pm2 start ecosystem.config.cjs`

## Comandos do dia a dia (raiz do projeto)

| Para... | Comando |
|---|---|
| **Subir os 3** | `pm2 start ecosystem.config.cjs` |
| **Ver o status dos 3** (online / stopped / errored, reinícios, memória) | `pm2 status` |
| **Ver os logs de todos juntos** (ao vivo, Ctrl+C sai sem parar nada) | `pm2 logs` |
| Logs de um só | `pm2 logs sales-worker` (ou `sales-api`, `sales-gateway`) |
| Últimas linhas, sem ficar preso | `pm2 logs sales-worker --lines 100 --nostream` |
| **Reiniciar um** | `pm2 restart sales-worker` |
| Reiniciar todos | `pm2 restart all` |
| **Parar um** | `pm2 stop sales-gateway` |
| **Parar os 3** | `pm2 stop all` |
| Voltar a subir um parado | `pm2 start sales-gateway` |
| Painel no terminal (CPU/memória/logs) | `pm2 monit` |
| Esvaziar os arquivos de log | `pm2 flush` |
| Desligar tudo e o próprio PM2 (fim do expediente) | `pm2 delete all` e depois `pm2 kill` |

## Quando reiniciar cada um

- Mudou código Python da API ou do worker → `pm2 restart sales-api` / `pm2 restart sales-worker`.
- Mudou o front (`web/`): `cd web; npm run build` e depois `pm2 restart sales-api`.
- Mudou o gateway (`services/whatsapp-gateway/src`): `cd services\whatsapp-gateway; npm run build` e depois `pm2 restart sales-gateway`.
- Mudou o `.env`: reinicie o processo que usa a variável (`pm2 restart all` resolve).

## Se um processo cair

Reinício **automático** com espera crescente (1 s, 2 s, 4 s... até 15 s). Se ele morrer 10 vezes seguidas em menos de 15 s, o PM2 desiste e
mostra `errored` em `pm2 status`: leia `pm2 logs <nome> --lines 100 --nostream`, corrija e use `pm2 restart <nome>`.

**Gateway:** ao reiniciar, o "lease" do processo anterior pode levar até ~30 s para vencer (o PM2 no Windows encerra o processo sem dar
chance de liberá-lo). O gateway **espera até 45 s** em vez de falhar, então `pm2 restart sales-gateway` pode demorar meio minuto
para voltar a `Conexão: conectado`. Isso é normal. Envio em andamento no instante da queda vira "incerto" e nunca é reenviado sozinho.

## Observações

- O gateway conecta ao WhatsApp sozinho **só** se já houver sessão pareada (como antes). Sem sessão, aguarda o botão "Conectar".
- Logs ficam em `logs/` e crescem com o tempo; `pm2 flush` esvazia. (Opcional: `pm2 install pm2-logrotate`.)
- Só o `sales-api` usa a porta 8000. Nunca rode o worker ou o gateway duas vezes (um terminal antigo + PM2): o gateway tem trava e recusa a segunda cópia; o worker duplicado funciona, mas processaria as mesmas tarefas em paralelo.

## Tela "Sistema" (sem terminal)

Aba **Sistema** na interface: status dos 3 processos (atualiza sozinho), **Reiniciar** / **Iniciar** / **Parar** de cada um, **Parar tudo** e **Iniciar tudo**
(worker + gateway; a API fica no ar de propósito porque é ela que serve a tela), e os **logs** (saída e erros, 50 a 1000 linhas, atualização automática).

- **Reiniciar a própria API:** a resposta confirma *antes* do reinício; a tela mostra "Reiniciando a API…" e reconecta sozinha. A API não pode ser *parada* por
  ali (você perderia a tela); para isso use o terminal (`pm2 stop sales-api`).
- A tela chama o `pm2` do sistema (procura `PM2_BIN`, o PATH e `%APPDATA%\npm\pm2.cmd`). Sem PM2, ela explica como instalar.
- **Segurança:** esses botões executam comandos no sistema operacional. Só é aceitável porque o sistema é local, de um operador, em 127.0.0.1 e sem login
  (há comentários no código em `api/routers/sistema.py`, `api/services/sistema_service.py` e na tela). Se um dia for exposto além do localhost, esta tela
  precisa de proteção extra antes de qualquer outra coisa.
- Memória/CPU dos processos Python mostram o valor do *launcher* do venv (pequeno), não o do processo real: serve para saber que está vivo, não para medir consumo.

> **Windows:** o PM2 usa um canal (pipe) **global**, então só existe um daemon por máquina e `PM2_HOME` não isola nada enquanto ele estiver rodando. Não
> "teste" comandos do PM2 em outra pasta achando que não afetam seu sistema real.

## Atalho de duplo clique

`iniciar-sistema.bat` (na raiz do projeto) faz tudo em ordem:
1. abre o **Docker Desktop** se não estiver rodando (espera até ~2,5 min) e avisa se não ficar pronto;
2. inicia o container **`sales-engine-db`** e espera o Postgres responder;
3. sobe API, worker e gateway pelo PM2 **só se estiverem parados** (nunca reinicia o que já está no ar; pode rodar de novo à vontade);
4. espera a API responder e abre **http://127.0.0.1:8000** no navegador.

Se algo falhar, a janela fica aberta com a mensagem (e as últimas linhas do log da API). Para não abrir o navegador: `iniciar-sistema.bat -NaoAbrirNavegador`.
