def test_home_page(client):
    response = client.get("/AMPA")
    assert response.status_code == 200
    assert b"AMPA Juli\xc3\xa1n Nieto Tapia" in response.data


def test_public_noticias(client):
    response = client.get("/noticias")
    assert response.status_code == 200
    assert b"Noticias" in response.data
