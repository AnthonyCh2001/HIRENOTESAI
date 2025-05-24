import os
import time
import pandas as pd
import cohere
import concurrent.futures
import unicodedata
import re
from flask import Flask, request, render_template, send_from_directory, redirect, url_for, flash
from fpdf import FPDF
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from datetime import datetime
import matplotlib
matplotlib.use('Agg')  # Reemplaza el backend de matplotlib
import matplotlib.pyplot as plt

app = Flask(__name__)
app.secret_key = 'supersecretkey'

UPLOAD_FOLDER = 'src/uploads'
PDF_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pdfs')
os.makedirs(PDF_FOLDER, exist_ok=True)
CHART_FOLDER = 'src/static/charts'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PDF_FOLDER, exist_ok=True)
os.makedirs(CHART_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
load_dotenv()

api_key = os.getenv("CO_API_KEY")
co = cohere.Client(api_key)

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

def mapear_columna(col):
    col = col.lower()
    for clave, valor in ALIAS_COLUMNAS.items():
        if clave in col:
            return valor
    return col




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


def normalizar(texto):
    if not isinstance(texto, str):
        texto = str(texto)
    texto = texto.strip().lower()
    texto = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('utf-8')
    return texto

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
        return True

    except Exception as e:
        print(f"[Error] Índice {index}: {e}")
        return False

def extraer_numero(nombre):
    match = re.search(r'(\d+)', nombre)
    return int(match.group()) if match else float('inf')

def limpiar_nombre(nombre):
    return re.sub(r'[^\w\s-]', '', nombre).strip().replace(' ', '_')


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/procesar', methods=['POST'])
def procesar():
    archivo = request.files['archivo']
    if not archivo:
        return "Archivo no válido", 400

    nombre_archivo = secure_filename(archivo.filename)
    ruta_guardado = os.path.join(app.config['UPLOAD_FOLDER'], nombre_archivo)
    archivo.save(ruta_guardado)

    df = pd.read_excel(ruta_guardado)
    print(f"Total filas en Excel: {len(df)}")

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

    if fallidos:
        print(f"Reintentando {len(fallidos)} candidatos fallidos en paralelo...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as retry_executor:
            retry_futures = [
                retry_executor.submit(generar_informe_y_pdf, idx, fila) for idx, fila in fallidos
            ]
            concurrent.futures.wait(retry_futures)

    return redirect(url_for('listar_pdfs'))

@app.route('/pdfs')
def listar_pdfs():
    archivos = os.listdir(PDF_FOLDER)
    archivos = [f for f in archivos if f.endswith(".pdf")]
    archivos.sort(key=extraer_numero)
    return render_template('pdfs.html', archivos=archivos)

@app.route('/eliminar/<nombre>', methods=['POST'])
def eliminar(nombre):
    ruta = os.path.join(PDF_FOLDER, nombre)
    if os.path.exists(ruta):
        os.remove(ruta)
        flash(f"{nombre} eliminado correctamente.")
    else:
        flash(f"No se encontró el archivo {nombre}.")
    return redirect(url_for('listar_pdfs'))

@app.route('/descargar/<nombre>')
def descargar(nombre):
    return send_from_directory(PDF_FOLDER, nombre, as_attachment=True)

@app.route('/ver_pdf/<nombre>')
def ver_pdf(nombre):
    return send_from_directory(PDF_FOLDER, nombre)

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5000)
