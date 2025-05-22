from modules.gemini import *
import aiohttp
import asyncio
import os
from pathlib import Path

async def listar_archivos(directorio, ignorar=None):
    archivos = []
    try:
        for root, dirs, files in os.walk(directorio):
            # Filtrar directorios a ignorar
            dirs[:] = [d for d in dirs if d not in ignorar]
            for file in files:
                archivos.append(os.path.join(root, file))
    except Exception as e:
        print(f"Error al listar archivos: {str(e)}")
    return archivos

async def files():
    prompt = "Por favor, analiza todos los archivos y dime como puedo desplegar este proyecto en vercel y que no me de error"
    ignorar = [".venv", "__pycache__", ".git", "vendor", "dev", ".gitattributes"]
    media = await listar_archivos('C:\\Users\\egg\\OneDrive\\Documentos\\GitHub\\api-ut', ignorar=ignorar)
    #print(media)
    print('Analizando archivos...')
    resultados = await analizar_files(prompt, media)
    with open("archivo_salida.txt", "w", encoding="utf-8") as f:
        f.write(resultados)
    print(resultados)

async def models():
    await gemini_list_models()
    await clear_cache()
    
    
async def test():
    files = os.listdir('test')
    model = genai.GenerativeModel(modelo)
    for file in files:
        mime_type = obtener_mime(os.path.join('test',file))
        print(f"{os.path.join('test',file)}: {mime_type}")
        if mime_type in textmime:
            genai.upload_file(str(os.path.join('test',file)))
    await files_list()
    await files_delete()

async def imagen():
    prompt = 'Genera una imagen de un joker como personaje del Call of Duty'
    await generar_imagen_hf(prompt)
    
if __name__ == '__main__':
    asyncio.run(files())