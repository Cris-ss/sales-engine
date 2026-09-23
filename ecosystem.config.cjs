/**
 * PM2: sobe API + worker + gateway com um comando (`pm2 start ecosystem.config.cjs`). Veja docs/pm2.md.
 *
 * - Python: usa o interpretador do .venv DIRETO (não precisa ativar o ambiente virtual).
 * - Reinício automático SÓ em caso de crash. Nada sobe sozinho ao ligar o computador (não usamos `pm2 startup`/`pm2 save`).
 * - Logs em ./logs (um arquivo por processo). `pm2 logs` mostra todos.
 */
const path = require("path");

const RAIZ = __dirname;
const PYTHON = path.join(RAIZ, ".venv", "Scripts", "python.exe");
const LOGS = path.join(RAIZ, "logs");
const PORTA_API = process.env.SALES_API_PORT || "8000"; // só o teste de infraestrutura muda isto

// Política de reinício: cai -> sobe de novo com espera crescente (1 s, 2 s, 4 s... até 15 s); depois de 10 falhas seguidas
// (processo que morre em menos de 15 s) o PM2 desiste e mostra "errored" em vez de ficar em loop infinito.
const REINICIO = {
  autorestart: true,
  min_uptime: "15s",
  max_restarts: 10,
  exp_backoff_restart_delay: 1000,
  kill_timeout: 8000,
  merge_logs: true,
  time: true,
};

function logs(nome) {
  return { out_file: path.join(LOGS, `${nome}.out.log`), error_file: path.join(LOGS, `${nome}.err.log`), log_date_format: "YYYY-MM-DD HH:mm:ss" };
}

const PY_ENV = { PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" };

module.exports = {
  apps: [
    {
      name: "sales-api",
      script: PYTHON,
      args: `-m uvicorn api.app:app --host 127.0.0.1 --port ${PORTA_API}`,
      interpreter: "none",
      cwd: RAIZ,
      env: PY_ENV,
      ...REINICIO,
      ...logs("api"),
    },
    {
      name: "sales-worker",
      script: PYTHON,
      args: "-m etapa7_whatsapp.worker",
      interpreter: "none",
      cwd: RAIZ,
      env: PY_ENV,
      ...REINICIO,
      ...logs("worker"),
    },
    {
      name: "sales-gateway",
      // Roda o JS já compilado. Depois de mudar o código do gateway: `npm run build` em services/whatsapp-gateway
      // e `pm2 restart sales-gateway`.
      script: path.join(RAIZ, "services", "whatsapp-gateway", "dist", "src", "index.js"),
      interpreter: "node",
      cwd: path.join(RAIZ, "services", "whatsapp-gateway"),
      ...REINICIO,
      ...logs("gateway"),
    },
  ],
};
