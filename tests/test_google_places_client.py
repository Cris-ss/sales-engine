import httpx

from etapa1_busca.google_places_client import GooglePlacesClient


def test_busca_categoria_e_converte_resultado():
    consultas = []

    def responder(request: httpx.Request):
        if "textsearch" in str(request.url):
            consultas.append(request.url.params["query"])
            return httpx.Response(200, json={"status": "OK", "results": [{
                "place_id": "place-1", "name": "Nutri Exemplo",
                "geometry": {"location": {"lat": -23.55, "lng": -46.63}},
            }]})
        return httpx.Response(200, json={"status": "OK", "result": {
            "name": "Nutri Exemplo", "website": "https://nutriexemplo.example",
            "formatted_phone_number": "(11) 99999-0000",
            "geometry": {"location": {"lat": -23.55, "lng": -46.63}},
            "address_components": [
                {"short_name": "Cidade Exemplo", "types": ["administrative_area_level_2"]},
                {"short_name": "SP", "types": ["administrative_area_level_1"]},
                {"long_name": "Asa Sul", "types": ["sublocality_level_1"]},
            ],
        }})

    cliente = GooglePlacesClient("teste", transport=httpx.MockTransport(responder))
    empresas = cliente.buscar("Nutricionistas", "Cidade Exemplo", "SP", 50)

    assert consultas == ["Nutricionistas Cidade Exemplo SP"]
    assert len(empresas) == 1
    assert empresas[0].externo_id == "google/place-1"
    assert empresas[0].nome == "Nutri Exemplo"
    assert empresas[0].municipio == "Cidade Exemplo"
    assert empresas[0].uf == "SP"
    assert empresas[0].website == "https://nutriexemplo.example"
