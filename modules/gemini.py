import os
import textwrap
import google.generativeai as genai
from google.generativeai import caching
import datetime
import time
from gtts import gTTS
from elevenlabs.client import ElevenLabs
from pathlib import Path
import mimetypes
import requests
import io
from PIL import Image
import soundfile as sf
import numpy as np
import aiohttp
from pathlib import Path

token_hf = os.environ.get('HF_API_KEY')
token_vision = 'f7bd61e5-67e0-4fe4-ae4e-284cc95e2b31'

textmime = ['application/pdf', 'application/x-javascript', 'text/javascript', 'application/x-python', 'text/x-python', 'text/plain', 'text/html', 'text/css', 'text/md', 'text/csv', 'text/xml', 'text/rtf']

# Inicializa el cliente ElevenLabs
client = ElevenLabs(api_key="sk_c24d9f27d5abbdbd1887e68b8a793cb36a1c8d8a80b14c13")

# Iniciar cliente de Google Generative AI
genai.configure(api_key="AIzaSyDY-JbCj5W205ZoPshj4CmZ1qeoQRmUQDw")
modelo = "gemini-2.0-pro-exp-02-05"

# Función para generar texto usando Google Generative AI
async def generar_respuesta(prompt):
    model = genai.GenerativeModel(modelo)
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Hubo un error al generar la respuesta: {str(e)}"

# Obtener tipos de archivos
def obtener_mime(filepath):
    mime_type, _ = mimetypes.guess_type(filepath)
    return mime_type

# Analizar archivos con IA
async def analizar_files(prompt, media):
    if not isinstance(media, list):
        return "La variable 'media' debe ser una lista de rutas de archivos."
    resultados = []
    model = genai.GenerativeModel(modelo)
    files_to_upload = []
    for file_path in media:
        try:
            mime_type = obtener_mime(file_path)
            #print(f"{file_path}: {mime_type}")
            if mime_type in textmime:
                path = Path(file_path).resolve()
                file = genai.upload_file(str(path))
                files_to_upload.append(file)
            else:
                resultados.append(
                    f"Archivo no compatible ({file_path}):\n"
                    f"Solamente compatible con archivos de texto como:\n"
                    "    -*PDF*\n"
                    "    -*JavaScript*\n"
                    "    -*Python*\n"
                    "    -*TXT*\n"
                    "    -*HTML*\n"
                    "    -*CSS*\n"
                    "    -*Markdown*\n"
                    "    -*CSV*\n"
                    "    -*XML*\n"
                    "    -*RTF*")
        except Exception as e:
            resultados.append(f"Error al procesar {file_path}: {str(e)}")
    if files_to_upload:
        try:
            response = model.generate_content([prompt] + files_to_upload)
            resultados.append(response.text)
            for file in files_to_upload:
                file.delete()
            # Si lo deseas, puedes eliminar los archivos físicamente
            # for path in [Path(file.path) for file in files_to_upload]:
            #     os.remove(path)
        except Exception as e:
            resultados.append(f"Error al generar contenido con los archivos: {str(e)}")
    return "\n\n".join(resultados)

def dividir_respuesta(respuesta, max_chars=4000):
    return textwrap.wrap(respuesta, max_chars)

def formatear_markdown(respuesta):
    formatted_response = respuesta.replace('*', '').replace('_', '')
    return formatted_response

async def generar_audio(texto, lang, salida_audio="respuesta.mp3"):
    tts = gTTS(texto, lang=lang)
    tts.save(salida_audio)
    print(f"Audio generado: {salida_audio}")
    
async def generar_audio1(texto, lang='es', salida_audio='respuesta.mp3'):
    response = client.voices.get_all()
    audio_generator = client.generate(text=texto, voice=response.voices[1].voice_id, model="eleven_multilingual_v2")
    with open(salida_audio, 'wb') as f:
        for chunk in audio_generator:
            f.write(chunk)

'''def generar_audio0(text,salida_audio='respuesta.wav'):
    API_URL = "https://api-inference.huggingface.co/models/fishaudio/fish-speech-1.2"
    headers = {"Authorization": f"Bearer {token_hf}"}
    payload ={"inputs": text,}
    response = requests.post(API_URL, headers=headers, json=payload)
    print(response.content)
    #audio, sampling_rate = response.json()
    #sf.write(salida_audio, audio, sampling_rate)'''

# Obtener archivos subidos a Google para analisis
async def files_list():
        print("My files:")
        for f in genai.list_files():
            print("  ", f.display_name)

# Eliminar archivos subidos a Google para analisis
async def files_delete():
        print("Delete files:")
        for f in genai.list_files():
            print("  ", f.display_name)
            myfile = genai.get_file(f.name)
            myfile.delete()

# Generar imagenes con VISIONCRAFT
async def generar_imagen(prompt):
    API_URL = "https://visioncraft.top/api/image/generate"
    payload = {"model": "FLUX.1-dev-fp8", "prompt": prompt, "token": token_vision, "stream": False}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(API_URL, json=payload) as response:
                if response.status == 429:
                    return f"El token ha superado el límite. Intentando con otro token..."
                elif response.status == 200:
                    return await response.json()
                else:
                    return {"error": f"Error {response.status}: {await response.text()}"}
        except Exception as e:
            return {"error": f"Error al intentar generar la imagen: {str(e)}"}

async def generar_imagen_hf(prompt):
    API_URL = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-dev"
    headers = {"Authorization": f"Bearer {token_hf}"}
    payload = {"inputs": prompt,}
    response = requests.post(API_URL, headers=headers, json=payload)
    #print(response.content)
    image = Image.open(io.BytesIO(response.content))
    image.save('ai.jpg')
    return 'ai.jpg'

# Generar videos con VISIONCRAFT
async def generar_video(prompt):
    API_URL = "https://visioncraft.top/api/image/generate"
    payload = {"model": "RealismFusion-V1", "prompt": prompt, "token": token_vision, "stream": False, "is_video": True, "fps":16, "frames":16}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}", json=payload) as response:
            return await response.json()

# Generar chats con AI con cache
async def gemini_text_cache(prompt, user, files=None):
    try:
        if await list_cache(f'{user}_cache') == None:
            print(f"CREANDO CACHE {await list_cache(f'{user}_cache')}")
            cache = caching.CachedContent.create(
            model='gemini-1.5-flash-8b-latest',
            display_name=f'{user}_cache',
            ttl=datetime.timedelta(minutes=60),
        )
        else:
            print(f"USANDO CACHE {await list_cache(f'{user}_cache')}")
            cache = caching.CachedContent.get(await list_cache(f'{user}_cache'))
        model = genai.GenerativeModel.from_cached_content(cached_content=cache)
        if files == None:
            response = model.generate_content([prompt])
        else:
            filesu = []
            for file_path in files:
                mime_type = obtener_mime(file_path)
                print(f"{file_path}: {mime_type}")
                if mime_type in textmime:
                    path = Path(file_path).resolve()
                    file = genai.upload_file(str(path))
                    filesu.append(file)
            response = model.generate_content([prompt, files])
        #print(f"Caché creado: {cache_name}")
        #print("Metadata de uso:", response.usage_metadata)
        #print("Texto generado:", response.text)
        return response.text
    except Exception as e:
        print(f"Error en gemini_text_cache: {str(e)}")
        return None

# Listado de caches creadas
async def list_cache(cache=None):
    for c in caching.CachedContent.list():
        if c.display_name == cache:
            return c.name
        else:
            return None

# Limpiar cache en caso de deshabilitar el tiempo de ttl en
# la funcion gemini_text_cache()
async def clear_cache(cache=None):
    for c in caching.CachedContent.list():
        print(c)
        c.delete()

# Obtener los modelos disponibles de Gemini
async def gemini_list_models():
    models = genai.list_models()
    for model in models:
        #if 'createCachedContent' in model.supported_generation_methods:
            print(model.name, model.description)