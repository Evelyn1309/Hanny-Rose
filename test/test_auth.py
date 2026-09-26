from src.auth import validar_credenciales

def test_cp01_longitud_password_invalida():
    assert validar_credenciales("usuario1", "12345") == False

def test_cp01_credenciales_correctas():
    assert validar_credenciales("usuario1", "Password123!") == True