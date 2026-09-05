import os
import gzip
import copy
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# ==============================================================================
# CONFIGURACIÓN
# ==============================================================================

# URL base en RAW de GitHub donde están los XML por categoría de tu otro repositorio.
# Ejemplo: "https://raw.githubusercontent.com/TU_USUARIO/TU_REPO/main"
URL_BASE_REPO = "https://raw.githubusercontent.com/nowmoretv/extra-epg-pro-categories/main"

GRUPOS = {
    "epg_principal": [
        "epg_deportes.xml",
        "epg_cine.xml",
        "epg_series.xml",
        "epg_entretenimiento.xml",
        "epg_nacionales.xml",
        "epg_regionales.xml",
        "epg_locales.xml"
    ],
    "epg_exterior": [
        "epg_europa.xml",
        "epg_norteamerica.xml",
        "epg_centroamerica.xml",
        "epg_sudamerica.xml",
        "epg_asia.xml",
        "epg_oceania.xml",
        "epg_africa.xml"
    ]
}

# epg_total procesará todos los archivos combinados de principal + exterior
# (si tienes categorías adicionales en el futuro, agrégalas a esta lista)
ARCHIVOS_TOTAL = list(dict.fromkeys(GRUPOS["epg_principal"] + GRUPOS["epg_exterior"]))

HORAS_VENTANA = 6

# ==============================================================================
# UTILIDADES DE FECHA Y DESCARGA
# ==============================================================================

def parsear_fecha_epg(fecha_str):
    """Convierte cadenas formato XMLTV (YYYYmmddHHMMSS ...) a objeto datetime en UTC."""
    if not fecha_str:
        return None
    try:
        clean = fecha_str.split()[0][:14]
        return datetime.strptime(clean, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None

def descargar_xml(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            return ET.fromstring(data)
    except Exception as e:
        print(f"    ⚠️ No se pudo descargar/leer {url}: {e}")
        return None

# ==============================================================================
# PROCESAMIENTO Y GENERACIÓN
# ==============================================================================

def limpiar_programa(prog_elem, es_cine):
    """
    Conserva exclusivamente <title>.
    Si es_cine es True, también conserva <desc>. Todo lo demás se elimina.
    """
    etiquetas_permitidas = {"title", "desc"} if es_cine else {"title"}

    for hijo in list(prog_elem):
        if hijo.tag not in etiquetas_permitidas:
            prog_elem.remove(hijo)

def exportar_archivos(root_tv, nombre_base):
    """Guarda tanto el archivo .xml legible como el .xml.gz comprimido."""
    nombre_xml = f"{nombre_base}.xml"
    nombre_gz = f"{nombre_base}.xml.gz"

    tree = ET.ElementTree(root_tv)
    ET.indent(tree, space="  ", level=0)
    
    # 1. Guardar XML
    tree.write(nombre_xml, encoding="utf-8", xml_declaration=True)
    print(f"    ✔ Generado: {nombre_xml}")

    # 2. Guardar XML.GZ
    with open(nombre_xml, "rb") as f_in, gzip.open(nombre_gz, "wb", compresslevel=9) as f_out:
        f_out.writelines(f_in)
    print(f"    ✔ Generado: {nombre_gz}")

def construir_guia(nombre_grupo, lista_archivos, ahora, limite_futuro):
    print(f"\n--> Generando '{nombre_grupo}'...")
    root_out = ET.Element("tv", generator_info_name=f"EPG Aggregator - {nombre_grupo}")
    
    canales_registrados = set()
    programas_por_canal = {}

    for archivo_xml in lista_archivos:
        url = f"{URL_BASE_REPO.rstrip('/')}/{archivo_xml}"
        print(f"    Descargando {archivo_xml}...")
        root_fuente = descargar_xml(url)
        if root_fuente is None:
            continue

        es_cine = (archivo_xml == "epg_cine.xml")

        # 1. Registrar canales únicos (limpios y ultra ligeros)
        for channel in root_fuente.findall("channel"):
            c_id = channel.get("id")
            if c_id and c_id not in canales_registrados:
                ch_limpio = ET.Element("channel", id=c_id)
                
                # Conservamos solo un display-name básico con el propio id (estándar XMLTV seguro)
                dn = ET.SubElement(ch_limpio, "display-name")
                dn.text = c_id
                
                root_out.append(ch_limpio)
                canales_registrados.add(c_id)

        # 2. Procesar programas y filtrar ventana horaria
        for prog in root_fuente.findall("programme"):
            c_id = prog.get("channel")
            start_dt = parsear_fecha_epg(prog.get("start"))
            stop_dt = parsear_fecha_epg(prog.get("stop"))

            if not c_id or not start_dt:
                continue

            # Caso A: Está en emisión actualmente
            en_emision = (stop_dt and start_dt <= ahora < stop_dt)
            # Caso B: Comienza dentro de las próximas 6 horas
            proximo = (ahora <= start_dt <= limite_futuro)

            if en_emision or proximo:
                if c_id not in programas_por_canal:
                    programas_por_canal[c_id] = []

                p_copy = copy.deepcopy(prog)
                limpiar_programa(p_copy, es_cine)
                programas_por_canal[c_id].append((start_dt, p_copy))

    # Incorporar los programas ordenados cronológicamente por canal
    total_programas = 0
    for c_id, progs in programas_por_canal.items():
        # Evitar programas duplicados si un canal está repetido en varias fuentes
        vistos = set()
        progs_ordenados = sorted(progs, key=lambda x: x[0])
        for dt, p_elem in progs_ordenados:
            clave_prog = (p_elem.get("channel"), p_elem.get("start"), (p_elem.findtext("title") or "").strip())
            if clave_prog not in vistos:
                root_out.append(p_elem)
                vistos.add(clave_prog)
                total_programas += 1

    print(f"    Canales únicos: {len(canales_registrados)} | Programas añadidos: {total_programas}")
    exportar_archivos(root_out, nombre_grupo)

def main():
    ahora = datetime.now(timezone.utc)
    limite_futuro = ahora + timedelta(hours=HORAS_VENTANA)

    print(f"=== EPG AGGREGATOR INICIADO ===")
    print(f"Hora actual (UTC): {ahora.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Límite máximo (UTC, +{HORAS_VENTANA}h): {limite_futuro.strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. epg_total
    construir_guia("epg_total", ARCHIVOS_TOTAL, ahora, limite_futuro)

    # 2. epg_principal
    construir_guia("epg_principal", GRUPOS["epg_principal"], ahora, limite_futuro)

    # 3. epg_exterior
    construir_guia("epg_exterior", GRUPOS["epg_exterior"], ahora, limite_futuro)

    print("\n✔ Todos los grupos .xml y .xml.gz se han generado correctamente.")

if __name__ == "__main__":
    main()
