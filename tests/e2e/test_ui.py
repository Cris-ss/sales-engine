"""Testes de navegador contra o banco de teste."""

from __future__ import annotations

import csv
import io
import json
import re
import urllib.request

import pytest
from playwright.sync_api import expect
from sqlalchemy import func, select

from db.models import CanalContato, ContatoEnviado, FunilStatus

pytestmark = pytest.mark.e2e


def _seed(fab, db, extras=0):
    """Dados sintéticos com casos que importam. Retorna ids nomeados."""
    ids = {}
    # Alfa: PR, score alto, email JÁ ENVIADO (data real 01/09/2026 09:00 em São Paulo), telefone celular apto
    a = fab.empresa("Alfa Contabil", tel1="1199180999", email_final="a@alfa.com", tem_pelo_menos_um_canal=True, site_url="http://alfa.example")
    fab.score(a, 75, dores_identificadas="Sobrecarga operacional", justificativa="Escritório com sinal claro")
    fab.contato(a, status="enviado", ok=True, dias=0)
    ids["alfa"] = a.id
    # Beta: PR, sem telefone apto (fixo), score neutro
    b = fab.empresa("Beta Contabil", tel1="1133334444", email_final="b@beta.com", tem_pelo_menos_um_canal=True)
    fab.score(b, 55)
    fab.contato(b)
    ids["beta"] = b.id
    # Gama: RJ, imobiliária, na "proposta" (subestágio de Contatado)
    g = fab.empresa("Gama Imoveis", nicho=fab.nicho_i, municipio="RIO DE JANEIRO", uf="RJ", tel1="2199887766",
                    formulario_contato_url="http://g.example/c", tem_pelo_menos_um_canal=True)
    fab.score(g, 50)
    fab.funil(g, "qualificada", dias=1)
    fab.funil(g, "proposta", dias=2)
    ids["gama"] = g.id
    # Delta: RJ, sem nada (sem validação/score/histórico)
    d = fab.empresa("Delta Sem Nada", nicho=fab.nicho_i, municipio="NITEROI", uf="RJ", validacao=False)
    ids["delta"] = d.id
    # Épsilon: novo, PR, para arrastar
    e = fab.empresa("Epsilon Novo", tel1="1188776655", email_final="e@e.com", tem_pelo_menos_um_canal=True)
    fab.score(e, 65)
    ids["epsilon"] = e.id
    for i in range(extras):
        x = fab.empresa(f"Extra {i:03d}", uf="SP", municipio="SAO PAULO")
        fab.score(x, 55)
    db.commit()
    return ids


def _api(base, caminho):
    return json.loads(urllib.request.urlopen(f"{base}/api/v1{caminho}").read())


def _n(db, model, **f):
    db.expire_all()
    q = select(func.count()).select_from(model)
    for k, v in f.items():
        q = q.where(getattr(model, k) == v)
    return db.execute(q).scalar_one()


# ------------------------------------------------------------------ Lista e filtros
def test_lista_filtros_sobrevivem_ao_reload_e_email_com_data_real(servidor, pagina, fab, db):
    ids = _seed(fab, db)
    pagina.goto(f"{servidor}/?uf=PR&canal=email")
    expect(pagina.get_by_text("3 leads", exact=False).first).to_be_visible()
    expect(pagina.get_by_role("list", name="Filtros ativos")).to_contain_text("UF: PR")

    pagina.reload()                                              # filtros vivem na URL
    expect(pagina.get_by_role("list", name="Filtros ativos")).to_contain_text("UF: PR")
    expect(pagina.get_by_role("list", name="Filtros ativos")).to_contain_text("Canal: Email confirmado")
    assert "uf=PR" in pagina.url and "canal=email" in pagina.url

    # trocar de tela preserva os filtros
    pagina.get_by_role("link", name="Kanban").click()
    expect(pagina).to_have_url(re.compile(r"/kanban\?.*uf=PR"))
    pagina.get_by_role("link", name="Lista").click()
    expect(pagina.get_by_role("list", name="Filtros ativos")).to_contain_text("UF: PR")

    # data REAL do envio (data_envio = 01/09/2026 09:00 em São Paulo), não a data de geração
    linha = pagina.locator("tr", has_text="Alfa Contabil")
    expect(linha).to_contain_text("Enviado (aceito pelo SMTP)")
    expect(linha).to_contain_text("01/09/2026")
    assert ids["alfa"]


def test_busca_com_debounce_nao_perde_digitacao_e_limpa(servidor, pagina, fab, db):
    _seed(fab, db)
    pagina.goto(servidor)
    caixa = pagina.get_by_label("Buscar por nome, CNPJ ou telefone")
    caixa.press_sequentially("alfa", delay=60)
    expect(pagina).to_have_url(re.compile(r"q=alfa"))
    expect(pagina.get_by_text("1 leads", exact=False).first).to_be_visible()
    assert caixa.input_value() == "alfa"
    pagina.get_by_role("button", name="Limpar filtros").first.click()
    expect(caixa).to_have_value("")


def test_whatsapp_desabilitado_com_explicacao_e_abrir_nao_altera_funil(servidor, pagina, contexto, fab, db):
    ids = _seed(fab, db)
    # sem telefone apto: botão desabilitado + motivo visível
    pagina.goto(f"{servidor}/?lead={ids['beta']}")
    drawer = pagina.get_by_role("complementary", name="Detalhes do lead")
    expect(drawer.get_by_role("button", name="Abrir WhatsApp")).to_be_disabled()
    expect(drawer).to_contain_text("Indisponível")
    expect(drawer).to_contain_text("telefone fixo")

    # com telefone apto: abre wa.me em nova aba, sem gravar nada
    antes = (_n(db, FunilStatus), _n(db, ContatoEnviado))
    pagina.goto(f"{servidor}/?lead={ids['alfa']}")
    drawer = pagina.get_by_role("complementary", name="Detalhes do lead")
    expect(drawer).to_contain_text("não verificado")
    with contexto.expect_page() as nova:
        drawer.get_by_role("button", name="Abrir WhatsApp").click()
    nova.value.wait_for_url(re.compile(r"^https://wa\.me/"), timeout=10_000)   # abre em about:blank e navega após buscar o link
    assert nova.value.url.startswith("https://wa.me/551199918")  # 9º dígito acrescentado
    assert "text=Ol%C3%A1" in nova.value.url
    assert (_n(db, FunilStatus), _n(db, ContatoEnviado)) == antes   # nada foi registrado


def test_drawer_mostra_estagio_derivado_e_historico(servidor, pagina, fab, db):
    ids = _seed(fab, db)
    pagina.goto(f"{servidor}/?lead={ids['alfa']}")
    drawer = pagina.get_by_role("complementary", name="Detalhes do lead")
    expect(drawer).to_contain_text("inferido")               # Alfa: email enviado, sem histórico => derivado
    expect(drawer).to_contain_text("Gerada em")
    expect(drawer).to_contain_text("Enviada em")
    pagina.goto(f"{servidor}/?lead={ids['delta']}")          # sem validação/score/histórico continua abrindo
    expect(pagina.get_by_role("complementary", name="Detalhes do lead")).to_contain_text("Sem score")


# ------------------------------------------------------------------ Kanban
def _arrastar(pagina, lead_id, coluna):
    alca = pagina.locator(f'[data-lead-id="{lead_id}"] .alca')
    alca.scroll_into_view_if_needed()
    a = alca.bounding_box()
    d = pagina.locator(f'[data-coluna="{coluna}"] h3').bounding_box()
    x0, y0 = a["x"] + a["width"] / 2, a["y"] + a["height"] / 2
    pagina.mouse.move(x0, y0)
    pagina.mouse.down()
    pagina.mouse.move(x0 + 12, y0 + 12, steps=4)
    pagina.mouse.move(d["x"] + 60, d["y"] + 40, steps=25)
    pagina.mouse.up()


def _coluna(pagina, coluna):
    return pagina.locator(f'[data-coluna="{coluna}"]')


def test_kanban_arrastar_persiste_apos_reload_sem_apagar_historico(servidor, pagina, fab, db):
    ids = _seed(fab, db)
    pagina.goto(f"{servidor}/kanban")
    expect(_coluna(pagina, "novo")).to_contain_text("Epsilon Novo")
    _arrastar(pagina, ids["epsilon"], "qualificado")
    expect(_coluna(pagina, "qualificado")).to_contain_text("Epsilon Novo")
    expect(pagina.get_by_text("Lead movido.")).to_be_visible()

    pagina.reload()
    expect(_coluna(pagina, "qualificado")).to_contain_text("Epsilon Novo")
    expect(_coluna(pagina, "novo")).not_to_contain_text("Epsilon Novo")
    assert _n(db, FunilStatus, empresa_id=ids["epsilon"]) == 1
    # histórico anterior de outra empresa segue intacto
    assert _n(db, FunilStatus, empresa_id=ids["gama"]) == 2


def test_kanban_mesma_coluna_nao_transforma_proposta_em_contatada(servidor, pagina, fab, db):
    ids = _seed(fab, db)
    pagina.goto(f"{servidor}/kanban")
    expect(_coluna(pagina, "contatado").locator(f'[data-lead-id="{ids["gama"]}"]')).to_contain_text("proposta")
    posts = []
    pagina.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    _arrastar(pagina, ids["gama"], "contatado")               # solta na MESMA coluna
    pagina.wait_for_timeout(700)
    assert posts == []                                        # nenhuma requisição
    assert _n(db, FunilStatus, empresa_id=ids["gama"]) == 2   # nenhuma linha nova
    expect(_coluna(pagina, "contatado").locator(f'[data-lead-id="{ids["gama"]}"]')).to_contain_text("proposta")


def test_kanban_conflito_entre_duas_abas_retorna_409_e_recarrega(servidor, contexto, fab, db):
    ids = _seed(fab, db)
    aba1, aba2 = contexto.new_page(), contexto.new_page()
    for p in (aba1, aba2):
        p.goto(f"{servidor}/kanban")
        expect(_coluna(p, "novo")).to_contain_text("Epsilon Novo")

    _arrastar(aba1, ids["epsilon"], "qualificado")            # aba 1 vence
    expect(_coluna(aba1, "qualificado")).to_contain_text("Epsilon Novo")

    _arrastar(aba2, ids["epsilon"], "descartado")             # aba 2 ainda tem o id de histórico antigo (null)
    expect(aba2.get_by_text("Conflito", exact=False)).to_be_visible()
    # a UI da aba 2 reflete a verdade do servidor, não o palpite otimista
    expect(_coluna(aba2, "qualificado")).to_contain_text("Epsilon Novo")
    expect(_coluna(aba2, "descartado")).not_to_contain_text("Epsilon Novo")
    assert _n(db, FunilStatus, empresa_id=ids["epsilon"]) == 1


def test_kanban_falha_da_api_desfaz_atualizacao_otimista(servidor, pagina, fab, db):
    ids = _seed(fab, db)
    presas = []
    pagina.route("**/transicoes", lambda rota: presas.append(rota))   # segura a requisição
    pagina.goto(f"{servidor}/kanban")
    expect(_coluna(pagina, "novo")).to_contain_text("Epsilon Novo")

    _arrastar(pagina, ids["epsilon"], "ganho")
    expect(_coluna(pagina, "ganho")).to_contain_text("Epsilon Novo")  # otimista: já está na coluna nova
    assert presas, "a requisição deveria estar pendente"
    presas[0].fulfill(status=500, content_type="application/json",
                      body=json.dumps({"erro": {"codigo": "erro_interno", "mensagem": "Erro interno inesperado."}}))

    expect(pagina.get_by_text("A mudança foi desfeita", exact=False)).to_be_visible()
    expect(_coluna(pagina, "novo")).to_contain_text("Epsilon Novo")   # voltou
    expect(_coluna(pagina, "ganho")).not_to_contain_text("Epsilon Novo")
    assert _n(db, FunilStatus, empresa_id=ids["epsilon"]) == 0


def test_kanban_menu_mover_por_teclado(servidor, pagina, fab, db):
    ids = _seed(fab, db)
    pagina.goto(f"{servidor}/kanban")
    pagina.locator(f'[data-lead-id="{ids["epsilon"]}"] select').select_option("qualificado")
    expect(_coluna(pagina, "qualificado")).to_contain_text("Epsilon Novo")
    expect(pagina.get_by_text("Lead movido.")).to_be_visible()      # espera o servidor confirmar (o card já se move de forma otimista)
    assert _n(db, FunilStatus, empresa_id=ids["epsilon"]) == 1


# ------------------------------------------------------------------ Métricas
def test_metricas_na_tela_batem_com_a_api(servidor, pagina, fab, db):
    _seed(fab, db)
    r = _api(servidor, "/metricas/resumo")
    pagina.goto(f"{servidor}/metricas")
    expect(pagina.locator(".kpi", has_text="Empresas").first.locator(".kpi-valor")).to_have_text(str(r["total_empresas"]))
    kpi_email = pagina.locator(".kpi", has_text="Com email confirmado").locator(".kpi-valor")
    expect(kpi_email).to_have_text(str(r["com_email_confirmado"]))
    # a definição da métrica está acessível
    pagina.locator(".kpi", has_text="Telefone apto").get_by_role("button", name="Ver definição da métrica").focus()
    expect(pagina.get_by_role("tooltip").filter(has_text="NÃO significa WhatsApp verificado").first).to_be_visible()
    # conversão mostra numerador/denominador e N/A para grupo sem dado
    expect(pagina.get_by_role("table", name="Conversão por nicho")).to_contain_text("(0/")
    pagina.goto(f"{servidor}/metricas?uf=RJ&nicho_id=1")
    expect(pagina.get_by_role("table", name="Conversão por nicho")).to_contain_text("N/A")


# ------------------------------------------------------------------ Exportação
def test_exportar_csv_e_xlsx_batem_com_o_filtro_completo(servidor, pagina, fab, db):
    _seed(fab, db, extras=60)                                 # 65 leads: mais que uma página (50)
    pagina.goto(f"{servidor}/?uf=SP")
    expect(pagina.get_by_text("60 leads", exact=False).first).to_be_visible()
    pagina.get_by_role("button", name="Exportar").click()
    with pagina.expect_download() as d:
        pagina.get_by_role("menuitem", name="CSV (Excel em português)").click()
    caminho = d.value.path()
    texto = open(caminho, "rb").read().decode("utf-8-sig")
    linhas = list(csv.reader(io.StringIO(texto), delimiter=";"))
    assert len(linhas) - 1 == 60                              # tudo do filtro, não só a página de 50
    assert all(l[5] == "SP" for l in linhas[1:])
    assert linhas[1][1].startswith("00.")                     # zeros à esquerda preservados
    assert d.value.suggested_filename.endswith(".csv")

    pagina.get_by_role("button", name="Exportar").click()
    with pagina.expect_download() as d2:
        pagina.get_by_role("menuitem", name="Excel (.xlsx)").click()
    assert d2.value.suggested_filename.endswith(".xlsx")


def test_fluxo_ponta_a_ponta_filtrar_abrir_mudar_estagio_metricas_exportar(servidor, pagina, fab, db):
    ids = _seed(fab, db)
    pagina.goto(servidor)
    pagina.locator('label.campo:has(span:text-is("UF")) select').select_option("PR")
    expect(pagina.get_by_text("3 leads", exact=False).first).to_be_visible()

    pagina.locator("tr", has_text="Epsilon Novo").get_by_role("button", name="Detalhes").click()
    drawer = pagina.get_by_role("complementary", name="Detalhes do lead")
    drawer.get_by_label("Novo estágio").select_option("venda")
    drawer.get_by_role("button", name="Mover").click()
    expect(pagina.get_by_text("Estágio atualizado.")).to_be_visible()
    assert _n(db, FunilStatus, empresa_id=ids["epsilon"]) == 1

    pagina.get_by_role("button", name="Fechar detalhes").click()
    pagina.get_by_role("link", name="Métricas").click()
    expect(pagina.locator(".kpi", has_text="Em Ganho").locator(".kpi-valor")).to_have_text("1")

    pagina.get_by_role("button", name="Exportar").click()
    with pagina.expect_download() as d:
        pagina.get_by_role("menuitem", name="CSV (Excel em português)").click()
    linhas = list(csv.reader(io.StringIO(open(d.value.path(), "rb").read().decode("utf-8-sig")), delimiter=";"))
    epsilon = next(l for l in linhas if "Epsilon" in l[2])
    assert epsilon[12] == "ganho" and epsilon[13] == "venda"  # Coluna do funil / Estágio
    assert len(linhas) - 1 == 3                               # só PR


def test_estados_de_erro_e_vazio(servidor, pagina, fab, db):
    _seed(fab, db)
    pagina.goto(f"{servidor}/?q=inexistente-xyz")
    expect(pagina.get_by_text("Nenhum lead encontrado com esses filtros.")).to_be_visible()
    pagina.route("**/api/v1/leads?**", lambda r: r.fulfill(status=500, content_type="application/json",
                 body=json.dumps({"erro": {"codigo": "erro_interno", "mensagem": "Erro interno inesperado."}})))
    pagina.goto(f"{servidor}/?uf=PR")
    expect(pagina.get_by_role("alert").first).to_contain_text("Algo deu errado")


# ------------------------------------------------------------------ Mapa
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360f8cfc00000030101000f2a5d0d0000000049454e44ae426082"
)


def _seed_mapa(fab, db):
    from api.persistence.geo_models import EmpresaGeolocalizacao as G

    ids = {}
    a = fab.empresa("Mapa Cidade Um", municipio="CIDADE EXEMPLO", uf="PR", email_final="a@a.com", tem_pelo_menos_um_canal=True)
    fab.score(a, 75)
    db.add(G(empresa_id=a.id, latitude=-25.43, longitude=-49.27, fonte="teste", precisao="cep", status="localizada"))
    b = fab.empresa("Mapa Cidade Dois", municipio="CIDADE EXEMPLO", uf="PR")
    fab.score(b, 55)
    db.add(G(empresa_id=b.id, latitude=-25.4284, longitude=-49.2733, fonte="teste", precisao="municipio", status="localizada"))
    c = fab.empresa("Mapa Rio", nicho=fab.nicho_i, municipio="RIO DE JANEIRO", uf="RJ")
    db.add(G(empresa_id=c.id, latitude=-22.9, longitude=-43.2, fonte="teste", precisao="municipio", status="localizada"))
    d = fab.empresa("Mapa Sem Coordenada", municipio="LUGAR NENHUM", uf="SP")
    db.add(G(empresa_id=d.id, fonte="teste", precisao="municipio", status="nao_encontrada"))
    fab.empresa("Mapa Sem Linha", municipio="OUTRO", uf="SP")
    db.commit()
    ids.update(a=a.id, b=b.id, c=c.id)
    return ids


def test_mapa_pinos_precisao_lista_sincronizada_e_nenhuma_geocodificacao(servidor, contexto, pagina, fab, db):
    ids = _seed_mapa(fab, db)
    contexto.route("**/tile.openstreetmap.org/**", lambda r: r.fulfill(status=200, content_type="image/png", body=PNG_1X1))
    requisicoes = []
    pagina.on("request", lambda r: requisicoes.append(r.url))

    pagina.goto(f"{servidor}/mapa")
    # empresas sem coordenadas são contabilizadas (2 de 5)
    expect(pagina.locator(".aviso-mapa")).to_contain_text("2 de 5")
    expect(pagina.get_by_text("por CEP (aproximado)", exact=False).first).to_contain_text("1 por CEP")
    expect(pagina.get_by_label("Legenda do mapa")).to_contain_text("Centro do município (não é o endereço)")
    expect(pagina.get_by_label("Legenda do mapa")).to_contain_text("Posição aproximada pelo CEP")
    expect(pagina.locator(".leaflet-container")).to_be_visible()

    lista = pagina.get_by_label("Leads na área visível")
    expect(lista.locator(".item-mapa")).to_have_count(3)
    expect(lista).to_contain_text("centro do município")

    # seleção pela lista abre o popup no mapa, com a precisão explicada
    lista.get_by_role("button", name=re.compile("Mapa Rio")).click()
    popup = pagina.locator(".leaflet-popup")
    expect(popup).to_be_visible(timeout=8000)
    expect(popup).to_contain_text("NÃO é o endereço da empresa")
    popup.get_by_role("button", name="Ver detalhes").click()
    expect(pagina).to_have_url(re.compile(rf"lead={ids['c']}"))
    expect(pagina.get_by_role("complementary", name="Detalhes do lead")).to_contain_text("Mapa Rio")
    expect(pagina.get_by_role("complementary", name="Detalhes do lead")).to_contain_text("Coordenadas:")

    # navegar/abrir o mapa NUNCA chama serviço de geocodificação
    externos = [u for u in requisicoes if not u.startswith(servidor) and "tile.openstreetmap.org" not in u]
    assert externos == [], externos
    assert not [u for u in requisicoes if any(h in u for h in ("awesomeapi", "nominatim", "brasilapi", "googleapis"))]


def test_mapa_filtros_da_lista_valem_no_mapa_e_modo_de_cor(servidor, contexto, pagina, fab, db):
    _seed_mapa(fab, db)
    contexto.route("**/tile.openstreetmap.org/**", lambda r: r.fulfill(status=200, content_type="image/png", body=PNG_1X1))
    pagina.goto(f"{servidor}/mapa?uf=RJ")
    lista = pagina.get_by_label("Leads na área visível")
    expect(lista.locator(".item-mapa")).to_have_count(1)
    expect(lista).to_contain_text("Mapa Rio")
    expect(pagina.locator(".aviso-mapa")).to_have_count(0)   # no filtro RJ todos têm coordenadas

    pagina.get_by_role("button", name="Cor por score").click()
    expect(pagina.get_by_role("button", name="Cor por score")).to_have_attribute("aria-pressed", "true")
    expect(pagina.get_by_label("Legenda do mapa")).to_contain_text("Sem score")
    expect(pagina.get_by_label("Legenda do mapa")).to_contain_text("Neutro (55")
    pagina.get_by_role("link", name="Lista").click()                                  # filtro acompanha
    expect(pagina.get_by_role("list", name="Filtros ativos")).to_contain_text("UF: RJ")
