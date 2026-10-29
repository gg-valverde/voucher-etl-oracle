"""Adaptación pública del proyecto de vouchers: configuración externa y esquema genérico.
No contiene datos reales. Ejecutar demo_offline.py para revisar sin conexiones.
"""
import os
import uuid

from datetime import datetime, timezone, timedelta
import time


# ============================================================
# CONFIGURACION API
# ============================================================

LOGIN_URL = os.getenv("VOUCHER_LOGIN_URL", "")
VOUCHER_URL = os.getenv("VOUCHER_API_URL", "")

USERNAME = os.getenv("VOUCHER_API_USER", "")
PASSWORD = os.getenv("VOUCHER_API_PASSWORD", "")


# ============================================================
# PARAMETROS API
# ============================================================

PAGE_LENGTH = 5000  # Probar 10000 solo si la API lo admite
REQUEST_TIMEOUT = 60
MAX_RETRIES = 3
ORACLE_BATCH_SIZE = 5000
STAGING_TABLE = "VOUCHER_STAGE"


# ============================================================
# CONFIGURACION ORACLE
# ============================================================

ORACLE_CLIENT = os.getenv("ORACLE_CLIENT_LIB_DIR", "")

ORACLE_USER = os.getenv("ORACLE_USER", "")
ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD", "")

ORACLE_DSN = os.getenv("ORACLE_DSN", "")


# ============================================================
# ZONA HORARIA
# ============================================================

UTC_MENOS_4 = timezone(timedelta(hours=-4))

# ============================================================
# CONFIGURACIONES Y FECHAS DESDE ORACLE
# ============================================================

SQL_CAMPANAS = """
SELECT
    VOUCHER_CONFIG,
    CAMPANA_VOUCHER,
    TO_CHAR(FECHA_INICIO, 'YYYY-MM-DD') AS FECHA_INICIO,
    TO_CHAR(FECHA_FIN, 'YYYY-MM-DD') AS FECHA_FIN
FROM VOUCHER_CONFIG
WHERE ACTIVO = 1
ORDER BY VOUCHER_CONFIG
"""


# ============================================================
# FUNCION CONVERSION FECHA
# UTC -> UTC-4 (COMPATIBLE CON PYTHON 3.8)
# ============================================================

def convertir_fecha(valor):

    if valor is None or valor == "":
        return None

    try:
        cadena = str(valor).strip().replace("Z", "+00:00")

        # Python 3.8 requiere exactamente 6 dígitos en los microsegundos.
        # Ajustamos cadenas con 5 dígitos (ej. .57692) o distintas longitudes.
        if "." in cadena:
            partes = cadena.split(".")
            resto_micro = partes[1]

            # Buscar si la fracción de segundo tiene offset (+00:00 o -04:00)
            idx_tz = max(resto_micro.find("+"), resto_micro.find("-"))

            if idx_tz != -1:
                fraccion = resto_micro[:idx_tz]
                tz_part = resto_micro[idx_tz:]
            else:
                fraccion = resto_micro
                tz_part = ""

            # Normalizar la fracción de segundos a 6 dígitos exactos
            fraccion = fraccion[:6].ljust(6, "0")
            cadena = partes[0] + "." + fraccion + tz_part

        # Convertir ISO 8601
        fecha = datetime.fromisoformat(cadena)

        # Si no tiene zona horaria, asumimos UTC
        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=timezone.utc)

        # Convertir a UTC-4
        return fecha.astimezone(UTC_MENOS_4)

    except Exception as e:

        print(
            "ADVERTENCIA: fecha no valida: {} | {}".format(
                valor,
                e
            )
        )

        return None


# ============================================================
# FUNCION REQUEST GET CON REINTENTOS
# ============================================================

def obtener_pagina(
    session,
    token,
    fecha_inicio,
    fecha_fin,
    voucher_config,
    pagina
):

    headers = {
        "Authorization": "Bearer {}".format(token)
    }

    params = {
        "start": fecha_inicio,
        "end": fecha_fin,
        "page": pagina,
        "pageLength": PAGE_LENGTH,
        "voucherConfig": voucher_config
    }

    ultimo_error = None

    for intento in range(1, MAX_RETRIES + 1):

        try:

            response = session.get(
                VOUCHER_URL,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT
            )

            response.raise_for_status()

            return response.json()

        except Exception as e:

            ultimo_error = e

            print(
                "  Error pagina {} - intento {}/{}: {}".format(
                    pagina,
                    intento,
                    MAX_RETRIES,
                    e
                )
            )

            if intento < MAX_RETRIES:

                time.sleep(2 * intento)

    raise Exception(
        "No se pudo obtener la pagina {}: {}".format(
            pagina,
            ultimo_error
        )
    )


# ============================================================
# LOGIN
# ============================================================

def obtener_token(session):

    print("")
    print("========================================")
    print("LOGIN API")
    print("========================================")

    response = session.post(

        LOGIN_URL,

        json={
            "username": USERNAME,
            "password": PASSWORD
        },

        headers={
            "Content-Type": "application/json"
        },

        timeout=REQUEST_TIMEOUT
    )

    print(
        "HTTP LOGIN: {}".format(
            response.status_code
        )
    )

    response.raise_for_status()

    login_data = response.json()

    token = login_data["access"]

    print("Login OK")
    print("Token obtenido: SI")

    print(
        "Expiration: {}".format(
            login_data.get("expiration")
        )
    )

    return token


# ============================================================
# LEER CAMPAÑAS ACTIVAS DESDE ORACLE
# ============================================================

def obtener_campanas(cursor):
    print("Leyendo campañas activas desde VOUCHER_CONFIG...")
    cursor.execute(SQL_CAMPANAS)
    campanas = cursor.fetchall()

    print("Campañas activas encontradas: {}".format(len(campanas)))
    for config, nombre, fecha_inicio, fecha_fin in campanas:
        print("  Config: {} | Campaña: {} | {} -> {}".format(
            config, nombre, fecha_inicio, fecha_fin
        ))
    return campanas


# ============================================================
# SQL MERGE
# ============================================================

SQL_INSERT_STAGING = """
INSERT INTO VOUCHER_STAGE (
    RUN_ID, ID, VOUCHER_CONFIG, CAMPANA_VOUCHER, CODE, PROFORMA, AMOUNT,
    BRANCH_OFFICE, ADDITIONAL, GENERATED, PROFORMA_USED,
    BRANCH_OFFICE_USED, USED, EXPIRATION, DNI, CLIENT_ID, CORE_CLIENT_ID,
    KIND, COMPANY, KIND_LABEL, COMPANY_LABEL, STATUS_LABEL, STAGED_AT
) VALUES (
    :run_id, :id, :voucher_config, :campana_voucher, :code, :proforma, :amount,
    :branch_office, :additional, :generated, :proforma_used,
    :branch_office_used, :used, :expiration, :dni, :client_id, :core_client_id,
    :kind, :company, :kind_label, :company_label, :status_label, SYSTIMESTAMP
)
"""

SQL_MERGE_FROM_STAGING = """
MERGE INTO VOUCHERS t
USING (
    SELECT ID, VOUCHER_CONFIG, CAMPANA_VOUCHER, CODE, PROFORMA, AMOUNT,
           BRANCH_OFFICE, ADDITIONAL, GENERATED, PROFORMA_USED,
           BRANCH_OFFICE_USED, USED, EXPIRATION, DNI, CLIENT_ID,
           CORE_CLIENT_ID, KIND, COMPANY, KIND_LABEL, COMPANY_LABEL,
           STATUS_LABEL
    FROM (
        SELECT s.*,
               ROW_NUMBER() OVER (
                   PARTITION BY s.ID ORDER BY s.STAGED_AT DESC
               ) AS RN
        FROM VOUCHER_STAGE s
        WHERE s.RUN_ID = :run_id
          AND s.ID IS NOT NULL
    )
    WHERE RN = 1
) s
ON (t.ID = s.ID)
WHEN MATCHED THEN UPDATE SET
    t.VOUCHER_CONFIG = s.VOUCHER_CONFIG,
    t.CAMPANA_VOUCHER = s.CAMPANA_VOUCHER,
    t.CODE = s.CODE,
    t.PROFORMA = s.PROFORMA,
    t.AMOUNT = s.AMOUNT,
    t.BRANCH_OFFICE = s.BRANCH_OFFICE,
    t.ADDITIONAL = s.ADDITIONAL,
    t.GENERATED = s.GENERATED,
    t.PROFORMA_USED = s.PROFORMA_USED,
    t.BRANCH_OFFICE_USED = s.BRANCH_OFFICE_USED,
    t.USED = s.USED,
    t.EXPIRATION = s.EXPIRATION,
    t.DNI = s.DNI,
    t.CLIENT_ID = s.CLIENT_ID,
    t.CORE_CLIENT_ID = s.CORE_CLIENT_ID,
    t.KIND = s.KIND,
    t.COMPANY = s.COMPANY,
    t.KIND_LABEL = s.KIND_LABEL,
    t.COMPANY_LABEL = s.COMPANY_LABEL,
    t.STATUS_LABEL = s.STATUS_LABEL,
    t.FECHA_CARGA = SYSTIMESTAMP
WHEN NOT MATCHED THEN INSERT (
    ID, VOUCHER_CONFIG, CAMPANA_VOUCHER, CODE, PROFORMA, AMOUNT,
    BRANCH_OFFICE, ADDITIONAL, GENERATED, PROFORMA_USED,
    BRANCH_OFFICE_USED, USED, EXPIRATION, DNI, CLIENT_ID, CORE_CLIENT_ID,
    KIND, COMPANY, KIND_LABEL, COMPANY_LABEL, STATUS_LABEL, FECHA_CARGA
) VALUES (
    s.ID, s.VOUCHER_CONFIG, s.CAMPANA_VOUCHER, s.CODE, s.PROFORMA, s.AMOUNT,
    s.BRANCH_OFFICE, s.ADDITIONAL, s.GENERATED, s.PROFORMA_USED,
    s.BRANCH_OFFICE_USED, s.USED, s.EXPIRATION, s.DNI, s.CLIENT_ID,
    s.CORE_CLIENT_ID, s.KIND, s.COMPANY, s.KIND_LABEL, s.COMPANY_LABEL,
    s.STATUS_LABEL, SYSTIMESTAMP
)
"""


# ============================================================
# PREPARAR UN VOUCHER
# ============================================================

def preparar_fila(v, campana_voucher):

    return {

        "id":
            v.get("id"),

        "voucher_config":
            v.get("voucherConfig"),

        "campana_voucher":
            campana_voucher,

        "code":
            v.get("code"),

        "proforma":
            v.get("proforma"),

        "amount":
            v.get("amount"),

        "branch_office":
            v.get("branchOffice"),

        "additional":
            v.get("additional"),

        "generated":
            convertir_fecha(
                v.get("generated")
            ),

        "used":
            convertir_fecha(
                v.get("used")
            ),

        "expiration":
            convertir_fecha(
                v.get("expiration")
            ),

        "proforma_used":
            v.get("proformaUsed"),

        "branch_office_used":
            v.get("branchOfficeUsed"),

        "dni":
            v.get("dni"),

        "client_id":
            v.get("clientId"),

        "core_client_id":
            v.get("coreClientId"),

        "kind":
            v.get("kind"),

        "company":
            v.get("company"),

        "kind_label":
            v.get("kindLabel"),

        "company_label":
            v.get("companyLabel"),

        "status_label":
            v.get("statusLabel")
    }


# ============================================================
# CARGAR LOTE EN ORACLE
# ============================================================

def cargar_lote(cursor, connection, filas, run_id):
    """Inserta una página en staging; no hace MERGE fila por fila."""
    if not filas:
        return 0

    for fila in filas:
        fila["run_id"] = run_id

    total = 0
    for inicio in range(0, len(filas), ORACLE_BATCH_SIZE):
        lote = filas[inicio:inicio + ORACLE_BATCH_SIZE]
        cursor.executemany(
            SQL_INSERT_STAGING,
            lote,
            batcherrors=False
        )
        # Commit por lote para no mantener una transacción enorme durante la descarga.
        connection.commit()
        total += len(lote)
    return total


def aplicar_merge_staging(cursor, connection, run_id):
    """Aplica una sola operación set-based a todos los registros de esta ejecución."""
    print("Aplicando MERGE masivo desde staging a DETALLE_VOUCHER...")
    inicio = time.perf_counter()
    cursor.execute(SQL_MERGE_FROM_STAGING, run_id=run_id)
    filas_afectadas = cursor.rowcount
    connection.commit()
    print("MERGE finalizado en {:.1f}s. Filas afectadas reportadas por Oracle: {}".format(
        time.perf_counter() - inicio, filas_afectadas
    ))
    return filas_afectadas


# ============================================================
# PROCESAR UNA CAMPAÑA
# ============================================================

def procesar_campana(
    session,
    token,
    cursor,
    connection,
    voucher_config,
    campana_voucher,
    fecha_inicio,
    fecha_fin,
    run_id
):

    print("")
    print("")
    print("========================================")
    print("CAMPAÑA: {}".format(campana_voucher))
    print("VOUCHER_CONFIG: {}".format(voucher_config))
    print("FECHA INICIO: {}".format(fecha_inicio))
    print("FECHA FIN: {}".format(fecha_fin))
    print("========================================")

    pagina = 1

    total_api = 0
    total_staging = 0
    segundos_api = 0.0
    segundos_staging = 0.0

    while True:

        print(
            "Consultando pagina {}...".format(
                pagina
            )
        )

        inicio_api = time.perf_counter()
        vouchers = obtener_pagina(
            session=session,
            token=token,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            voucher_config=voucher_config,
            pagina=pagina
        )
        duracion_api = time.perf_counter() - inicio_api
        segundos_api += duracion_api

        cantidad = len(vouchers)

        print(
            "  Registros obtenidos: {}".format(
                cantidad
            )
        )

        if cantidad == 0:
            break

        total_api += cantidad

        filas = []

        for voucher in vouchers:
            fila = preparar_fila(voucher, campana_voucher)
            if fila["id"] is None:
                raise ValueError(
                    "La API devolvió un voucher sin id en configuración {}, página {}. "
                    "Se detiene para no perder ni mezclar registros.".format(voucher_config, pagina)
                )
            filas.append(fila)

        inicio_staging = time.perf_counter()
        cargados = cargar_lote(cursor, connection, filas, run_id)
        duracion_staging = time.perf_counter() - inicio_staging
        segundos_staging += duracion_staging
        total_staging += cargados

        print("  Tiempo API: {:.2f}s | staging Oracle: {:.2f}s".format(
            duracion_api, duracion_staging
        ))
        print("  Insertados en staging: {} | total campaña: {}".format(
            cargados, total_staging
        ))

        if cantidad < PAGE_LENGTH:
            break

        pagina += 1

    print("")
    print("----------------------------------------")
    print(
        "CAMPAÑA FINALIZADA: {}".format(
            campana_voucher
        )
    )
    print(
        "Total API: {}".format(
            total_api
        )
    )
    print(
        "Total staging: {}".format(
            total_staging
        )
    )
    print(
        "Paginas: {}".format(
            pagina
        )
    )
    print("----------------------------------------")

    print("Tiempo acumulado API: {:.1f}s | staging: {:.1f}s".format(
        segundos_api, segundos_staging
    ))
    return total_staging, total_api


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():
    # Dependencias de integración solo en ejecución conectada.
    global requests, oracledb
    import requests
    import oracledb
    required = [LOGIN_URL, VOUCHER_URL, USERNAME, PASSWORD, ORACLE_USER, ORACLE_PASSWORD, ORACLE_DSN]
    if not all(required):
        raise RuntimeError("Configura las variables de entorno documentadas antes de conectar.")
    inicio_proceso = time.perf_counter()
    connection = None
    cursor = None
    session = None
    run_id = str(uuid.uuid4())

    try:
        if not PASSWORD:
            raise RuntimeError("Define la variable de entorno VOUCHER_API_PASSWORD.")
        if not ORACLE_PASSWORD:
            raise RuntimeError("Define la variable de entorno VOUCHER_ORACLE_PASSWORD.")

        print("Inicializando Oracle...")
        if ORACLE_CLIENT:
            oracledb.init_oracle_client(lib_dir=ORACLE_CLIENT)
        connection = oracledb.connect(
            user=ORACLE_USER, password=ORACLE_PASSWORD, dsn=ORACLE_DSN
        )
        cursor = connection.cursor()
        print("Oracle conectado. RUN_ID={}".format(run_id))

        # Limpia únicamente ejecuciones abandonadas con más de 7 días.
        # No afecta a una ejecución activa reciente.
        cursor.execute(
            "DELETE FROM VOUCHER_STAGE WHERE STAGED_AT < SYSTIMESTAMP - INTERVAL '7' DAY"
        )
        connection.commit()

        campanas = obtener_campanas(cursor)
        if not campanas:
            print("No existen campañas activas en VOUCHER_CONFIG. No se modifica la tabla final.")
            return

        session = requests.Session()
        token = obtener_token(session)

        total_general = 0
        total_api_general = 0
        configuraciones_procesadas = 0

        for campana in campanas:
            voucher_config = campana[0]
            campana_voucher = campana[1]
            fecha_inicio = campana[2]
            fecha_fin = campana[3]

            if not fecha_inicio or not fecha_fin:
                raise ValueError(
                    "La campaña {} (configuración {}) no tiene fecha de inicio o fin.".format(
                        campana_voucher, voucher_config
                    )
                )

            total, total_api = procesar_campana(
                session=session,
                token=token,
                cursor=cursor,
                connection=connection,
                voucher_config=voucher_config,
                campana_voucher=campana_voucher,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                run_id=run_id
            )

            total_general += total
            total_api_general += total_api
            configuraciones_procesadas += 1

        # Integridad: el destino no se modifica hasta terminar correctamente la extracción.
        filas_merge = aplicar_merge_staging(cursor, connection, run_id)

        # Eliminar staging solo después de que el MERGE y el commit finalizaron correctamente.
        cursor.execute(
            "DELETE FROM VOUCHER_STAGE WHERE RUN_ID = :run_id",
            run_id=run_id
        )
        connection.commit()

        tiempo_total = time.perf_counter() - inicio_proceso
        print("\n========== PROCESO TERMINADO ==========")
        print("Configuraciones con registros: {}".format(configuraciones_procesadas))
        print("Registros recibidos de API: {}".format(total_api_general))
        print("Registros preparados en staging: {}".format(total_general))
        print("Filas afectadas por MERGE: {}".format(filas_merge))
        print("Duración total: {:.1f} minutos".format(tiempo_total / 60))
        print("=======================================")

    except Exception as e:
        print("ERROR GENERAL: {}".format(e))
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        print("Los registros de staging de RUN_ID={} se conservan para diagnóstico/recuperación.".format(run_id))
        raise
    finally:
        if session:
            session.close()
        if cursor:
            cursor.close()
        if connection:
            connection.close()
        print("Conexiones cerradas.")


# ============================================================
# EJECUCION
# ============================================================

if __name__ == "__main__":

    main()
