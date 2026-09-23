"""Tela Sistema: status/reinício/logs via PM2. O pm2 é SEMPRE simulado nestes testes (nada é executado no sistema)."""

from __future__ import annotations

import json
import subprocess

import pytest

from api.services import sistema_service as sv

AGORA_MS = 1_800_000_000_000


def _jlist(*procs):
    return json.dumps(list(procs))


def _proc(nome, status="online", pid=123, restart=0, mem=52_428_800, cpu=1.5, uptime_ms=AGORA_MS - 65_000):
    return {"name": nome, "pid": pid, "pm2_env": {"status": status, "restart_time": restart, "pm_uptime": uptime_ms}, "monit": {"memory": mem, "cpu": cpu}}


class Pm2Falso:
    def __init__(self, jlist="[]", falhar_restart=False):
        self.chamadas: list[list[str]] = []
        self.jlist = jlist
        self.falhar_restart = falhar_restart

    def __call__(self, args, timeout=30):
        self.chamadas.append(args)
        if args[0] == "jlist":
            return subprocess.CompletedProcess(args, 0, "[PM2] aviso qualquer\n" + self.jlist + "\n", "")
        if args[0] == "restart" and self.falhar_restart:
            return subprocess.CompletedProcess(args, 1, "", "[PM2][ERROR] Process not found")
        return subprocess.CompletedProcess(args, 0, f"[PM2] {args[0]} ok \x1b[32mfeito\x1b[0m", "")


@pytest.fixture()
def pm2(monkeypatch):
    f = Pm2Falso(_jlist(_proc("sales-api"), _proc("sales-worker", status="stopped", pid=0), _proc("sales-gateway", status="errored", restart=10)))
    monkeypatch.setattr(sv, "executar_pm2", f)
    return f


def test_status_dos_tres_processos_normalizado(client, pm2, monkeypatch):
    monkeypatch.setattr(sv.time, "time", lambda: AGORA_MS / 1000)
    r = client.get("/api/v1/sistema/processos").json()
    assert r["pm2_disponivel"] is True
    por = {p["nome"]: p for p in r["processos"]}
    assert list(por) == ["sales-api", "sales-worker", "sales-gateway"]
    assert (por["sales-api"]["estado"], por["sales-api"]["uptime_seg"], por["sales-api"]["memoria_mb"], por["sales-api"]["pid"]) == ("rodando", 65, 50.0, 123)
    assert por["sales-worker"]["estado"] == "parado" and por["sales-worker"]["uptime_seg"] is None
    assert por["sales-gateway"]["estado"] == "erro" and por["sales-gateway"]["reinicios"] == 10


def test_processo_nunca_iniciado_aparece_como_nao_iniciado(client, monkeypatch):
    monkeypatch.setattr(sv, "executar_pm2", Pm2Falso(_jlist(_proc("sales-api"))))
    por = {p["nome"]: p for p in client.get("/api/v1/sistema/processos").json()["processos"]}
    assert por["sales-worker"]["estado"] == "nao_iniciado" and por["sales-worker"]["registrado"] is False


def test_sem_pm2_a_tela_recebe_o_motivo_em_vez_de_erro(client, monkeypatch):
    def sem_pm2(*a, **k):
        raise sv.Pm2Indisponivel("PM2 não encontrado. Instale com `npm install -g pm2`")

    monkeypatch.setattr(sv, "executar_pm2", sem_pm2)
    r = client.get("/api/v1/sistema/processos").json()
    assert r["pm2_disponivel"] is False and "npm install -g pm2" in r["erro"] and r["processos"] == []
    assert client.post("/api/v1/sistema/processos/sales-worker/reiniciar").status_code == 503


def test_reiniciar_worker_e_gateway_usam_pm2_restart(client, pm2):
    for nome in ("sales-worker", "sales-gateway"):
        r = client.post(f"/api/v1/sistema/processos/{nome}/reiniciar").json()
        assert r["ok"] is True and r["reiniciando"] is False and "\x1b" not in r["saida"]
        assert ["restart", nome] in pm2.chamadas


def test_reiniciar_processo_nao_registrado_sobe_pelo_ecosystem(client, monkeypatch):
    f = Pm2Falso(_jlist(_proc("sales-api")), falhar_restart=True)
    monkeypatch.setattr(sv, "executar_pm2", f)
    assert client.post("/api/v1/sistema/processos/sales-worker/reiniciar").json()["ok"] is True
    assert ["restart", "sales-worker"] in f.chamadas
    assert any(c[0] == "start" and c[-2:] == ["--only", "sales-worker"] and c[1].endswith("ecosystem.config.cjs") for c in f.chamadas)


def test_a_api_reinicia_a_si_mesma_confirmando_antes_e_sem_chamar_pm2_restart_na_requisicao(client, pm2, monkeypatch):
    agendado = []
    monkeypatch.setattr(sv, "agendar_reinicio_da_api", lambda: agendado.append(True))
    r = client.post("/api/v1/sistema/processos/sales-api/reiniciar")
    assert r.status_code == 200 and r.json()["reiniciando"] is True and "reconecta" in r.json()["mensagem"]
    assert agendado == [True]
    assert ["restart", "sales-api"] not in pm2.chamadas  # quem faz é o helper desacoplado, depois da resposta


def test_api_fora_do_pm2_nao_promete_reiniciar(client, monkeypatch):
    monkeypatch.setattr(sv, "executar_pm2", Pm2Falso(_jlist(_proc("sales-worker"))))
    monkeypatch.setattr(sv, "agendar_reinicio_da_api", lambda: pytest.fail("não devia agendar"))
    r = client.post("/api/v1/sistema/processos/sales-api/reiniciar")
    assert r.status_code == 409 and r.json()["erro"]["codigo"] == "api_fora_do_pm2"


def test_parar_a_api_pela_tela_e_recusado_e_parar_tudo_mantem_a_api(client, pm2):
    assert client.post("/api/v1/sistema/processos/sales-api/parar").status_code == 409
    r = client.post("/api/v1/sistema/tudo/parar").json()
    assert set(r["resultados"]) == {"sales-worker", "sales-gateway"} and r["api_mantida"] is True
    assert ["stop", "sales-api"] not in pm2.chamadas and ["stop", "sales-worker"] in pm2.chamadas and ["stop", "sales-gateway"] in pm2.chamadas


def test_iniciar_um_e_iniciar_tudo_usam_o_ecosystem(client, pm2):
    assert client.post("/api/v1/sistema/processos/sales-gateway/iniciar").json()["ok"] is True
    client.post("/api/v1/sistema/tudo/iniciar")
    inicios = [c for c in pm2.chamadas if c[0] == "start"]
    assert [c[-1] for c in inicios] == ["sales-gateway", "sales-worker", "sales-gateway"]


@pytest.mark.parametrize("nome", ["sales-api; rm -rf /", "../../etc/passwd", "outro", "SALES-API", "all"])
def test_nomes_fora_da_lista_fixa_sao_recusados_e_nada_e_executado(client, pm2, nome):
    for metodo, caminho in (("get", f"/api/v1/sistema/processos/{nome}/logs"), ("post", f"/api/v1/sistema/processos/{nome}/reiniciar"),
                            ("post", f"/api/v1/sistema/processos/{nome}/parar"), ("post", f"/api/v1/sistema/processos/{nome}/iniciar")):
        r = getattr(client, metodo)(caminho)
        assert r.status_code in (404, 405), (caminho, r.status_code)
    assert all(c[0] == "jlist" or c[0] == "x" for c in pm2.chamadas) or pm2.chamadas == []


def test_logs_ultimas_linhas_sem_ansi_e_limites(client, tmp_path, monkeypatch):
    monkeypatch.setattr(sv, "LOGS", tmp_path)
    (tmp_path / "worker.out.log").write_text("\n".join(f"linha {i}" for i in range(500)) + "\n", encoding="utf-8")
    (tmp_path / "worker.err.log").write_text("\x1b[31merro vermelho\x1b[0m\nSegunda linha\n", encoding="utf-8")
    r = client.get("/api/v1/sistema/processos/sales-worker/logs?linhas=50").json()
    assert len(r["saida"]) == 50 and r["saida"][-1] == "linha 499" and r["saida"][0] == "linha 450"
    assert r["erros"] == ["erro vermelho", "Segunda linha"]
    assert client.get("/api/v1/sistema/processos/sales-gateway/logs").json() == {**client.get("/api/v1/sistema/processos/sales-gateway/logs").json(), "saida": [], "erros": []}
    assert client.get("/api/v1/sistema/processos/sales-worker/logs?linhas=5").status_code == 422  # mínimo 10
    assert client.get("/api/v1/sistema/processos/sales-worker/logs?linhas=5000").status_code == 422  # máximo 1000


def test_logs_de_arquivo_enorme_le_so_o_final(tmp_path):
    grande = tmp_path / "x.log"
    grande.write_text("\n".join(f"L{i:07d}" for i in range(200_000)) + "\n", encoding="utf-8")  # ~1,8 MB
    linhas = sv._ultimas_linhas(grande, 3)
    assert linhas == ["L0199997", "L0199998", "L0199999"]


def test_jlist_com_lixo_ao_redor_do_json_e_lido():
    assert sv._json_do_jlist("[PM2] Spawning daemon\n[]\nfim") == []
    assert sv._json_do_jlist("sem json") == []


def test_agendar_reinicio_usa_processo_desacoplado_com_atraso(monkeypatch):
    chamadas = []
    monkeypatch.setattr(sv, "localizar_pm2", lambda: r"C:\pm2.cmd")
    monkeypatch.setattr(sv.subprocess, "Popen", lambda cmd, **kw: chamadas.append(cmd))
    sv.agendar_reinicio_da_api(atraso_seg=2)
    cmd = chamadas[0]
    assert cmd[0] == "powershell" and "Start-Process" in cmd[-1] and "timeout /t 2" in cmd[-1] and "restart sales-api" in cmd[-1]
