import os
import time
import pandas as pd
import cohere
import concurrent.futures
import unicodedata
import re
import json
import uuid
import requests
import numpy as np

from flask import Flask, request, render_template, send_from_directory, redirect, url_for, flash
from fpdf import FPDF
from io import BytesIO
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from datetime import datetime
import matplotlib
matplotlib.use('Agg')  # Reemplaza el backend de matplotlib
import matplotlib.pyplot as plt

app = Flask(__name__)
app.secret_key = 'supersecretkey'

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = 'src/uploads'
PDF_FOLDER = 'src/pdfs'
CHART_FOLDER = 'src/charts'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PDF_FOLDER, exist_ok=True)
os.makedirs(CHART_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
app.config['PDF_FOLDER'] = os.path.join(BASE_DIR, 'pdfs')
app.config['CHART_FOLDER'] = os.path.join(BASE_DIR, 'charts')

load_dotenv()

api_key = os.getenv("CO_API_KEY")
co = cohere.Client(api_key)

# Manejo de variables del excel
MAPA_PDFS_PATH = os.path.join(PDF_FOLDER, 'mapa_pdfs.json')
def cargar_mapa_pdfs():
    if os.path.exists(MAPA_PDFS_PATH):
        with open(MAPA_PDFS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}
def guardar_mapa_pdfs(mapa):
    with open(MAPA_PDFS_PATH, 'w', encoding='utf-8') as f:
        json.dump(mapa, f, indent=2, ensure_ascii=False)


#-------------------------
# Diccionarios de apoyo
#-------------------------

# Escala softskills
ESCALA_INTERPERSONAL = {
    "muy baja": 1,
    "baja": 2,
    "media": 3,
    "alta": 4,
    "muy alta": 5
}

# Alias de columnas
ALIAS_COLUMNAS = {
    "nombre": "Nombre Completo",
    "edad": "Edad",
    "correo": "Correo Electrónico",
    "estado civil": "Estado civil",
    "telefono": "Teléfono",
    "evaluador": "Evaluador",
    "grado de instruccion": "Grado de Instruccion",
    "fecha de evaluacion": "Fecha de evaluación",
    "carrera": "Carrera",
    "puesto": "Puesto Postulado",
    "nivel": "Nivel de Compatibilidad",
    "experiencia": "Experiencia (años)",
    "áreas": "Áreas de Experiencia",
    "plc": "PLC y Redes Industriales",
    "inglés": "Inglés",
    "proyectos": "Gestión de Proyectos",
    "interdisciplinario": "Trabajo Interdisciplinario",
    "proactividad": "Proactividad y Adaptación",
    "comunicación": "Comunicación",
    "equipo": "Trabajo en Equipo",
    "liderazgo": "Liderazgo",
    "resiliencia": "Resiliencia",
    "comentarios": "Comentarios Generales"
}

#------------------------
# Funciones auxiliares
#------------------------

def mapear_columna(col):
    col = col.lower()
    for clave, valor in ALIAS_COLUMNAS.items():
        if clave in col:
            return valor
    return col

def extraer_numero(nombre):
    match = re.search(r'(\d+)', nombre)
    return int(match.group()) if match else float('inf')

def limpiar_nombre(nombre):
    return re.sub(r'[^\w\s-]', '', nombre).strip().replace(' ', '_')

def normalizar(texto):
    if not isinstance(texto, str):
        texto = str(texto)
    texto = texto.strip().lower()
    texto = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('utf-8')
    return texto

def descargar_sheet_como_excel(sheet_url):
    try:
        # Extraer ID del documento
        match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_url)
        if not match:
            raise ValueError("URL inválida de Google Sheets")

        sheet_id = match.group(1)
        export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"

        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(export_url, headers=headers)

        if response.status_code == 200:
            # Generar nombre único
            unique_name = f"google_sheets_{uuid.uuid4().hex}.xlsx"
            ruta_destino = os.path.join('src','uploads', unique_name)
            with open(ruta_destino, 'wb') as f:
                f.write(response.content)
            return ruta_destino
        else:
            raise Exception(f"Error al descargar el archivo: {response.status_code}")

    except Exception as e:
        print("Error descargando el archivo de Google Sheets:", e)
        return None

#-------------------------------------
# Funciones para reporte de candidato
#-------------------------------------

def construir_prompt(datos, nombre_candidato):
    prompt = (
        f"Eres un reclutador senior. Redacta una evaluación clara, profesional y natural en español para el candidato {nombre_candidato}. "
        f"El informe debe iniciar con el subtítulo **Evaluación de {nombre_candidato}** y luego cubrir: resumen general, fortalezas, competencias técnicas, competencias interpersonales, experiencia relevante, oportunidades de mejora y una recomendación. "
        "No repitas información que ya esté en la sección de datos personales. No escribas encabezados como 'Evaluación de Selección' salvo el subtítulo mencionado. "
        "Organiza el contenido usando subtítulos marcados con **, por ejemplo: **Fortalezas**. "
        "Evita listas con guiones. El texto debe ser fluido, coherente, y no debe parecer una lista. "
        "Máximo 500 palabras por secciones. Todo debe parecer redactado por un humano con criterio profesional."
    )
    for k, v in datos.items():
        prompt += f"\n{k}: {v}"
    return prompt

def crear_pdf(nombre_archivo, datos_resumen, informe_texto):
    pdf = FPDF()
    pdf.set_left_margin(25)
    pdf.set_right_margin(25)
    pdf.add_page()

    pdf.set_font("Times", "B", 16)
    pdf.cell(0, 10, "INFORME DE EVALUACIÓN DEL CANDIDATO", ln=True, align="C")
    pdf.ln(5)

    pdf.set_font("Times", "B", 12)
    pdf.cell(0, 10, "DATOS PERSONALES", ln=True)

    campos_orden = [
        "Nombre Completo", "Edad", "Estado civil", "Teléfono",
        "Evaluador", "Grado de Instruccion", "Carrera", "Puesto Postulado",
        "Fecha de evaluación", "Correo Electrónico"
    ]

    etiqueta_width = 60
    separador_width = 5
    valor_width = 0

    for campo in campos_orden:
        posibles_keys = [k for k in datos_resumen if campo.lower().strip() in k.lower().strip()]
        if posibles_keys:
            key = posibles_keys[0]
            valor_raw = datos_resumen[key]
            if pd.isna(valor_raw):
                valor = ""
            elif isinstance(valor_raw, float):
                valor = str(int(valor_raw))
            elif isinstance(valor_raw, datetime):
                valor = valor_raw.strftime("%d/%m/%Y")
            else:
                valor = str(valor_raw).strip()

            pdf.set_font("Times", "B", 11)
            pdf.cell(etiqueta_width, 8, campo.upper(), ln=False)
            pdf.cell(separador_width, 8, ":", ln=False)
            pdf.set_font("Times", "", 11)
            pdf.cell(valor_width, 8, valor, ln=True)

    pdf.ln(5)

    secciones = re.split(r'(\*\*[^*]+\*\*)', informe_texto)
    for i, seccion in enumerate(secciones):
        if seccion.startswith("**") and seccion.endswith("**"):
            titulo = seccion.strip("*.").strip().upper()
            pdf.set_font("Times", "B", 12)
            pdf.cell(0, 8, titulo, ln=True)
            pdf.ln(2)

            # Revisión flexible de subtítulo interpersonal
            if any(palabra in titulo.lower() for palabra in ["interpersonales", "habilidades blandas", "soft skills"]):
                nombre_base = limpiar_nombre(nombre_archivo.replace('.pdf', ''))
                nombre_img = f"{nombre_base}_interpersonal.png"
                ruta_img = generar_grafico_interpersonal(datos_resumen, nombre_img)
                if ruta_img and os.path.exists(ruta_img):
                    pdf.image(ruta_img, x=30, w=150)
                    pdf.ln(5)

        else:
            pdf.set_font("Times", "", 11)
            parrafos = seccion.strip().split('\n')
            for parrafo in parrafos:
                if parrafo.strip():
                    pdf.multi_cell(0, 8, parrafo.strip())
                    pdf.ln(1)

    pdf.output(os.path.join(PDF_FOLDER, nombre_archivo))

def generar_grafico_interpersonal(datos, nombre_archivo):
    habilidades = []
    valores = []

    datos_normalizados = {normalizar(k): normalizar(v) for k, v in datos.items()}

    for campo in [
        "Trabajo en Equipo", "Comunicación", "Liderazgo",
        "Resiliencia", "Proactividad y Adaptación"
    ]:
        clave_norm = normalizar(campo)
        if clave_norm in datos_normalizados:
            valor_norm = datos_normalizados[clave_norm]
            if valor_norm in ESCALA_INTERPERSONAL:
                habilidades.append(campo)  # conservar el original con mayúsculas para el gráfico
                valores.append(ESCALA_INTERPERSONAL[valor_norm])

    if habilidades:
        plt.figure(figsize=(6, 3.5))
        bars = plt.barh(habilidades, valores, color='#4A90E2', height=0.4)
        plt.title("Habilidades Blandas", fontsize=12)
        plt.xlim(0, 5.5)
        plt.xticks([1, 2, 3, 4, 5])
        plt.yticks(fontsize=9)
        plt.xlabel("Nivel", fontsize=10)
        plt.grid(axis='x', linestyle='--', alpha=0.6)

        for bar in bars:
            width = bar.get_width()
            plt.text(width + 0.1, bar.get_y() + bar.get_height() / 2, f'{int(width)}', va='center', fontsize=9)

        plt.tight_layout()
        ruta_imagen = os.path.join(CHART_FOLDER, nombre_archivo)
        plt.savefig(ruta_imagen)
        plt.close()
        return ruta_imagen
    return None

def generar_informe_y_pdf(index, fila, reintentos=3, espera_base=2):
    try:
        datos_candidato = {
            mapear_columna(col): fila[col]
            for col in fila.index
            if pd.notna(fila[col]) and str(fila[col]).strip() != ""
        }

        columna_nombre = next((col for col in fila.index if "nombre" in col.lower()), None)
        nombre_candidato = str(fila[columna_nombre]) if columna_nombre and pd.notna(fila[columna_nombre]) else f"candidato_{index+1}"
        nombre_archivo_pdf = limpiar_nombre(nombre_candidato) + ".pdf"
        ruta_pdf = os.path.join(PDF_FOLDER, nombre_archivo_pdf)

        if os.path.exists(ruta_pdf):
            print(f"{nombre_archivo_pdf} ya existe, será actualizado.")
            os.remove(ruta_pdf)

        print(f"Procesando candidato {index + 1}: {nombre_candidato}")

        datos_prompt = {k: v for k, v in datos_candidato.items() if k not in [
            "Nombre Completo", "Edad", "Estado civil", "Teléfono", "Evaluador", "Grado de Instruccion",
            "Carrera", "Puesto Postulado", "Fecha de evaluación", "Correo Electrónico"]}

        prompt = construir_prompt(datos_prompt, nombre_candidato)
        response = co.generate(
            model="command-r-plus",
            prompt=prompt,
            max_tokens=800,
            temperature=0.4
        )
        informe = response.generations[0].text.strip()

        crear_pdf(nombre_archivo_pdf, datos_candidato, informe)
        print(f"PDF creado: {nombre_archivo_pdf}")

        # Registrar nombre original del candidato
        mapa_actual = cargar_mapa_pdfs()
        mapa_actual[nombre_archivo_pdf] = nombre_candidato
        guardar_mapa_pdfs(mapa_actual)
        return True

    except Exception as e:
        print(f"[Error] Índice {index}: {e}")
        return False

#-------------------------------------
# Funciones para reporte comparativo
#-------------------------------------
def construir_prompt_comparativo(lista_datos):
    prompt = (
       "Eres un reclutador senior con amplia experiencia evaluando candidatos. "
        "Redacta un informe comparativo claro, profesional y natural en español para un grupo de candidatos evaluados. "
        "El informe debe cubrir las siguientes secciones: **Resumen General Comparativo**, **Fortalezas**, **Competencias Técnicas**, **Competencias Interpersonales**, **Experiencia Relevante**, **Oportunidades de Mejora** y una **Recomendación General**.\n\n"

        "En cada sección, **compara directamente el desempeño entre los candidatos**. No te limites a enumerar habilidades o cualidades: **explica quién destaca más, quién tiene un desempeño medio y quién muestra debilidades**, y en qué aspectos concretos. "
        "Utiliza frases como 'el candidato X demuestra un nivel más alto en...', 'en comparación con Y, Z muestra una menor habilidad para...', 'mientras que...', etc. "
        "Haz que el análisis sea claro y útil para tomar decisiones. Evita repeticiones innecesarias y referencias a los datos personales.\n\n"

        "Usa subtítulos marcados con doble asterisco (**), por ejemplo: **Fortalezas**. "
        "No uses listas con guiones; redacta párrafos coherentes, fluidos, y bien estructurados. "
        "Máximo 1000 palabras por sección. "
        "Todo el informe debe parecer escrito por un profesional con criterio experto y lenguaje natural, no por una IA.\n\n"
        "Aquí están los datos relevantes de cada candidato:\n")

    for idx, datos in enumerate(lista_datos, start=1):
        prompt += f"\n\nCandidato {idx}:\n"
        for k, v in datos.items():
            prompt += f"{k}: {v}\n"
    return prompt

def generar_texto_comparativo(prompt):
    try:
        response = co.generate(
            model="command-r-plus",
            prompt=prompt,
            max_tokens=2500,
            temperature=0.7,
            stop_sequences=["--"],
        )
        texto = response.generations[0].text.strip()
        return texto
    except Exception as e:
        print("Error al generar texto comparativo con Cohere:", e)
        return "No se pudo generar el informe comparativo."

def crear_grafico_radar_comparativo(datos_candidatos, nombre_archivo):
    etiquetas = ["Liderazgo", "Comunicación", "Trabajo en equipo", "Resiliencia"]
    etiquetas_norm = [normalizar(e) for e in etiquetas]

    candidatos = list(datos_candidatos.keys())
    valores_por_candidato = []

    # Calcular ángulos antes de cerrar el círculo
    angulos = np.linspace(0, 2 * np.pi, len(etiquetas), endpoint=False).tolist()
    angulos.append(angulos[0])  # cerrar el radar

    for nombre in candidatos:
        datos = datos_candidatos[nombre]
        datos_normalizados = {normalizar(k): normalizar(v) for k, v in datos.items()}
        valores = [
            ESCALA_INTERPERSONAL.get(datos_normalizados.get(etq, ""), 0)
            for etq in etiquetas_norm
        ]
        valores.append(valores[0])  # cerrar el radar
        valores_por_candidato.append(valores)

    fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))
    colores = ['#FF5733', '#33B5FF', '#8D33FF', '#33FF91', '#FFC733', '#FF33B8']

    for i, valores in enumerate(valores_por_candidato):
        ax.plot(angulos, valores, label=candidatos[i], linewidth=2, color=colores[i % len(colores)])
        ax.fill(angulos, valores, alpha=0.15, color=colores[i % len(colores)])

    ax.set_xticks(angulos[:-1])
    ax.set_xticklabels(etiquetas, fontsize=9)
    ax.set_yticks(range(1, 6))
    ax.set_yticklabels([str(i) for i in range(1, 6)], fontsize=8)
    ax.set_ylim(0, 5)
    plt.title("Comparativa de Competencias Interpersonales", fontsize=13)
    plt.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1), fontsize=8)
    plt.tight_layout()

    ruta_imagen = os.path.join(CHART_FOLDER, nombre_archivo)
    plt.savefig(ruta_imagen)
    plt.close()
    return ruta_imagen

def generar_pdf_comparativo(nombre_archivo, seleccionados):
    mapa_nombres = cargar_mapa_pdfs()
    ruta_uploads = os.path.join('src','uploads')
    archivos_excel = [f for f in os.listdir(ruta_uploads) if f.endswith('.xlsx')]

    filas_candidatos = []
    datos_interpersonales = {}

    for archivo_pdf in seleccionados:
        nombre_pdf = os.path.splitext(archivo_pdf)[0].lower()
        nombre_real = mapa_nombres.get(archivo_pdf, None)
        encontrado = False

        if not nombre_real:
            filas_candidatos.append({
                'Nombre': archivo_pdf,
                'Correo': 'No disponible',
                'Teléfono': 'No disponible',
                'Grado de Instruccion': 'No disponible',
                'Estado civil': 'No disponible',
                'Evaluador': 'No disponible',
            })
            continue

        nombre_normalizado = normalizar(nombre_real)

        # Buscar el candidato en todos los archivos Excel
        for archivo_excel in archivos_excel:
            ruta_excel = os.path.join(ruta_uploads, archivo_excel)
            try:
                df = pd.read_excel(ruta_excel)
                nombres_df = df[ALIAS_COLUMNAS['nombre']].dropna().astype(str).str.lower().apply(normalizar)

                coincidencias = df[nombres_df.str.contains(nombre_normalizado, na=False)]
                if not coincidencias.empty:
                    fila = coincidencias.iloc[0]
                    fila_dict = {
                        'Nombre': fila.get(ALIAS_COLUMNAS['nombre'], 'No disponible'),
                        'Correo': fila.get(ALIAS_COLUMNAS['correo'], 'No disponible'),
                        'Teléfono': fila.get(ALIAS_COLUMNAS['telefono'], 'No disponible'),
                        'Grado de Instruccion': fila.get(ALIAS_COLUMNAS['grado de instruccion'], 'No disponible'),
                        'Estado civil': fila.get(ALIAS_COLUMNAS['estado civil'], 'No disponible'),
                        'Evaluador': fila.get(ALIAS_COLUMNAS['evaluador'], 'No disponible'),
                    }

                    datos_interpersonales[fila_dict['Nombre']] = {
                        'Trabajo en Equipo': fila.get(ALIAS_COLUMNAS.get("equipo", ""), ""),
                        'Comunicación': fila.get(ALIAS_COLUMNAS.get("comunicación", ""), ""),
                        'Liderazgo': fila.get(ALIAS_COLUMNAS.get("liderazgo", ""), ""),
                        'Resiliencia': fila.get(ALIAS_COLUMNAS.get("resiliencia", ""), ""),
                        'Proactividad y Adaptación': fila.get(ALIAS_COLUMNAS.get("proactividad y adaptacion", ""), ""),
                    }

                    filas_candidatos.append(fila_dict)
                    encontrado = True
                    break
            except Exception as e:
                print(f"[Error] Procesando {archivo_excel}: {e}")

        if not encontrado:
            filas_candidatos.append({
                'Nombre': nombre_real,
                'Correo': 'No disponible',
                'Teléfono': 'No disponible',
                'Grado de Instruccion': 'No disponible',
                'Estado civil': 'No disponible',
                'Evaluador': 'No disponible',
            })

    # PDF con formato mejorado
    pdf = FPDF()
    pdf.set_left_margin(25)
    pdf.set_right_margin(25)
    pdf.add_page()

    pdf.set_font("Times", "B", 16)
    pdf.cell(0, 10, "INFORME COMPARATIVO DE CANDIDATOS", ln=True, align="C")
    pdf.ln(10)

    etiqueta_width = 60
    separador_width = 5
    valor_width = 0

    for i, fila in enumerate(filas_candidatos, start=1):
        pdf.set_font("Times", "B", 12)
        pdf.cell(0, 10, f"CANDIDATO {i}", ln=True)
        pdf.ln(2)

        for campo in ["Nombre", "Correo", "Teléfono", "Grado de Instruccion", "Estado civil", "Evaluador"]:
            valor = str(fila.get(campo, "")).strip()
            pdf.set_font("Times", "B", 11)
            pdf.cell(etiqueta_width, 8, campo.upper(), ln=False)
            pdf.cell(separador_width, 8, ":", ln=False)
            pdf.set_font("Times", "", 11)
            pdf.cell(valor_width, 8, valor, ln=True)

        pdf.ln(5)

    # Generar texto comparativo
    prompt_comparativo = construir_prompt_comparativo(filas_candidatos)
    texto_informe = generar_texto_comparativo(prompt_comparativo)

    # Dividir el texto por secciones
    secciones = re.split(r'(\*\*[^*]+\*\*)', texto_informe)
    
    for i, seccion in enumerate(secciones):
        if seccion.startswith("**") and seccion.endswith("**"):
            titulo = seccion.strip("*.").strip().upper()
            pdf.set_font("Times", "B", 12)
            pdf.cell(0, 8, titulo, ln=True)
            pdf.ln(2)
            
            # Si es la sección de competencias interpersonales, insertar el gráfico radar
            if any(palabra in titulo.lower() for palabra in ["interpersonales", "habilidades blandas", "soft skills"]):
                nombre_img = f"interpersonal_radar_{uuid.uuid4().hex[:6]}.png"
                ruta_grafico = crear_grafico_radar_comparativo(datos_interpersonales, nombre_img)
                if ruta_grafico and os.path.exists(ruta_grafico):
                    pdf.image(ruta_grafico, w=140)
                    pdf.ln(5)


        else:
            pdf.set_font("Times", "", 11)
            parrafos = seccion.strip().split('\n')
            for parrafo in parrafos:
                if parrafo.strip():
                    pdf.multi_cell(0, 8, parrafo.strip())
                    pdf.ln(1)

    ruta_salida = os.path.join( 'src','pdfs', nombre_archivo)
    pdf.output(ruta_salida)
    return ruta_salida

#------------------------------------------
# Rutas a diferentes pantallas y procesos 
#------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/procesar', methods=['POST'])
def procesar():
    archivo = request.files.get('archivo')
    sheet_url = request.form.get('sheet_url', '').strip()
    df = None

    # Caso 1: se subió un archivo
    if archivo and archivo.filename:
        nombre_archivo = secure_filename(archivo.filename)
        ruta_guardado = os.path.join(app.config['UPLOAD_FOLDER'], nombre_archivo)
        archivo.save(ruta_guardado)
        df = pd.read_excel(ruta_guardado)
        print(f"Archivo Excel cargado localmente: {nombre_archivo}")
    
    # Caso 2: se ingresó un enlace a Google Sheets
    elif sheet_url:
        if "docs.google.com/spreadsheets" in sheet_url:
            try:
                # Descargar con nombre único
                ruta_excel = descargar_sheet_como_excel(sheet_url)
                if ruta_excel is None or not os.path.exists(ruta_excel):
                    return "No se pudo descargar el archivo desde Google Sheets.", 400

                df = pd.read_excel(ruta_excel)
                print(f"Google Sheet guardado como Excel en: {ruta_excel}")

            except Exception as e:
                return f"Error al procesar Google Sheet: {e}", 400
        else:
            return "El enlace proporcionado no es válido para Google Sheets.", 400

    else:
        return "Debe subir un archivo Excel o proporcionar un enlace válido de Google Sheets.", 400

    print(f"Total filas a procesar: {len(df)}")

    # Procesamiento paralelo
    fallidos = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_index = {executor.submit(generar_informe_y_pdf, idx, fila): idx for idx, fila in df.iterrows()}
        for future in concurrent.futures.as_completed(future_to_index):
            idx = future_to_index[future]
            try:
                if not future.result():
                    fallidos.append((idx, df.iloc[idx]))
            except Exception as e:
                print(f"[Error] Índice {idx} al procesar en paralelo: {e}")
                fallidos.append((idx, df.iloc[idx]))

    # Reintentos
    if fallidos:
        print(f"🔁 Reintentando {len(fallidos)} candidatos fallidos...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as retry_executor:
            retry_futures = [
                retry_executor.submit(generar_informe_y_pdf, idx, fila) for idx, fila in fallidos
            ]
            concurrent.futures.wait(retry_futures)

    return redirect(url_for('listar_pdfs'))

@app.route('/eliminar', methods=['POST'])
def eliminar_multiples():
    seleccionados_str = request.form.get('seleccionados', '')
    if not seleccionados_str:
        flash("Debe seleccionar al menos un archivo para eliminar.")
        return redirect(url_for('listar_pdfs'))

    seleccionados = seleccionados_str.split(',')
    eliminados = []
    no_encontrados = []

    for archivo in seleccionados:
        ruta = os.path.join(PDF_FOLDER, archivo)
        if os.path.exists(ruta):
            os.remove(ruta)
            eliminados.append(archivo)
        else:
            no_encontrados.append(archivo)

    if eliminados:
        flash(f"Archivos eliminados correctamente: {', '.join(eliminados)}")
    if no_encontrados:
        flash(f"No se encontraron los archivos: {', '.join(no_encontrados)}")

    return redirect(url_for('listar_pdfs'))

@app.route('/comparar', methods=['POST'])
def comparar_candidatos():
    seleccionados = request.form.getlist('seleccionados')
    if not (3 <= len(seleccionados) <= 6):
        flash("Debe seleccionar entre 3 y 6 candidatos para generar el informe comparativo.")
        return redirect(url_for('listar_pdfs'))

    mapa_nombres = cargar_mapa_pdfs()
    filas_candidatos = []

    for archivo_pdf in seleccionados:
        nombre_candidato = mapa_nombres.get(archivo_pdf, "Nombre Desconocido")
        fila = {
            'Nombre': nombre_candidato,
            'Correo': 'No disponible',
            'Teléfono': 'No disponible',
            'Grado de Instruccion': 'No disponible',
            'Estado civil': 'No disponible',
            'Evaluador': 'No disponible'
        }
        filas_candidatos.append(fila)

    nombre_comparativo = f"Reporte_Comparativo_{uuid.uuid4().hex[:8]}.pdf"
    ruta_pdf = generar_pdf_comparativo(nombre_comparativo, seleccionados)
    
    # Aquí podrías registrar el PDF comparativo como los demás
    return redirect(url_for('listar_pdfs'))

@app.route('/ver_pdf/<nombre>')
def ver_pdf(nombre):
    ruta_completa = os.path.join(app.config['PDF_FOLDER'], nombre)
    print(f"INTENTANDO VER: {ruta_completa}")
    print("¿Existe?", os.path.exists(ruta_completa))
    return send_from_directory(app.config['PDF_FOLDER'], nombre)

@app.route('/pdfs')
def listar_pdfs():
    archivos = os.listdir(PDF_FOLDER)
    archivos = [f for f in archivos if f.endswith(".pdf")]
    archivos.sort(key=extraer_numero)
    return render_template('pdfs.html', archivos=archivos)

@app.route('/descargar_pdf/<nombre>')
def descargar_pdf(nombre):
    return send_from_directory(app.config['PDF_FOLDER'], nombre, as_attachment=True)


if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5000)
