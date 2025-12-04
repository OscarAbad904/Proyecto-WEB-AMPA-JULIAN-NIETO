from app import create_app

def test_config():
    assert not create_app().testing
    assert create_app("testing").testing

def test_app_exists(app):
    assert app is not None

def test_index_route(client):
    response = client.get("/")
    assert response.status_code == 200
