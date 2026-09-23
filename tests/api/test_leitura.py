"""API de leitura: leads, filtros e Kanban."""

from __future__ import annotations

import sys

from sqlalchemy import func, select

from db.models import CanalContato, ContatoEnviado, Empresa, FunilStatus


def _monta(fab, db):
    # A: vários scores (o mais recente vence), vários contatos, histórico de funil
    a = fab.empresa("Alfa", tel1="1199180999", email_final="a@alfa.com", tem_pelo_menos_um_canal=True,
                    formulario_contato_url="http://alfa.com/contato")
    fab.score(a, 45, dias=0)
    fab.score(a, 70, dias=5, dores_identificadas="dor1; dor2")
    fab.contato(a, status="enviado", ok=True, dias=6)
    fab.contato(a, status="pendente", dias=0)
    fab.contato(a, canal=CanalContato.FORMULARIO_SITE, destino="http://alfa.com/contato")
    fab.funil(a, "qualificada", dias=1)
    fab.funil(a, "proposta", dias=2)
    # B: nada além da empresa (sem validação, score, contato, funil)
    b = fab.empresa("Beta", validacao=False)
    # C: score sentinela 55, email realmente enviado, SEM histórico de funil
    c = fab.empresa("Gama", nicho=fab.nicho_i, municipio="RIO DE JANEIRO", uf="RJ", tel1="2132162212",
                    email_final="c@gama.com", tem_pelo_menos_um_canal=True)
    fab.score(c, 55)
    fab.contato(c, status="enviado", ok=True, dias=3)
    # D: só formulário, celular apto
    d = fab.empresa("Delta", tel1="8199003422", formulario_contato_url="http://d.com", tem_pelo_menos_um_canal=True)
    fab.score(d, 50)
    fab.contato(d, canal=CanalContato.FORMULARIO_SITE, destino="http://d.com")
    # E: excluída do fluxo (canal não confirmado) mas com email_final guardado
    e = fab.empresa("Epsilon", email_final="e@eps.com", tem_pelo_menos_um_canal=False,
                    motivo_reprovacao="site_nao_confirmado_marca_ausente")
    db.commit()
    return a, b, c, d, e


def test_uma_linha_por_empresa_mesmo_com_muitos_scores_e_contatos(client, fab, db):
    _monta(fab, db)
    r = client.get("/api/v1/leads?page_size=100")
    assert r.status_code == 200
    j = r.json()
    ids = [i["id"] for i in j["itens"]]
    assert j["total"] == 5 == len(ids) == len(set(ids))
    assert db.execute(select(func.count()).select_from(Empresa)).scalar_one() == j["total"]


def test_score_vigente_e_o_mais_recente_e_ausente_nao_e_zero(client, fab, db):
    a, b, *_ = _monta(fab, db)
    assert client.get(f"/api/v1/leads/{a.id}").json()["score"] == 70.0
    lb = client.get(f"/api/v1/leads/{b.id}").json()
    assert lb["score"] is None and lb["faixa_score"] == "sem_score"


def test_desempate_do_score_por_id_quando_criado_em_igual(client, fab, db):
    e = fab.empresa("Empate")
    fab.score(e, 50, dias=0)
    fab.score(e, 65, dias=0)  # mesmo criado_em, id maior => vence
    db.commit()
    assert client.get(f"/api/v1/leads/{e.id}").json()["score"] == 65.0


def test_empresa_sem_validacao_score_ou_historico_continua_acessivel(client, fab, db):
    _, b, *_ = _monta(fab, db)
    r = client.get(f"/api/v1/leads/{b.id}")
    assert r.status_code == 200
    j = r.json()
    assert j["coluna"] == "novo" and j["estagio"] == "encontrada" and j["estagio_derivado"] is True
    assert j["email_confirmado"] is False and j["formulario_confirmado"] is False
    for sub in ("scores", "contatos", "funil"):
        rr = client.get(f"/api/v1/leads/{b.id}/{sub}")
        assert rr.status_code == 200 and rr.json()["total"] == 0


def test_empresa_osm_sem_cnpj_continua_acessivel(client, fab, db):
    empresa = Empresa(
        nicho_id=fab.nicho_c.id, cnpj=None, fonte="openstreetmap", fonte_externo_id="node/teste-1",
        nome_fantasia="Lead OSM sem CNPJ", municipio="CIDADE EXEMPLO", uf="SP",
    )
    db.add(empresa)
    db.commit()

    lista = client.get("/api/v1/leads", params={"q": "Lead OSM"})
    assert lista.status_code == 200
    assert lista.json()["itens"][0]["cnpj"] is None
    detalhe = client.get(f"/api/v1/leads/{empresa.id}")
    assert detalhe.status_code == 200 and detalhe.json()["cnpj"] is None


def test_estagio_derivado_de_email_enviado_sem_gravar_nada(client, fab, db):
    _, _, c, *_ = _monta(fab, db)
    j = client.get(f"/api/v1/leads/{c.id}").json()
    assert j["estagio"] == "contatada" and j["coluna"] == "contatado" and j["estagio_derivado"] is True
    assert j["email_status"] == "enviado" and j["qtd_emails_enviados"] == 1
    assert db.execute(select(func.count()).select_from(FunilStatus).where(FunilStatus.empresa_id == c.id)).scalar_one() == 0


def test_historico_real_prevalece_sobre_derivado(client, fab, db):
    a, *_ = _monta(fab, db)
    j = client.get(f"/api/v1/leads/{a.id}").json()
    assert j["estagio"] == "proposta" and j["coluna"] == "contatado" and j["estagio_derivado"] is False
    assert j["funil_id"] is not None


def test_email_enviado_nao_confirma_entrega_e_data_real_vem_de_data_envio(client, fab, db):
    a, *_ = _monta(fab, db)
    itens = client.get(f"/api/v1/leads/{a.id}/contatos?canal=email").json()["itens"]
    assert {i["status"] for i in itens} == {"enviado", "pendente"}
    enviado = next(i for i in itens if i["status"] == "enviado")
    assert enviado["enviado_em"] is not None
    pendente = next(i for i in itens if i["status"] == "pendente")
    assert pendente["enviado_em"] is None  # geração != envio


def test_canais_e_whatsapp_nao_verificado(client, fab, db):
    a, b, c, d, e = _monta(fab, db)
    ids = lambda q: sorted(i["id"] for i in client.get(f"/api/v1/leads?page_size=100&{q}").json()["itens"])
    assert ids("canal=email") == sorted([a.id, c.id])          # E tem email guardado mas canal NÃO confirmado
    assert ids("canal=formulario") == sorted([a.id, d.id])
    assert ids("canal=whatsapp") == sorted([a.id, d.id])       # celulares; fixo do C não é apto
    assert ids("canal=ambos") == [a.id]
    assert ids("canal=sem_canal") == sorted([b.id, e.id])     # C tem email confirmado
    la = client.get(f"/api/v1/leads/{a.id}").json()
    assert la["whatsapp_apto"] is True
    w = client.get(f"/api/v1/leads/{a.id}/whatsapp-link").json()
    assert w["verificado"] is False and w["link"].startswith("https://wa.me/55")


def test_whatsapp_link_desabilitado_sem_telefone_apto_e_nao_grava(client, fab, db):
    _, _, c, *_ = _monta(fab, db)
    antes = (
        db.execute(select(func.count()).select_from(ContatoEnviado)).scalar_one(),
        db.execute(select(func.count()).select_from(FunilStatus)).scalar_one(),
    )
    w = client.get(f"/api/v1/leads/{c.id}/whatsapp-link").json()
    assert w["apto"] is False and w["link"] is None and w["motivo_inapto"]
    db.expire_all()
    depois = (
        db.execute(select(func.count()).select_from(ContatoEnviado)).scalar_one(),
        db.execute(select(func.count()).select_from(FunilStatus)).scalar_one(),
    )
    assert antes == depois


def test_filtros_score_faixa_uf_busca(client, fab, db):
    a, b, c, d, e = _monta(fab, db)
    ids = lambda q: sorted(i["id"] for i in client.get(f"/api/v1/leads?page_size=100&{q}").json()["itens"])
    assert ids("faixa=neutro") == [c.id]
    assert ids("faixa=baixo") == [d.id]
    assert ids("faixa=alto") == [a.id]
    assert ids("faixa=sem_score") == sorted([b.id, e.id])
    assert ids("sem_score=true") == sorted([b.id, e.id])
    assert ids("score_min=50&score_max=55") == sorted([c.id, d.id])
    assert ids("uf=RJ") == [c.id]
    assert ids("municipio=rio de janeiro") == [c.id]
    assert ids("q=alfa") == [a.id]
    assert ids(f"q={a.cnpj}") == [a.id]
    assert ids(f"q=00.000.000/0000-0{a.id}") == [a.id]  # CNPJ formatado é normalizado para dígitos
    assert ids("q=1199180999") == [a.id]
    assert ids("q=%25") == []  # curinga do LIKE é escapado, não casa tudo


def test_ordenacao_estavel_e_paginacao(client, fab, db):
    for i in range(7):
        fab.score(fab.empresa(f"Emp{i}"), 55)
    db.commit()
    vistos = []
    for page in (1, 2, 3):
        j = client.get(f"/api/v1/leads?page_size=3&page={page}&sort=score&order=desc").json()
        vistos += [x["id"] for x in j["itens"]]
        assert j["total"] == 7
    assert vistos == sorted(vistos) and len(set(vistos)) == 7  # mesmo score => desempate por id


def test_limites_e_erros_com_formato_estavel(client):
    r = client.get("/api/v1/leads?page_size=101")
    assert r.status_code == 422 and r.json()["erro"]["codigo"] == "validacao"
    r = client.get("/api/v1/leads?canal=telepatia")
    assert r.status_code == 422 and r.json()["erro"]["codigo"] == "filtro_invalido"
    r = client.get("/api/v1/leads/999999")
    assert r.status_code == 404 and r.json()["erro"]["codigo"] == "lead_nao_encontrado"


def test_kanban_resumo_bate_com_universo(client, fab, db):
    _monta(fab, db)
    j = client.get("/api/v1/kanban/resumo").json()
    tot = {c["codigo"]: c["total"] for c in j["colunas"]}
    assert j["total"] == 5 == sum(tot.values())
    assert tot["contatado"] == 2 and tot["novo"] == 3  # A (proposta) e C (derivado)
    pag = client.get("/api/v1/kanban/colunas/contatado/leads").json()
    assert pag["total"] == 2
    assert client.get("/api/v1/kanban/colunas/inexistente/leads").status_code == 404


def test_kanban_resumo_ignora_coluna_do_filtro_mas_respeita_demais(client, fab, db):
    _monta(fab, db)
    j = client.get("/api/v1/kanban/resumo?coluna=ganho&uf=PR").json()
    assert j["total"] == 4  # 5 empresas menos a do RJ; coluna ignorada


def test_filtros_opcoes_e_nichos(client, fab, db):
    _monta(fab, db)
    o = client.get("/api/v1/filtros/opcoes").json()
    assert {f["codigo"] for f in o["faixas"]} == {"sem_score", "baixo", "neutro", "medio", "alto"}
    assert o["cortes_score"] == {"neutro": 55.0, "alto_min": 65.0}
    assert {u["codigo"] for u in o["ufs"]} == {"PR", "RJ"}
    assert sum(n["total"] for n in client.get("/api/v1/nichos").json()) == 5


def test_consultas_nao_importam_etapas_do_pipeline(client, fab, db):
    _monta(fab, db)
    modulos_antes = set(sys.modules)
    client.get("/api/v1/leads")
    proibidos = {"etapa1_busca", "etapa2_validacao", "etapa3_scoring", "etapa4_email", "etapa5_envio"}
    modulos_importados = set(sys.modules) - modulos_antes
    assert not (proibidos & {m.split(".")[0] for m in modulos_importados})


def test_consulta_busca_nome_entre_aspas_mais_endereco_sem_complemento_e_cep(client, fab, db):
    e = fab.empresa("Alfa")
    e.nome_fantasia, e.logradouro, e.numero = "ALFA CONTABIL", "RUA SAO VICENTE", "259"
    e.complemento, e.bairro, e.cep, e.municipio, e.uf = "SALA 2", "CENTRO", "12345678", "CIDADE EXEMPLO", "PR"
    sem_fantasia = fab.empresa("Beta")
    sem_fantasia.nome_fantasia, sem_fantasia.razao_social = None, "BETA LTDA"
    sem_fantasia.logradouro, sem_fantasia.numero, sem_fantasia.bairro = "AV X", None, None
    sem_fantasia.municipio, sem_fantasia.uf = "GOIANIA", "GO"
    db.commit()
    assert client.get(f"/api/v1/leads/{e.id}").json()["consulta_busca"] == '"ALFA CONTABIL" RUA SAO VICENTE 259 – CENTRO – CIDADE EXEMPLO/PR'
    assert client.get(f"/api/v1/leads/{sem_fantasia.id}").json()["consulta_busca"] == '"BETA LTDA" AV X – GOIANIA/GO'


def test_consulta_busca_sem_endereco_deixa_claro_que_e_por_nicho(client, fab, db):
    e = fab.empresa("Osm")
    e.nome_fantasia, e.logradouro, e.bairro, e.numero = "Cardiologia", None, None, None
    e.municipio, e.uf = "Cidade Exemplo", "SP"
    db.commit()
    j = client.get(f"/api/v1/leads/{e.id}").json()
    assert j["consulta_busca"] == f'"Cardiologia" (nicho: {j["nicho_nome"]}) Cidade Exemplo/SP'
