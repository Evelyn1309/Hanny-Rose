def validar_credenciales(usuario, password):
    if len(password) < 8:
        return False
    return True