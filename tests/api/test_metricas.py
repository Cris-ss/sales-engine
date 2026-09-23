"""Métricas: números conciliados com SQL direto,
grupos sem dado, múltiplos contatos não inflam contagens, definições visíveis."""

from __future__ import annotations

from sqlalchemy import text

from db.models import CanalContato


def _dados(fab, db):
    # Alfa: contabilidade/PR, 3 emails enviados + vários scores + funil chegando a "venda"
    a = fab.empresa("Alfa", tel1="1199180999", email_final="a@a.com", tem_pelo_menos_um_canal=True)
    for i in range(3):
        fab.contato(a, status="enviado", ok=True, dias=i)
    fab.score(a, 45, dias=0)
    fab.score(a, 70, dias=3)
    fab.funil(a, "qualificada", dias=1)
    fab.funil(a, "contatada", dias=2)
    fab.funil(a, "venda", dias=3)
    # Beta: contabilidade/PR, sem nada
    b = fab.empresa("Beta")
    # Gama: imobiliárias/RJ, email enviado (derivado contatada), score 55
    c = fab.empresa("Gama", nicho=fab.nicho_i, municipio="RIO DE JANEIRO", uf="RJ", email_final="g@g.com", tem_pelo_menos_um_canal=True)
    fab.contato(c, status="enviado", ok=True)
    fab.score(c, 55)
    # Delta: imobiliárias/RJ, só formulário, na proposta
    d = fab.empresa("Delta", nicho=fab.nicho_i, municipio="RIO DE JANEIRO", uf="RJ", formulario_contato_url="http://d", tem_pelo_menos_um_canal=True)
    fab.contato(d, canal=CanalContato.FORMULARIO_SITE, destino="http://d")
    fab.funil(d, "proposta")
    # Épsilon: sem município (dado faltando)
    e = fab.empresa("Epsilon", municipio=None, uf="SP")
    db.commit()
    return a, b, c, d, e


def test_resumo_bate_com_sql_direto_e_multiplos_contatos_nao_inflam(client, fab, db):
    _dados(fab, db)
    j = client.get("/api/v1/metricas/resumo").json()
    assert j["total_empresas"] == 5
    assert j["com_email_confirmado"] == 2 == db.execute(text("select count(*) from validacoes where tem_pelo_menos_um_canal and email_final is not null")).scalar()
    assert j["com_formulario"] == 1
    assert j["com_score"] == 2                                   # Alfa tem 2 scores, conta 1 empresa
    assert j["empresas_com_email_enviado"] == 2                  # Alfa (3 envios) + Gama
    assert j["mensagens_email_enviadas"] == 4 == db.execute(text("select count(*) from contatos_enviados where status_envio='enviado'")).scalar()
    assert j["em_ganho_atual"] == 1
    assert j["com_telefone_apto"] == 1
    est = {e["estagio"]: e["total"] for e in j["por_estagio"]}
    assert est["venda"] == 1 and est["proposta"] == 1 and est["contatada"] == 1 and est["encontrada"] == 2
    assert sum(est.values()) == j["total_empresas"]
    assert "com_telefone_apto" in j["definicoes"] and "NÃO significa WhatsApp" in j["definicoes"]["com_telefone_apto"]


def test_funil_atual_nao_se_confunde_com_historico_de_passagem(client, fab, db):
    _dados(fab, db)
    j = client.get("/api/v1/metricas/funil").json()
    atual = {e["estagio"]: e["total"] for e in j["atual"]}
    hist = {e["estagio"]: e["empresas_distintas"] for e in j["historico_passagem"]}
    assert atual["qualificada"] == 0 and hist["qualificada"] == 1     # Alfa passou por qualificada, hoje está em venda
    assert atual["venda"] == 1 and hist["venda"] == 1
    assert hist["contatada"] == 1                                     # só linhas reais: o derivado da Gama NÃO entra
    assert atual["contatada"] == 1                                    # ...mas entra no estoque atual
    assert sum(c["total"] for c in j["atual_por_coluna"]) == j["total_empresas"] == 5


def test_conversao_por_nicho_com_numerador_e_denominador(client, fab, db):
    _dados(fab, db)
    j = client.get("/api/v1/metricas/conversao?nivel=nicho").json()
    por = {i["chave"]: i for i in j["itens"]}
    assert por["contabilidade"]["empresas"] == 3 and por["contabilidade"]["ganhos"] == 1
    assert por["contabilidade"]["taxa_pct"] == 33.33
    assert por["imobiliarias"]["empresas"] == 2 and por["imobiliarias"]["ganhos"] == 0 and por["imobiliarias"]["taxa_pct"] == 0.0
    assert "venda" in j["definicao"]


def test_conversao_grupo_sem_dados_vira_na_e_respeita_filtros(client, fab, db):
    _dados(fab, db)
    j = client.get("/api/v1/metricas/conversao?nivel=nicho&uf=RJ").json()
    por = {i["chave"]: i for i in j["itens"]}
    assert por["contabilidade"]["empresas"] == 0 and por["contabilidade"]["taxa_pct"] is None   # "N/A", não 0%
    assert por["imobiliarias"]["empresas"] == 2


def test_conversao_por_cidade_agrupa_municipio_uf_e_marca_sem_municipio(client, fab, db):
    _dados(fab, db)
    j = client.get("/api/v1/metricas/conversao?nivel=cidade").json()
    rotulos = {i["rotulo"]: i for i in j["itens"]}
    assert rotulos["RIO DE JANEIRO / RJ"]["empresas"] == 2
    assert rotulos["CIDADE EXEMPLO / PR"]["empresas"] == 2 and rotulos["CIDADE EXEMPLO / PR"]["ganhos"] == 1
    assert rotulos["(sem município)"]["sem_dado"] is True and rotulos["(sem município)"]["empresas"] == 1
    assert sum(i["empresas"] for i in j["itens"]) == 5                  # cada empresa em exatamente um grupo


def test_filtros_compartilhados_valem_nas_metricas(client, fab, db):
    _dados(fab, db)
    assert client.get("/api/v1/metricas/resumo?nicho_id=1").json()["total_empresas"] == 3
    assert client.get("/api/v1/metricas/resumo?faixa=sem_score").json()["total_empresas"] == 3
