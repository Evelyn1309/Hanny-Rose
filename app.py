import os
import pymysql
from decimal import Decimal
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'hanny_rosse_secret_key_financial_system_2026')

# ============================================================
# CONFIGURACIÓN DE CONEXIÓN A MYSQL
# ============================================================
DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_USER = os.environ.get('DB_USER', 'root')
DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
DB_NAME = os.environ.get('DB_NAME', 'hanny_rosse_finanzas')

def get_db():
    if 'db' not in g:
        g.db = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True
        )
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# ============================================================
# DECORADORES DE SEGURIDAD
# ============================================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Debes iniciar sesión para acceder al sistema.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def generar_numero_comprobante(cursor):
    # Consulta el ID máximo registrado actualmente
    cursor.execute('SELECT MAX(id_transaccion) as max_id FROM transacciones')
    res = cursor.fetchone()
    next_id = (res['max_id'] or 0) + 1 if res and res.get('max_id') else 1
    
    # Formato: CMP-000001 (puedes cambiar 'CMP-' por el prefijo que prefieras)
    return f"CMP-{next_id:06d}"
# ============================================================
# RUTAS DEL APLICATIVO
# ============================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                '''SELECT u.*, r.nombre_rol 
                   FROM usuarios u 
                   JOIN roles r ON u.id_rol = r.id_rol 
                   WHERE u.email = %s AND u.estado = "ACTIVO"''',
                (email,)
            )
            user = cursor.fetchone()

        if user and check_password_hash(user['password_hash'], password):
            session.clear()
            session['user_id'] = user['id_usuario']
            session['user_name'] = f"{user['nombres']} {user['apellidos']}"
            session['user_role'] = user['nombre_rol']
            flash(f'¡Bienvenido(a) {session["user_name"]}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Credenciales incorrectas o usuario inactivo.', 'danger')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Has cerrado sesión correctamente.', 'info')
    return redirect(url_for('login'))

@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute('SELECT * FROM cajas WHERE estado = "ABIERTA" ORDER BY id_caja DESC LIMIT 1')
        caja_abierta = cursor.fetchone()

        total_ingresos = Decimal('0.00')
        total_egresos = Decimal('0.00')
        saldo_caja = Decimal('0.00')
        transacciones = []

        if caja_abierta:
            id_caja = caja_abierta['id_caja']

            cursor.execute(
                'SELECT COALESCE(SUM(monto), 0) as total FROM transacciones WHERE id_caja = %s AND tipo_movimiento = "INGRESO"',
                (id_caja,)
            )
            total_ingresos = Decimal(str(cursor.fetchone()['total']))

            cursor.execute(
                'SELECT COALESCE(SUM(monto), 0) as total FROM transacciones WHERE id_caja = %s AND tipo_movimiento = "EGRESO"',
                (id_caja,)
            )
            total_egresos = Decimal(str(cursor.fetchone()['total']))

            monto_inicial = Decimal(str(caja_abierta['monto_inicial']))
            saldo_caja = monto_inicial + total_ingresos - total_egresos

            cursor.execute(
                '''SELECT t.*, c.nombre_categoria, u.nombres 
                   FROM transacciones t 
                   JOIN categorias c ON t.id_categoria = c.id_categoria
                   JOIN usuarios u ON t.id_usuario = u.id_usuario
                   WHERE t.id_caja = %s ORDER BY t.fecha_hora DESC''',
                (id_caja,)
            )
            transacciones = cursor.fetchall()

    return render_template(
        'dashboard.html',
        caja=caja_abierta,
        total_ingresos=total_ingresos,
        total_egresos=total_egresos,
        saldo_caja=saldo_caja,
        transacciones=transacciones
    )

@app.route('/caja/apertura', methods=['POST'])
@login_required
def abrir_caja():
    try:
        monto_inicial = Decimal(request.form.get('monto_inicial', '0.00'))
    except Exception:
        flash('Monto inicial inválido.', 'danger')
        return redirect(url_for('dashboard'))

    user_id = session['user_id']
    db = get_db()

    with db.cursor() as cursor:
        cursor.execute('SELECT id_caja FROM cajas WHERE estado = "ABIERTA"')
        caja_activa = cursor.fetchone()

        if caja_activa:
            flash('Ya existe una caja abierta en el sistema.', 'warning')
            return redirect(url_for('dashboard'))

        cursor.execute(
            'INSERT INTO cajas (id_usuario, fecha_apertura, monto_inicial, estado) VALUES (%s, %s, %s, "ABIERTA")',
            (user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), monto_inicial)
        )

    flash('Caja abierta exitosamente con saldo inicial.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/caja/cierre', methods=['POST'])
@login_required
def cerrar_caja():
    try:
        monto_real = Decimal(request.form.get('monto_real', '0.00'))
    except Exception:
        flash('Monto ingresado inválido.', 'danger')
        return redirect(url_for('dashboard'))

    id_caja = request.form.get('id_caja')
    db = get_db()

    with db.cursor() as cursor:
        cursor.execute('SELECT * FROM cajas WHERE id_caja = %s', (id_caja,))
        caja = cursor.fetchone()

        if not caja:
            flash('Caja no encontrada.', 'danger')
            return redirect(url_for('dashboard'))

        cursor.execute(
            'SELECT COALESCE(SUM(monto), 0) as total FROM transacciones WHERE id_caja = %s AND tipo_movimiento = "INGRESO"',
            (id_caja,)
        )
        ingresos = Decimal(str(cursor.fetchone()['total']))

        cursor.execute(
            'SELECT COALESCE(SUM(monto), 0) as total FROM transacciones WHERE id_caja = %s AND tipo_movimiento = "EGRESO"',
            (id_caja,)
        )
        egresos = Decimal(str(cursor.fetchone()['total']))

        monto_inicial = Decimal(str(caja['monto_inicial']))
        monto_teorico = monto_inicial + ingresos - egresos
        diferencia = monto_real - monto_teorico

        cursor.execute(
            '''UPDATE cajas 
               SET fecha_cierre = %s, monto_final_teorico = %s, monto_final_real = %s, diferencia = %s, estado = "CERRADA"
               WHERE id_caja = %s''',
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), monto_teorico, monto_real, diferencia, id_caja)
        )

    flash(f'Caja cerrada correctamente. Diferencia registrada: ${diferencia:.2f}', 'info')
    return redirect(url_for('dashboard'))

@app.route('/transaccion/nueva', methods=['GET', 'POST'])
@login_required
def nueva_transaccion():
    db = get_db()

    with db.cursor() as cursor:
        cursor.execute('SELECT * FROM cajas WHERE estado = "ABIERTA" LIMIT 1')
        caja_abierta = cursor.fetchone()

        if not caja_abierta:
            flash('Debe abrir una caja antes de registrar movimientos financieros.', 'danger')
            return redirect(url_for('dashboard'))

        user_id = session['user_id']

        if request.method == 'POST':
            tipo = request.form.get('tipo_movimiento')
            id_categoria = request.form.get('id_categoria')
            concepto = request.form.get('concepto', '').strip()
            
            # Generar comprobante automático
            comprobante = generar_numero_comprobante(cursor)

            try:
                monto = Decimal(request.form.get('monto', '0.00'))
                if monto <= 0:
                    raise ValueError("El monto debe ser mayor a cero.")
            except Exception as e:
                flash(f'Monto inválido: {e}', 'danger')
                cursor.execute('SELECT * FROM categorias')
                categorias = cursor.fetchall()
                nuevo_comprobante = generar_numero_comprobante(cursor)
                return render_template('transaccion_form.html', categorias=categorias, numero_comprobante=nuevo_comprobante)

            if tipo == 'EGRESO':
                cursor.execute(
                    'SELECT COALESCE(SUM(monto), 0) as total FROM transacciones WHERE id_caja = %s AND tipo_movimiento = "INGRESO"',
                    (caja_abierta['id_caja'],)
                )
                ingresos = Decimal(str(cursor.fetchone()['total']))

                cursor.execute(
                    'SELECT COALESCE(SUM(monto), 0) as total FROM transacciones WHERE id_caja = %s AND tipo_movimiento = "EGRESO"',
                    (caja_abierta['id_caja'],)
                )
                egresos = Decimal(str(cursor.fetchone()['total']))

                monto_inicial = Decimal(str(caja_abierta['monto_inicial']))
                saldo_disponible = monto_inicial + ingresos - egresos

                if monto > saldo_disponible:
                    flash(f'Error: El monto (${monto:.2f}) supera el saldo disponible en caja (${saldo_disponible:.2f}).', 'danger')
                    cursor.execute('SELECT * FROM categorias')
                    categorias = cursor.fetchall()
                    nuevo_comprobante = generar_numero_comprobante(cursor)
                    return render_template('transaccion_form.html', categorias=categorias, numero_comprobante=nuevo_comprobante)

            # Obtener el ID recién insertado
            id_nueva_transaccion = cursor.lastrowid

            cursor.execute(
                '''INSERT INTO transacciones 
                   (id_caja, id_usuario, id_categoria, tipo_movimiento, monto, concepto, numero_comprobante) 
                   VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                (caja_abierta['id_caja'], user_id, id_categoria, tipo, monto, concepto, comprobante)
            )
            
            # Obtener el ID insertado
            cursor.execute("SELECT LAST_INSERT_ID() as id")
            id_transaccion = cursor.fetchone()['id']

            flash(f'Transacción registrada exitosamente. Comprobante N°: {comprobante}', 'success')
            
            # Redirigir directamente al comprobante imprimible
            return redirect(url_for('imprimir_comprobante', id_transaccion=id_transaccion))

        # Cargar formulario (GET)
        cursor.execute('SELECT * FROM categorias')
        categorias = cursor.fetchall()
        nuevo_comprobante = generar_numero_comprobante(cursor)
        

    return render_template('transaccion_form.html', categorias=categorias, numero_comprobante=nuevo_comprobante)

@app.route('/transaccion/<int:id_transaccion>/imprimir')
@login_required
def imprimir_comprobante(id_transaccion):
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            '''SELECT t.*, c.nombre_categoria, u.nombres, u.apellidos
               FROM transacciones t 
               JOIN categorias c ON t.id_categoria = c.id_categoria
               JOIN usuarios u ON t.id_usuario = u.id_usuario
               WHERE t.id_transaccion = %s''',
            (id_transaccion,)
        )
        transaccion = cursor.fetchone()

    if not transaccion:
        flash('Transacción no encontrada.', 'danger')
        return redirect(url_for('dashboard'))

    return render_template('comprobante_print.html', transaccion=transaccion)
if __name__ == '__main__':
    app.run(debug=True)