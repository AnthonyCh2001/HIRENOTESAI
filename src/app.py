import os
import time
import pandas as pd
import cohere
import concurrent.futures
import re
from flask import Flask, request, render_template, send_from_directory, redirect, url_for, flash, jsonify
from fpdf import FPDF
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Configurar Flask
app = Flask(__name__)
app.secret_key = 'supersecretkey'
UPLOAD_FOLDER = 'src/uploads'
PDF_FOLDER = 'src/static/pdfs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PDF_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
load_dotenv()

# Conectar con Cohere
api_key = os.getenv("CO_API_KEY")
co = cohere.Client(api_key)

# Estado de progreso global
progreso = {
    "total": 0,
    "procesados": 0
}

ALIAS_COLUMNAS = {
    "nombre": "Nombre Completo",
    "edad": "Edad",
    "correo": "Correo Electrónico",
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

def construir_prompt(datos):
    prompt = "Eres un reclutador senior. Redacta una evaluación clara, profesional y natural en español para informes de selección. Analiza todas las competencias del candidato proporcionadas, agrupadas y por separado: técnicas, interpersonales y cualquier otra. Destaca fortalezas, áreas de mejora y relación de estas con el puesto. Cierra con una recomendación argumentada sobre su continuidad en el proceso. Evita repetir datos textuales, sonar genérico o redundante. Que la variable de evaluacion del reclutador sea de 3800 a 4000 palabras."

    for k, v in datos.items():
        prompt += f"{k}: {v}\n"
    prompt += "\nEl texto debe parecer escrito por un humano con criterio. No más de 300 palabras."
    return prompt

def crear_pdf(nombre_archivo, datos_resumen, informe_texto):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "Informe de Evaluación del Candidato", ln=True, align="C")
    pdf.ln(10)

    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Datos Personales:", ln=True)
    pdf.ln(4)
    pdf.set_font("Arial", "", 11)
    for campo in ["Nombre Completo", "Edad", "Correo Electrónico", "Carrera", "Puesto Postulado"]:
        if campo in datos_resumen:
            pdf.set_font("Arial", "B", 11)
            pdf.cell(60, 8, f"{campo}", border=1)
            pdf.set_font("Arial", "", 11)
            pdf.cell(120, 8, str(datos_resumen[campo]), border=1, ln=True)
    pdf.ln(5)

    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Conocimientos Técnicos:", ln=True)
    pdf.ln(4)
    pdf.set_font("Arial", "", 11)
    for campo in ["Nivel de Compatibilidad", "Experiencia (años)", "Áreas de Experiencia",
                  "PLC y Redes Industriales", "Inglés", "Gestión de Proyectos"]:
        if campo in datos_resumen:
            pdf.set_font("Arial", "B", 11)
            pdf.cell(60, 8, f"{campo}", border=1)
            pdf.set_font("Arial", "", 11)
            pdf.cell(120, 8, str(datos_resumen[campo]), border=1, ln=True)
    pdf.ln(5)

    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Habilidades Blandas:", ln=True)
    pdf.ln(4)
    pdf.set_font("Arial", "", 11)
    for campo in ["Trabajo Interdisciplinario", "Proactividad y Adaptación", "Comunicación",
                  "Trabajo en Equipo", "Liderazgo", "Resiliencia"]:
        if campo in datos_resumen:
            pdf.set_font("Arial", "B", 11)
            pdf.cell(60, 8, f"{campo}", border=1)
            pdf.set_font("Arial", "", 11)
            pdf.cell(120, 8, str(datos_resumen[campo]), border=1, ln=True)

    if "Comentarios Generales" in datos_resumen:
        pdf.ln(10)
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 10, "Comentarios Generales:", ln=True)
        pdf.set_font("Arial", "", 11)
        pdf.multi_cell(0, 8, str(datos_resumen["Comentarios Generales"]))

    pdf.add_page()
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Evaluación del Reclutador:", ln=True)
    pdf.ln(2)
    pdf.set_font("Arial", "", 11)
    pdf.multi_cell(0, 8, informe_texto)

    pdf.output(os.path.join(PDF_FOLDER, nombre_archivo))

def extraer_numero(nombre):
    match = re.search(r'(\d+)', nombre)
    return int(match.group()) if match else float('inf')

def limpiar_nombre(nombre):
    return re.sub(r'[^\w\s-]', '', nombre).strip().replace(' ', '_')

def generar_informe_y_pdf(index, fila, reintentos=3, espera_base=2):
    for intento in range(reintentos):
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

            # Log cuando se solicita generar informe
            print(f"[INFO] Solicitando generación de informe para: {nombre_candidato}")

            if os.path.exists(ruta_pdf):
                os.remove(ruta_pdf)

            prompt = construir_prompt(datos_candidato)

            respuesta = co.generate(
                model="command-r-plus",
                prompt=prompt,
                max_tokens=700,
                temperature=0.4,
            )

            informe = respuesta.generations[0].text.strip()
            if not informe.endswith("."):
                informe += "."

            crear_pdf(nombre_archivo_pdf, datos_candidato, informe)

            progreso["procesados"] += 1

            # Log cuando se genera exitosamente
            print(f"[OK] Informe generado: {nombre_archivo_pdf}")

            return True

        except Exception as e:
            if hasattr(e, 'status_code') and e.status_code == 429:
                espera = espera_base * (2 ** intento)
                print(f"[WARN] Límite de tasa alcanzado. Reintentando en {espera}s (Intento {intento+1}/{reintentos})...")
                time.sleep(espera)
            else:
                # Log cuando hay error general
                print(f"[ERROR] Error al generar informe para {nombre_candidato}: {e}")
                return False
    return False


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

    print(f"[INFO] Archivo recibido: {nombre_archivo}")

    df = pd.read_excel(ruta_guardado)

    progreso["total"] = len(df)
    progreso["procesados"] = 0

    fallidos = []

    def procesar_fila(idx, fila):
        resultado = generar_informe_y_pdf(idx, fila)
        return idx, resultado

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(procesar_fila, idx, fila): idx for idx, fila in df.iterrows()}

        for future in concurrent.futures.as_completed(futures):
            idx, resultado = future.result()
            if not resultado:
                fallidos.append((idx, df.iloc[idx]))

    if fallidos:
        print(f"[WARN] Se reintentarán {len(fallidos)} informes fallidos.")

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as retry_executor:
            retry_futures = [
                retry_executor.submit(generar_informe_y_pdf, idx, fila) for idx, fila in fallidos
            ]
            concurrent.futures.wait(retry_futures)

    print("[INFO] Proceso de generación de informes finalizado.")

    progreso["procesados"] = progreso["total"]  # asegúrate de que quede en 100% al terminar
    return redirect(url_for('listar_pdfs'))

@app.route('/progreso')
def obtener_progreso():
    if progreso["total"] == 0:
        porcentaje = 0
    else:
        porcentaje = int(progreso["procesados"] * 100 / progreso["total"])
        if porcentaje > 100:
            porcentaje = 100
    return jsonify({"porcentaje": porcentaje})

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

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5000)