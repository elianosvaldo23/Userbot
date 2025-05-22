import asyncio
from contextlib import suppress
import subprocess
import os, json
import shutil
import re
import threading
import queue
import math
import time
import uuid
import ffmpeg
import datetime
import aiohttp_cors
from aiohttp import web
import humanize
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait
from pyrogram.handlers import MessageHandler
import pyrogram
from pyrogram.errors import (
    ChannelBanned,
    ChannelInvalid,
    ChannelPrivate,
    ChatIdInvalid,
    ChatInvalid,
    FloodWait
)

from spotdl import Spotdl
from spotdl.utils.spotify import SpotifyClient
from spotdl.download.downloader import Downloader
from spotdl.utils.config import DEFAULT_CONFIG
from spotdl.types.song import Song
from spotdl.types.options import DownloaderOptions
from spotdl.utils.config import get_config_file

from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from modules.config import OWNER_ID, NAME, API_ID, API_HASH, TARGET_CHANNEL, VERSION, ENGINE, SESSION_STRING
from modules.gemini import *

# Diccionario global para almacenar procesos de streaming activos
active_streams = {}

# Crear un filtro personalizado para verificar si el usuario es el propietario
def owner_filter(_, __, message):
    return message.from_user and message.from_user.id in OWNER_ID

owner_only = filters.create(owner_filter)

start_time = 0
last_update_time = 0
last_current = 0
update_time = 10

# Crear el cliente del bot
bot = Client(
    f"{NAME}",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
    app_version=VERSION,
    device_model=ENGINE
)

# Decorador para manejar errores comunes
def handle_errors(func):
    async def wrapper(client, message):
        try:
            await func(client, message)
        except Exception as e:
            await message.reply(f"**[⛔]** Error: `{str(e)}`")
    return wrapper

# Función para mostrar progreso de descarga/subida sin tqdm
async def progress(current, total, status_msg, action):
    pass  # No mostramos progreso continuo, solo usamos los mensajes iniciales

@handle_errors
async def download(client: Client, message: Message):
    if message.from_user.id not in OWNER_ID:
        return
    
    if not message.reply_to_message:
        await client.send_message(
            chat_id="me",
            text="**[⛔]** Responde a un mensaje para descargar su contenido."
        )
        return

    status_msg = await client.send_message("me", "**[👾]** Downloading...")
    await client.delete_messages(message.chat.id, message.id)
    
    msg = message.reply_to_message
    if not msg.media and not (msg.text or msg.caption):
        await status_msg.delete()
        await client.send_message(
            chat_id="me",
            text="**[⛔]** El mensaje no contiene medios ni texto."
        )
        return

    media_path = None
    if msg.media:
        media_path = await client.download_media(
            msg,
            progress=progress,
            progress_args=(status_msg, "Downloading")
        )
        if not media_path:
            await status_msg.delete()
            await client.send_message(
                chat_id="me",
                text="**[⛔]** No se pudo descargar el contenido multimedia."
            )
            return

        nombre_original = os.path.basename(media_path)
        nombre_limpio = limpiar_nombre_archivo(nombre_original)
        if nombre_original != nombre_limpio:
            nuevo_path = os.path.join(os.path.dirname(media_path), nombre_limpio)
            os.rename(media_path, nuevo_path)
            media_path = nuevo_path

    text = msg.text or msg.caption
    caption = limpiar_caption(text) if text else None
    media_type = determine_media_type(media_path) if media_path else None

    await status_msg.delete()
    upload_msg = await client.send_message("me", "**[👾]** Uploading...")

    common_params = {
        "chat_id": TARGET_CHANNEL,
        "message_thread_id": None  # No se especifica topic_id por defecto
    }

    try:
        if media_type == "video":
            video_info = get_video_info(media_path)
            thumbnail_path = f"{media_path}_thumb.jpg"
            (
                ffmpeg
                .input(media_path, ss=video_info['duration']//2 if video_info['duration'] > 0 else 0)
                .filter('scale', 320, -1)
                .output(thumbnail_path, vframes=1)
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            await client.send_video(
                **common_params,
                video=media_path,
                caption=caption,
                duration=int(video_info.get('duration', 0)),
                width=video_info.get('width', 0),
                height=video_info.get('height', 0),
                thumb=thumbnail_path if os.path.exists(thumbnail_path) else None,
                progress=progress,
                progress_args=(upload_msg, "Uploading")
            )
            if os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
        elif media_type == "photo":
            await client.send_photo(
                **common_params,
                photo=media_path,
                caption=caption,
                progress=progress,
                progress_args=(upload_msg, "Uploading")
            )
        elif media_type == "document":
            await client.send_document(
                **common_params,
                document=media_path,
                caption=caption,
                thumb="thumb.jpg" if os.path.exists("thumb.jpg") else None,
                progress=progress,
                progress_args=(upload_msg, "Uploading")
            )
        elif text:
            await client.send_message(
                **common_params,
                text=caption,
                disable_web_page_preview=True
            )

        await upload_msg.delete()

        if media_path and os.path.exists(media_path):
            os.remove(media_path)

    except Exception as ex:
        await upload_msg.delete()
        await client.send_message(
            chat_id="me",
            text=f"**[⛔]** Error al enviar el contenido: `{str(ex)}`"
        )

# Funciones auxiliares
def human_readable_size(size_bytes):
    """Convierte bytes a un formato legible (KB, MB, GB)"""
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

def obtener_duracion_video(video_path):
    """Obtiene la duración del video en segundos"""
    try:
        probe = ffmpeg.probe(video_path)
        duration = float(probe['streams'][0]['duration'])
        return duration
    except:
        return 0

def calcular_progreso(output, total_duration):
    """Calcula el progreso de la compresión basado en la salida de ffmpeg"""
    try:
        time_match = re.search(r'time=(\d{2}:\d{2}:\d{2}.\d{2})', output)
        size_match = re.search(r'size=\s*(\d+)(\w+)', output)
        
        current_time = 0
        if time_match:
            time_str = time_match.group(1)
            h, m, s = map(float, time_str.split(':'))
            current_time = h * 3600 + m * 60 + s
        
        percentage = (current_time / total_duration) * 100 if total_duration > 0 else 0
        
        readable_size = "0 MB"
        if size_match:
            size = size_match.group(1)
            unit = size_match.group(2)
            readable_size = f"{size} {unit}"
        
        return readable_size, percentage, current_time
    except:
        return "0 MB", 0, 0

# Configuración de compresión por defecto
DEFAULT_COMPRESSION_SETTINGS = {
    'resolution': '640x360',
    'crf': '35',
    'audio_bitrate': '48k',
    'fps': '24',
    'preset': 'ultrafast',
    'codec': 'libx264'
}

def generar_miniatura(video_path, output_path):
    """Genera una miniatura del video entre los segundos 1 y 9"""
    try:
        (
            ffmpeg
            .input(video_path, ss='00:00:01')
            .filter('scale', 320, -1)
            .output(output_path, vframes=1)
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        return True
    except Exception as e:
        print(f"Error generando miniatura: {e}")
        return False

def determine_media_type(file_path):
    extension = os.path.splitext(file_path)[1].lower()
    if extension in [".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"]:
        return "photo"
    elif extension in [".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm", ".m4v"]:
        return "video"
    else:
        return "document"

def extract_urls(text):
    if not text:
        return []
    url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    return re.findall(url_pattern, text)

def get_video_info(media_path):
    try:
        video_info = ffmpeg.probe(media_path, v='error', select_streams='v:0', 
                                show_entries='stream=duration,width,height')
        stream = video_info['streams'][0]
        
        return {
            'duration': float(stream.get('duration', 0)),
            'width': int(stream.get('width', 0)),
            'height': int(stream.get('height', 0))
        }
    except Exception as e:
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'error', 
                 '-select_streams', 'v:0',
                 '-show_entries', 'stream=duration,width,height',
                 '-of', 'json',
                 media_path],
                capture_output=True,
                text=True
            )
            info = json.loads(result.stdout)
            stream = info['streams'][0]
            
            return {
                'duration': float(stream.get('duration', 0)),
                'width': int(stream.get('width', 0)),
                'height': int(stream.get('height', 0))
            }
        except Exception as ex:
            print(f"Error getting video info: {ex}")
            return {
                'duration': 0,
                'width': 0,
                'height': 0
            }

def get_listado():
    url = "https://datafacil.vercel.app/listado.json"
    response = requests.get(url)
    frases = response.json()
    return frases

def limpiar_caption(caption):
    if not caption:
        return caption
        
    texto_limpio = caption
    for frase in get_listado():
        texto_limpio = texto_limpio.replace(frase, "").strip()
    
    while "\n\n\n" in texto_limpio:
        texto_limpio = texto_limpio.replace("\n\n\n", "\n\n")
    
    return texto_limpio.strip()

def limpiar_nombre_archivo(nombre):
    nombre_limpio = nombre
    for frase in get_listado():
        nombre_limpio = nombre_limpio.replace(frase, "").strip()
    
    while "  " in nombre_limpio:
        nombre_limpio = nombre_limpio.replace("  ", " ")
    
    nombre_sin_ext, ext = os.path.splitext(nombre_limpio)
    nombre_limpio = f"{nombre_sin_ext}{ext}"
    
    return nombre_limpio.strip()

# Handlers
@handle_errors
async def set_compression_settings(client: Client, message: Message):
    if message.from_user.id not in OWNER_ID:
        return
    
    if len(message.command) < 2:
        current_settings = "\n".join([f"{k}: {v}" for k, v in DEFAULT_COMPRESSION_SETTINGS.items()])
        await message.reply(
            f"**[👾] Configuración actual de compresión:**\n`{current_settings}`\n\n"
            "**[⛔] Uso:** `-setcompression [parametro=valor]`\n"
            "**Ejemplo:** `-setcompression resolution=1280x720 crf=28`"
        )
        return
    
    try:
        params = " ".join(message.command[1:]).split()
        for param in params:
            if '=' in param:
                key, value = param.split('=', 1)
                if key in DEFAULT_COMPRESSION_SETTINGS:
                    DEFAULT_COMPRESSION_SETTINGS[key] = value
        
        new_settings = "\n".join([f"{k}: {v}" for k, v in DEFAULT_COMPRESSION_SETTINGS.items()])
        await message.reply(f"**[✅] Nueva configuración de compresión:**\n`{new_settings}`")
    
    except Exception as e:
        await message.reply(f"**[⛔] Error:** `{str(e)}`")

@handle_errors
async def compress_video(client: Client, message: Message):
    if message.from_user.id not in OWNER_ID:
        return
    
    if not message.reply_to_message or (not message.reply_to_message.video and not message.reply_to_message.document):
        await message.reply("**[⛔]** Debes responder a un video o un archivo de video.")
        return
    
    is_document = message.reply_to_message.document is not None
    if is_document:
        media = message.reply_to_message.document
        file_name = media.file_name or f"video_{message.id}"
        if not determine_media_type(file_name) == "video":
            await message.reply("**[⛔]** El archivo no es un video válido.")
            return
    else:
        media = message.reply_to_message.video

    original_path = None
    compressed_path = None
    thumbnail_path = None
    start_time = datetime.datetime.now()
    
    try:
        status_msg = await message.reply("**[👾]** Descargando video...")
        original_filename = media.file_name or f"video_{message.id}.mp4"
        original_path = await client.download_media(
            media,
            file_name=f"downloads/{original_filename}"
        )
        
        if not os.path.exists(original_path):
            await status_msg.edit("**[⛔]** Error al descargar el video.")
            return
        
        original_info = get_video_info(original_path)
        original_size = os.path.getsize(original_path)
        original_duration = original_info.get('duration', 0)
        
        duration_str = str(datetime.timedelta(seconds=int(original_duration)))
        await status_msg.edit(f"**[👾]** Video descargado ({duration_str}). Comprimiendo...")
        
        base_name = os.path.splitext(original_filename)[0]
        compressed_path = f"downloads/{base_name}_compressed.mp4"
        thumbnail_path = f"downloads/{base_name}_thumb.jpg"
        
        generar_miniatura(original_path, thumbnail_path)
        
        (
            ffmpeg
            .input(original_path)
            .output(
                compressed_path,
                vf=f'scale={DEFAULT_COMPRESSION_SETTINGS["resolution"]},fps={DEFAULT_COMPRESSION_SETTINGS["fps"]}',
                crf=DEFAULT_COMPRESSION_SETTINGS['crf'],
                preset=DEFAULT_COMPRESSION_SETTINGS['preset'],
                vcodec=DEFAULT_COMPRESSION_SETTINGS['codec'],
                acodec='aac',
                audio_bitrate=DEFAULT_COMPRESSION_SETTINGS['audio_bitrate'],
                movflags='+faststart'
            )
            .global_args('-loglevel', 'error')
            .global_args('-y')
            .run()
        )
        
        if not os.path.exists(compressed_path):
            await status_msg.edit("**[⛔]** Error al comprimir el video.")
            return
        
        compressed_size = os.path.getsize(compressed_path)
        compressed_info = get_video_info(compressed_path)
        tiempo_procesamiento = datetime.datetime.now() - start_time
        
        result_text = (
            f"**[✅] {base_name} - Compresión completada**\n\n"
            f"**📊 Estadísticas:**\n"
            f"┠ Tamaño original: {human_readable_size(original_size)}\n"
            f"┠ Tamaño comprimido: {human_readable_size(compressed_size)}\n"
            f"┠ Reducción: {((original_size - compressed_size) / original_size * 100):.1f}%\n"
            f"┖ Duración del video: {duration_str}\n\n"
            f"**⚙️ Configuración usada:**\n"
            f"┠ Resolución: {DEFAULT_COMPRESSION_SETTINGS['resolution']}\n"
            f"┠ CRF: {DEFAULT_COMPRESSION_SETTINGS['crf']}\n"
            f"┠ FPS: {DEFAULT_COMPRESSION_SETTINGS['fps']}\n"
            f"┠ Codec: {DEFAULT_COMPRESSION_SETTINGS['codec']}\n"
            f"┠ Preset: {DEFAULT_COMPRESSION_SETTINGS['preset']}\n"
            f"┖ Audio: {DEFAULT_COMPRESSION_SETTINGS['audio_bitrate']}\n\n"
            f"**⏱️ Tiempo de compresión:** {str(tiempo_procesamiento).split('.')[0]}"
        )
        
        await status_msg.edit("**[👾]** Subiendo video comprimido...")
        
        thumb = thumbnail_path if os.path.exists(thumbnail_path) else None
        
        await client.send_video(
            chat_id=message.chat.id,
            video=compressed_path,
            caption=result_text,
            duration=int(compressed_info.get('duration', original_duration)),
            width=compressed_info.get('width', 0),
            height=compressed_info.get('height', 0),
            thumb=thumb,
            file_name=f"{base_name}_compressed.mp4",
            reply_to_message_id=message.reply_to_message.id
        )
        
        await status_msg.delete()
    
    except Exception as e:
        error_msg = f"**[⛔]** Error al comprimir el video: `{str(e)}`"
        try:
            await status_msg.edit(error_msg)
        except:
            await message.reply(error_msg)
    
    finally:
        for file_path in [original_path, compressed_path, thumbnail_path]:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)

@handle_errors
async def start(client: Client, message: Message):
    if message.from_user.id in OWNER_ID:
        bienvenida = f"""
🌟 *¡Hola {message.from_user.mention}!* 🌟  

**Bienvenido a Wolf Userbot**  
*Tu asistente multifunción en Telegram.*  

▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬  
🔹 **Funciones principales:**  
✔ **IA Integrada** (Chats, búsquedas, ayuda)  
✔ **Extraer posts** (de canales/grupos)  
✔ **Información de usuarios/chats**  
✔ **Rápido y seguro** (sin dependencias externas)  
✔ **Personalizable** (solo para ti)  

▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬  
🛠 **Versión:** `v{VERSION}`  
⚡ *Desarrollado por @Sasuke286*  
"""
        await message.reply(
            text=bienvenida,
            disable_web_page_preview=True
        )

@handle_errors
async def help(client: Client, message: Message):
    if message.from_user.id in OWNER_ID:
        help = f"""
<b>Comandos del User-bot</b>

<code>-start</code>
└ Inicia el User-bot

<code>-userinfo</code> <i>reply</i> | <i>user_id</i>
└ Muestra información de un usuario

<code>-chatinfo</code> <i>reply</i> | <i>chat_id</i>
└ Muestra información de un chat

<code>-ai</code> <i>texto</i>
└ Genera una respuesta de la IA

<code>-aiaudio</code>
└ Genera una respuesta de la IA en audio

<code>-stream</code> <i>stream_url</i> <i>stream_key</i>
└ Inicia un stream de video

<code>-stopstream</code> <i>stream_id</i>
└ Detiene un stream en progreso

<code>-urlsave</code> <i>enlace</i> <i>cantidad</i> <i>channel_id</i> <i>topic_id</i>
└ Guarda mensajes de un enlace de Telegram

<code>-save</code> <i>id chanel</i> <i>cantidad</i> <i>channel_id</i> <i>topic_id</i>
└ Renvio masivo de mensajes de un canal a otro

<code>-clear</code>
└ Limpia la carpeta de descargas

<code>-story</code> <i>reply</i>
└ Sube un archivo multimedia a tu historia

<code>-afk</code>
└ Activa/desactiva el modo AFK

<code>-compress</code> <i>reply to video/document</i>
└ Comprime un video o archivo de video

<code>-setcompression</code> <i>param=valor</i>
└ Configura los parámetros de compresión

<code>.dl</code> <i>reply to media</i>
└ Descarga y envía un documento, video, audio o foto a mensajes guardados
"""
        await message.reply(
            text=help
        )

@handle_errors
async def ping(client: Client, message: Message):
    if message.from_user.id in OWNER_ID:
        start = datetime.datetime.now()
        end = datetime.datetime.now()
        ms = (end - start).microseconds / 1000
        await message.reply(f"**[👾] Pong!** `{ms} ms`", quote=True)

@handle_errors
async def userinfo(client: Client, message: Message):
    if message.from_user.id in OWNER_ID:
        dc_id = {
            1: "Miami FL | USA",
            2: "Amsterdam | NL",
            3: "Miami FL | USA",
            4: "Amsterdam | NL",
            5: "Singapore | SG"
        }
        
        msg = await message.reply("**[👾]** Wait For Info...")
        if message.reply_to_message:
            user = message.reply_to_message.from_user.id
        elif len(message.command) > 1:
            user = message.command[1]
        else:
            return await msg.edit("**[⛔]** Invalid User")
        try:
            ui = await client.get_users(user)
        except Exception as ex:
            return await msg.edit(f"**[⛔]** Error\nEX:\n`{ex}`")
        
        dcid = f"{ui.dc_id} | {dc_id[ui.dc_id]}" if ui.dc_id else "Unknown"
        button = InlineKeyboardButton(text="GOOGLE", url=f"https://www.google.com/")
        keyboard = InlineKeyboardMarkup([[button]])
        ui_text = [
            f"┎ User {ui.mention}\n",
            f"┠ Firstname : {ui.first_name}\n",
            f"┠ Lastname : {ui.last_name}\n" if ui.last_name else "",
            f"┠ Username : @{ui.username}\n"if ui.username else "",
            f"┠ ID: `{ui.id}`\n",
            f"┠ DCID: {dcid}\n",
            f"┠ Premium: {'Si' if ui.is_premium else 'No'}\n"
            f"┠ Status: {(str(ui.status)).split('.')[-1]}\n",
            f"┠ Bot: {'Si' if ui.is_bot else 'No'}\n",
            f"┠ Scam: {'Si' if ui.is_scam else 'No'}\n",
            f"┠ Contacto: {'Si' if ui.is_contact else 'No'}\n",
            f"┠ Verificado: {'Si' if ui.is_verified else 'No'}\n",
            f"┖ Chats en Común: {len(await ui.get_common_chats())}",
        ]
        pic = ui.photo.big_file_id if ui.photo else None
        if pic is not None:
            await msg.delete()
            photo = await client.download_media(pic)
            await message.reply_photo(
                photo=photo,
                caption="".join(ui_text),
                reply_markup=keyboard,
            )
            if os.path.exists(photo):
                os.remove(photo)
        else:
            await bot.send_message(message.chat.id, text="".join(ui_text))

@handle_errors
async def get_chat_info(client: Client, message: Message):
    if message.from_user.id in OWNER_ID:
        msg = await message.reply("**[👾]** Wait For Info...")
        reply = message.reply_to_message
        if reply:
            chat_id = reply.chat.id
        elif len(message.command) > 1:
            chat_id = message.command[1]
        else:
            await msg.edit("**[⛔]** Debes proporcionar un ID de chat o responder a un mensaje.")
            return
        try:
            chat_info = await client.get_chat(chat_id)
        except Exception as ex:
            return await msg.edit(f"**[⛔]** Error fetching chat info.\nEX:\n`{ex}`")
        
        chat_info_text = [
            f"┎ Info {chat_info.title}\n",
            f"┠ Username : @{chat_info.username}\n" if chat_info.username is not None else "",
            f"┠ ID: `{chat_info.id}`\n",
            f"┠ Miembros: {chat_info.members_count}\n",
            f"┠ Scam: {'Si' if chat_info.is_scam else 'No'}\n",
            f"┠ Soporte: {'Si' if (chat_info.is_support) else 'No'}\n"
            f"┠ Verificado: {'Si' if (chat_info.is_verified) else 'No'}\n",
            f"┠ Chat Type: {(str(chat_info.type)).split('.')[-1]}\n",
            f"┖ Descripción:\n{chat_info.description}" if chat_info.description is not None else "",
        ]
        pic = chat_info.photo.big_file_id if chat_info.photo else None
        if pic is not None:
            photo = await bot.download_media(pic)
            await bot.send_photo(
                message.chat.id,
                photo,
                caption="".join(chat_info_text),
                reply_to_message_id=message.id,
            )
            os.remove(photo)
            await msg.delete()
            return
        else:
            await bot.send_message(message.chat.id, text="".join(chat_info_text))

@handle_errors
async def upload_to_story(client: Client, message: Message):
    if message.from_user.id not in OWNER_ID:
        return
    
    if not message.reply_to_message or (not message.reply_to_message.video and not message.reply_to_message.photo):
        await message.reply("**[⛔]** Debes responder a un video o una imagen.")
        return
    
    try:
        status_msg = await message.reply("**[👾]** Descargando archivo...")
        media = message.reply_to_message.video if message.reply_to_message.video else message.reply_to_message.photo
        media_path = await client.download_media(
            media,
        )
        
        caption = message.text.split(" ", 1)[1] if len(message.text.split(" ", 1)) > 1 else None
        
        duration = None
        if message.reply_to_message.video:
            video_info = get_video_info(media_path)
            duration = int(video_info['duration'])
        
        if message.reply_to_message.video:
            await client.send_story(
                chat_id="me",
                media=media_path,
                duration=duration,
                caption=caption
            )
        elif message.reply_to_message.photo:
            await client.send_story(
                chat_id="me",
                media=media_path,
                caption=caption
            )
        
        if os.path.exists(media_path):
            os.remove(media_path)
        
        await status_msg.edit("**[✅]** Archivo subido a tu historia exitosamente.")
    
    except Exception as ex:
        await message.reply(f"**[⛔]** Error al subir a la historia: {ex}")

@handle_errors
async def save_and_forward_message(client: Client, message: Message):
    if not message.from_user.id in OWNER_ID:
        return
    
    try:
        if len(message.command) < 2:
            await message.reply("**[⛔]** Uso: `-urlsave [enlace de Telegram] [cantidad opcional] [channel_id opcional] [topic_id opcional]`")
            return

        link = message.command[1]
        
        count = 1
        target_channel = TARGET_CHANNEL
        target_topic = None
        
        if len(message.command) >= 3:
            count = int(message.command[2])
        if len(message.command) >= 4:
            target_channel = int(message.command[3])
        if len(message.command) >= 5:
            target_topic = int(message.command[4])

        info_msg = await message.reply(
            f"**[👾]** Procesando enlace:\n{link}\n"
            f"Cantidad: {count}\n"
            f"Canal destino: {target_channel}\n"
            f"Topic ID: {target_topic if target_topic else 'No especificado'}", 
            disable_web_page_preview=True
        )

        status_msg = await message.reply(f"**[👾]** Sacando contenido...")

        private_with_topic = r"https?://t\.me/c/(\d+)/(\d+)/(\d+)"
        private_pattern = r"https?://t\.me/c/(\d+)/(\d+)"
        public_pattern = r"https?://t\.me/([\w\d_]+)/(\d+)"
        bot_pattern = r"https?://t\.me/b/([\w\d_]+)/(\d+)"

        topic_id = None
        if re.match(private_with_topic, link):
            match = re.match(private_with_topic, link)
            chat_id = int("-100" + match.group(1))
            message_id = int(match.group(3))
            topic_id = int(match.group(2))
        elif re.match(private_pattern, link):
            match = re.match(private_pattern, link)
            chat_id = int("-100" + match.group(1))
            message_id = int(match.group(2))
        elif re.match(public_pattern, link):
            match = re.match(public_pattern, link)
            chat_id = match.group(1)
            message_id = int(match.group(2))
        elif re.match(bot_pattern, link):
            match = re.match(bot_pattern, link)
            chat_id = match.group(1)
            message_id = int(match.group(2))
        else:
            await status_msg.edit("**[⛔]** El enlace proporcionado no es válido.")
            return
        
        success_count = 0
        error_count = 0
        total_messages = count
        start_time = datetime.datetime.now()

        for i in range(count):
            try:
                if success_count > 0 and success_count % 50 == 0:
                    await status_msg.edit(f"**[⏳]** Pausa de 1 minutos para evitar flood después de {success_count} mensajes...")
                    await asyncio.sleep(5)

                current_message_id = message_id + i
                msg = await client.get_messages(chat_id, current_message_id)

                if not msg:
                    await message.reply(f"**[⛔]** No se pudo obtener el mensaje con ID: `{current_message_id}`.")
                    continue
                
                if not msg.media and not (msg.text or msg.caption):
                    continue

                media_path = None

                if msg.media:
                    media_path = await client.download_media(
                        msg,
                    )
                    await asyncio.sleep(10)
                    if not media_path:
                        await status_msg.edit(f"**[⚠️]** No se pudo descargar el contenido multimedia.")
                        return

                    nombre_original = os.path.basename(media_path)
                    nombre_limpio = limpiar_nombre_archivo(nombre_original)
                    if nombre_original != nombre_limpio:
                        nuevo_path = os.path.join(os.path.dirname(media_path), nombre_limpio)
                        os.rename(media_path, nuevo_path)
                        media_path = nuevo_path

                text = msg.text or msg.caption
                caption = limpiar_caption(text) if text else None

                media_type = determine_media_type(media_path) if media_path else None

                common_params = {
                    "chat_id": target_channel,
                    "message_thread_id": target_topic
                }

                if media_type == "video":
                    video_info = get_video_info(media_path)
                    thumbnail_path = f"{media_path}_thumb.jpg"
                    (
                        ffmpeg
                        .input(media_path, ss=video_info['duration']//2 if video_info['duration'] > 0 else 0)
                        .filter('scale', 320, -1)
                        .output(thumbnail_path, vframes=1)
                        .overwrite_output()
                        .run(capture_stdout=True, capture_stderr=True)
                    )
                    await client.send_video(
                        **common_params,
                        video=media_path,
                        caption=caption,
                        duration=video_info['duration'],
                        width=video_info['width'],
                        height=video_info['height'],
                        thumb=thumbnail_path if os.path.exists(thumbnail_path) else None,
                    )
                    if os.path.exists(thumbnail_path):
                        os.remove(thumbnail_path)
                elif media_type == "photo":
                    await asyncio.sleep(1)
                    await client.send_photo(
                        **common_params,
                        photo=media_path,
                        caption=caption
                    )
                elif media_type == "document":
                    await asyncio.sleep(10)
                    await client.send_document(
                        **common_params,
                        document=media_path,
                        caption=caption,
                    )
                elif text:
                    await client.send_message(
                        **common_params,
                        text=caption,
                        disable_web_page_preview=True
                    )

                if media_path and os.path.exists(media_path):
                    os.remove(media_path)
                success_count += 1

                await asyncio.sleep(1)
            
            except (
                ChannelBanned,
                ChannelInvalid,
                ChannelPrivate,
                ChatIdInvalid,
                ChatInvalid,
            ):
                await info_msg.edit("Estas unido a ese canal?")
                return

            except FloodWait as e:
                await status_msg.edit(f"**[⏳]** Esperando {e.value} segundos debido a limitaciones de Telegram...")
                await asyncio.sleep(e.value)
            except Exception as ex:
                error_count += 1
                
        elapsed_time = datetime.datetime.now() - start_time
        final_text = (
            f"**[👾]** Proceso completado:\n"
            f"✅ Mensajes exitosos: {success_count}\n"
            f"⚠️ Errores: {error_count}\n"
            f"⏱️ Tiempo total: {str(elapsed_time).split('.')[0]}"
        )
        if topic_id:
            final_text += f"\n📑 Topic ID: {topic_id}"
        final_text += f"\n📅 {datetime.datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}"

        await status_msg.edit(final_text)
        
    except Exception as ex:
        await message.reply(f"**[⛔]** Error general: {str(ex)}")

class StreamStatusQueue:
    def __init__(self, message, status_msg, stream_id):
        self.message = message
        self.status_msg = status_msg
        self.stream_id = stream_id
        self.status_queue = queue.Queue()
        self.stop_event = threading.Event()

def status_monitor(stream_status_queue, client):
    while not stream_status_queue.stop_event.is_set():
        try:
            try:
                message_text, is_error = stream_status_queue.status_queue.get(timeout=1)
            except queue.Empty:
                continue

            try:
                asyncio.run(_update_status(
                    client, 
                    stream_status_queue.message, 
                    stream_status_queue.status_msg, 
                    message_text, 
                    is_error
                ))
            except Exception as e:
                print(f"Error updating status: {e}")
        except Exception as e:
            print(f"Status monitor error: {e}")
    
async def _update_status(client, message, status_msg, message_text, is_error):
    try:
        await status_msg.edit(message_text)
    except Exception:
        await message.reply(message_text)

def configure_ffmpeg(video_path, output_url):
    video_info = get_video_info(video_path)
    video_codec = video_info["video_codec"]
    audio_codec = video_info["audio_codec"]
    pix_fmt = video_info.get("pix_fmt", "")
    
    stream = ffmpeg.input(video_path)
    
    output_args = {
        "format": "flv",
        "preset": "ultrafast",
        "crf": "20",
        "maxrate": "1200k",
        "bufsize": "2400k",
        "r": video_info["fps"],
        "g": int(video_info["fps"] * 2),
        "pix_fmt": "yuv420p",
        "audio_bitrate": "96k",
        "ar": "48000",
        "tune": "zerolatency",
    }
    
    if video_codec != "h264" or pix_fmt != "yuv420p":
        output_args["vcodec"] = "libx264"
    else:
        output_args["vcodec"] = "libx264"

    if audio_codec != "aac":
        output_args["acodec"] = "aac"
    else:
        output_args["acodec"] = "aac"
    
    stream = stream.output(output_url, **output_args)
    
    stream = stream.global_args(
        "-loglevel", "info",
        "-stream_loop", "-1",
    )

    return stream

def stream_video_thread(video_path, stream_url, stream_key, stream_status_queue):
    try:
        if not os.path.exists(video_path):
            stream_status_queue.status_queue.put(("**[⛔]** El archivo de video no existe.", True))
            return
        
        output_url = f"{stream_url}{stream_key}"
   
        try:
            stream_status_queue.status_queue.put(("**[👾]** Iniciando transmisión...", False))
            
            stream = configure_ffmpeg(video_path, output_url)
            
            ffmpeg.run(stream, overwrite_output=True)
            
            stream_status_queue.status_queue.put(("**[✅]** Transmisión completada.", False))

        except ffmpeg.Error as e:
            error_message = e.stderr.decode() if e.stderr else "Error desconocido en ffmpeg."
            stream_status_queue.status_queue.put((f"**[⛔️]** Error al transmitir: {error_message}", True))
        except Exception as e:
            stream_status_queue.status_queue.put((f"**[⛔️]** Error al transmitir: {str(e)}", True))
    
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)
        
        if stream_status_queue.stream_id in active_streams:
            del active_streams[stream_status_queue.stream_id]
        
        stream_status_queue.stop_event.set()

@handle_errors
async def stream_video(client: Client, message: Message):
    if message.from_user.id not in OWNER_ID:
        return
    
    if not message.reply_to_message or not message.reply_to_message.video:
        await message.reply("**[⛔]** Debes responder a un video para transmitir.")
        return
    
    try:
        stream_id = str(uuid.uuid4())
        
        if len(message.command) < 3:
            await message.reply("**[⛔]** Uso: `-stream [stream_url] [stream_key]`")
            return
        
        stream_url = message.command[1]
        stream_key = message.command[2]
        
        status_msg = await message.reply(f"**[👾]** Descargando video para transmisión. ID de Stream: `{stream_id}`")
        await message.reply(f'`-stopstream {stream_id}`')
        video_path = await client.download_media(
            message.reply_to_message.video,
        )
        
        if not os.path.exists(video_path):
            await status_msg.edit("**[⛔]** Error: No se pudo descargar el video.")
            return
        
        stream_status_queue = StreamStatusQueue(message, status_msg, stream_id)
        
        monitor_thread = threading.Thread(
            target=status_monitor, 
            args=(stream_status_queue, client),
            daemon=True
        )
        monitor_thread.start()
        
        streaming_thread = threading.Thread(
            target=stream_video_thread, 
            args=(video_path, stream_url, stream_key, stream_status_queue),
            daemon=True
        )
        streaming_thread.start()
        
        active_streams[stream_id] = {
            'thread': streaming_thread,
            'stop_event': stream_status_queue.stop_event
        }
        
        await status_msg.edit(f"**[👾]** Transmisión iniciada en segundo plano. ID de Stream: `{stream_id}`")
    
    except Exception as ex:
        await message.reply(f"**[⛔]** Error general: {ex}")

@handle_errors
async def stop_stream(client: Client, message: Message):
    if message.from_user.id not in OWNER_ID:
        return
    
    if len(message.command) < 2:
        await message.reply("**[⛔]** Uso: `-stopstream [stream_id]`")
        return
    
    stream_id = message.command[1]
    
    if stream_id not in active_streams:
        await message.reply(f"**[⛔]** No se encontró un stream con ID: `{stream_id}`")
        return
    
    try:
        active_streams[stream_id]['stop_event'].set()
        active_streams[stream_id]['thread'].join(timeout=1)
        del active_streams[stream_id]
        await message.reply(f"**[✅]** Stream con ID `{stream_id}` detenido exitosamente.")
    
    except Exception as ex:
        await message.reply(f"**[⛔]** Error al detener el stream: {ex}")

@handle_errors
async def clear(client: Client, message: Message):
    try:
        if os.path.exists('downloads'):
            shutil.rmtree('downloads')
            await message.reply(f'A sido limpiado todo')
            print(f"La carpeta downloads ha sido eliminada.")
        
        os.makedirs('downloads')
        print(f"La carpeta downloads_path ha sido creada nuevamente.")
        await message.reply(f'Creada la carpeta')
    except Exception as e:
        print(f"Hubo un error: {e}")

@handle_errors
async def gemini(client: Client, message: Message):
    msg = await message.reply("**[👾]** Esperando a la IA...")
    if message.reply_to_message:
        prompt = message.reply_to_message.text or message.reply_to_message.caption
    else:
        prompt = message.text.split(" ", 1)[1] if len(message.text.split(" ", 1)) > 1 else None
    if not prompt:
        await msg.edit("**[⛔]** Por favor proporciona un texto para generar la respuesta.")
        return
    try:
        audio = message.text.split("|")[-1]
    except:
        audio = 'no'
    salida_audio= 'respuesta.mp3'
    if audio == 'audio':
        await msg.edit("**[👾]** Generando respuesta...")
        respuesta = await generar_respuesta(prompt)
        respuesta_formateada = formatear_markdown(respuesta)
        await msg.edit("**[👾]** La AI esta grabando un audio...")
        await generar_audio(respuesta_formateada, 'es', salida_audio)
        await msg.delete(True)
        if os.path.exists(salida_audio):
            status_msg = await message.reply("**[👾]** Subiendo...")
            with open(salida_audio, 'rb') as f:
                await message.reply_voice(f)
            os.remove(salida_audio)
            await status_msg.delete(True)
        else:
            await message.reply("**[⛔]** No se pudo generar el archivo de audio.")
    else:
        mm = await msg.edit("**[👾]** Generando respuesta...")
        respuesta = await generar_respuesta(prompt)
        respuesta_fragmentos = dividir_respuesta(respuesta)
        for fragmento in respuesta_fragmentos:
            await message.reply(fragmento)
            time.sleep(1)
        await mm.delete(True)

@handle_errors
async def gemini_audio(client: Client, message: Message):
    msg = await message.reply("**[👾]** Esperando a la IA...")
    if message.reply_to_message:
        prompt = message.reply_to_message.text or message.reply_to_message.caption
    else:
        prompt = message.text.split(" ", 1)[1] if len(message.text.split(" ", 1)) > 1 else None
    if not prompt:
        await msg.edit("**[⛔]** Por favor proporciona un texto para generar la respuesta.")
        return
    try:
        lang = message.text.split("|")[-1]
    except:
        lang = 'es'
    await msg.delete(True)
    audio = await message.reply(f"**[👾]** Generando audio <{lang}>...")
    salida_audio= 'respuesta.wav'
    try:
        await generar_audio(prompt, lang, salida_audio)
        if os.path.exists(salida_audio):
            with open(salida_audio, 'rb') as f:
                await message.reply_voice(f)
            os.remove(salida_audio)
            await audio.delete(True)
        else:
            await message.reply("**[⛔]** No se pudo generar el archivo de audio.")
    except Exception as e:
        await message.reply(f"**[⛔]** Error al generar o subir audio: {str(e)}")

@handle_errors
async def gemini_file(client: Client, message: Message):
    if message.from_user.id not in OWNER_ID:
        return
    if not message.reply_to_message or not message.reply_to_message.document:
        await message.reply("**[⛔]** Debes responder a un documento.")
        return
    try:
        try:
            audio = message.text.split("|")[-1]
        except:
            audio = 'no'
        salida_audio= 'respuesta.mp3'
        if audio == 'audio':
            msg = await message.reply("**[👾]** Descargando archivo...")
            media = message.reply_to_message.document
            media_path = await client.download_media(media, file_name=media.file_name)
            prompt = message.text.split(" ", 1)[1] if len(message.text.split(" ", 1)) > 1 else None
            if not prompt:
                await msg.edit("**[⛔]** Por favor proporciona un texto para generar la respuesta.")
                return
            await msg.edit(f"**[👾]** AI analizando el documento {media.file_name}...")
            response = await analizar_files(prompt, media_path)
            respuesta_formateada = formatear_markdown(response)
            await msg.edit("**[👾]** La AI esta grabando un audio...")
            await generar_audio(respuesta_formateada, 'es', salida_audio)
            with open(salida_audio, 'rb') as f:
                await message.reply_voice(f)
            os.remove(salida_audio)
            os.remove(media_path)
            await msg.delete(True)
        else:
            msg = await message.reply("**[👾]** Descargando archivo...")
            media = message.reply_to_message.document
            media_path = await client.download_media(media, file_name=media.file_name)
            prompt = message.text.split(" ", 1)[1] if len(message.text.split(" ", 1)) > 1 else None
            if not prompt:
                await msg.edit("**[⛔]** Por favor proporciona un texto para generar la respuesta.")
                return
            await msg.edit(f"**[👾]** AI analizando el documento {media.file_name}...")
            response = await analizar_files(prompt, media_path)
            await msg.delete(True)
            split = dividir_respuesta(response)
            for fragmento in split:
                await message.reply(fragmento)
                time.sleep(1)
            os.remove(media_path)
    except Exception as ex:
        await message.reply(f"**[⛔]** Error al procesar su archivo: {ex}")

@handle_errors
async def gemini_image(client: Client, message: Message):
    if message.from_user.id not in OWNER_ID:
        return
    try:
        msg = await message.reply("**[👾]** pipopi...")
        prompt = message.text.split(" ", 1)[1] if len(message.text.split(" ", 1)) > 1 else None
        if not prompt:
            await msg.edit("**[⛔]** Por favor proporciona un texto para generar la respuesta.")
            return
        await msg.edit(f"**[👾]** La AI esta generando una imagen...")
        image = await generar_imagen_hf(prompt)
        with open('ai.jpg', 'rb') as f:
            await message.reply_photo(image)
        os.remove('ai.jpg')
        await msg.delete(True)
    except Exception as ex:
        await message.reply(f"**[⛔]** Error al procesar su archivo: {ex}")

# AFK
AFK = False
AFK_REASON = ""
AFK_TIME = ""
USERS = {}
GROUPS = {}

def get_chat_id(message: Message):
    return message.chat.id

def subtract_time(start, end):
    subtracted = humanize.naturaltime(start - end)
    return str(subtracted)

@handle_errors
async def set_afk(client: Client, message: Message):
    global AFK_REASON, AFK, AFK_TIME
    
    cmd = message.command
    afk_text = ""

    if len(cmd) > 1:
        afk_text = " ".join(cmd[1:])

    if isinstance(afk_text, str):
        AFK_REASON = afk_text

    AFK = True
    AFK_TIME = datetime.datetime.now()

    await message.reply(f"**[👾]** Modo AFK activado.\nRazón: `{AFK_REASON}`")
    await message.delete()

@handle_errors
async def unset_afk(client: Client, message: Message):
    global AFK, AFK_TIME, AFK_REASON, USERS, GROUPS

    if AFK:
        last_seen = subtract_time(datetime.datetime.now(), AFK_TIME).replace("ago", "").strip()
        await message.edit(
            f"**[👾]** Mientras estabas ausente (por {last_seen}), "
            f"recibiste {sum(USERS.values()) + sum(GROUPS.values())} "
            f"mensajes de {len(USERS) + len(GROUPS)} chats"
        )
        AFK = False
        AFK_TIME = ""
        AFK_REASON = ""
        USERS = {}
        GROUPS = {}
        await asyncio.sleep(5)

    await message.delete()

@handle_errors
async def collect_afk_messages(client: Client, message: Message):
    if AFK:
        last_seen = subtract_time(datetime.datetime.now(), AFK_TIME)
        is_group = message.chat.type in ["supergroup", "group"]
        CHAT_TYPE = GROUPS if is_group else USERS
        
        if get_chat_id(message) not in CHAT_TYPE:
            text = (
                f"<b>[👾] Este es un mensaje automático.</b>\n\n"
                f"<i>No estoy disponible en este momento.</i>\n"
                f"Última vez visto: {last_seen}\n"
                f"Razón:\n<blockquote expandable>{AFK_REASON}</blockquote>\n"
                f"<b>Te responderé cuando regrese.</b>"
            )
            await message.reply(text)
            CHAT_TYPE[get_chat_id(message)] = 1
            return
            
        if get_chat_id(message) in CHAT_TYPE:
            if CHAT_TYPE[get_chat_id(message)] == 50:
                text = (
                    f"<b>[👾] Este es un mensaje automático.</b>\n\n"
                    f"Última vez visto: {last_seen}\n"
                    f"Esta es la 10ma vez que te digo que estoy AFK...\n"
                    f"Te responderé cuando regrese.\n"
                    f"No más mensajes automáticos para ti."
                )
                await message.reply(text)
            elif CHAT_TYPE[get_chat_id(message)] > 50:
                return
            elif CHAT_TYPE[get_chat_id(message)] % 5 == 0:
                text = (
                    f"<b>[👾] Hey, aún no he vuelto.</b>\n\n"
                    f"Última vez visto: {last_seen}\n"
                    f"Sigo ocupado: \n<blockquote expandable>{AFK_REASON}</blockquote>\n"
                    f"Intenta más tarde."
                )
                await message.reply(text)

        CHAT_TYPE[get_chat_id(message)] += 1

@handle_errors
async def auto_unset_afk(client: Client, message: Message):
    global AFK, AFK_TIME, AFK_REASON, USERS, GROUPS
    
    if AFK and not message.text.startswith(('-afk', '-unafk')):
        last_seen = subtract_time(datetime.datetime.now(), AFK_TIME).replace("ago", "").strip()
        reply = await message.reply(
            f"**[👾]** Mientras estabas ausente (por {last_seen}), "
            f"recibiste {sum(USERS.values()) + sum(GROUPS.values())} "
            f"mensajes de {len(USERS) + len(GROUPS)} chats"
        )
        AFK = False
        AFK_TIME = ""
        AFK_REASON = ""
        USERS = {}
        GROUPS = {}
        await asyncio.sleep(5)
        await reply.delete()

@handle_errors
async def save_forward_message(client: Client, message: Message):
    if not message.from_user.id in OWNER_ID:
        return
    
    try:
        if len(message.command) < 4:
            await message.reply("**[⛔]** Uso: `-save [id_canal_origen] [id_mensaje_inicial] [cantidad de mensajes] [id_canal_destino] [topic_id(opcional)]`")
            return
        try:
            source_channel = int(message.command[1])
            start_id = int(message.command[2])
            count = int(message.command[3])
            destination_channel = int(message.command[4])
        except Exception as e:
            await message.reply(f"**[⛔]** Error: {e}")
            return

        topic_id = None 
        if len(message.command) > 5:
            try:
                topic_id = int(message.command[5])
            except ValueError:
                await message.reply("**[⛔]** El ID del tema debe ser un número entero.")
                return

        status_text = f"**[👾]** Reenviando mensajes desde `{source_channel}` a `{destination_channel}`"
        if topic_id:
            status_text += f" con el tema `{topic_id}`"
        status_text += "..."
        status_msg = await message.reply(status_text)

        success_count = 0
        error_count = 0
        total_messages = count
        start_time = datetime.datetime.now()

        for current_message_id in range(start_id, start_id + count):
            try:
                if success_count > 0 and success_count % 100 == 0:
                    await status_msg.edit(f"**[⏳]** Pausa de 5 segundos para evitar flood después de {success_count} mensajes...")
                    await asyncio.sleep(5)
                
                msg = await client.get_messages(source_channel, current_message_id)
                if not msg or msg.empty:
                    print(f"Mensaje {current_message_id} no encontrado o vacío")
                    error_count += 1
                    continue

                forward_params = {
                    "chat_id": destination_channel,
                    "from_chat_id": source_channel,
                    "message_ids": current_message_id,
                    "disable_notification": True,
                    "hide_sender_name": True
                }
                if topic_id:
                    forward_params["message_thread_id"] = topic_id

                await asyncio.sleep(3)
                await client.forward_messages(**forward_params)
                success_count += 1

                if success_count % 10 == 0:
                    progress = (success_count / total_messages) * 100
                    progress_bar = "█" * int(progress / 5) + "░" * (20 - int(progress / 5))
                    
                    progress_text = (
                        f"**[👾]** Progreso: {progress:.1f}%\n"
                        f"```\n{progress_bar}```\n"
                        f"✅ Reenviados: {success_count}/{total_messages}\n"
                        f"⚠️ Errores: {error_count}\n"
                        f"🔄 ID actual: {current_message_id}"
                    )
                    if topic_id:
                        progress_text += f"\n📑 Topic ID: {topic_id}"
                    
                    await status_msg.edit(progress_text)

            except FloodWait as fw:
                await status_msg.edit(f"**[⏳]** Esperando {fw.x} segundos debido a limitaciones de Telegram...")
                await asyncio.sleep(fw.value)
            except Exception as e:
                error_count += 1
                print(f"Error reenviando mensaje {current_message_id}: {str(e)}")
                continue

        elapsed_time = datetime.datetime.now() - start_time
        final_text = (
            f"**[👾]** Tarea completada!\n"
            f"✅ Mensajes reenviados: {success_count}\n"
            f"⚠️ Errores: {error_count}\n"
            f"⏱️ Tiempo total: {str(elapsed_time).split('.')[0]}"
        )
        if topic_id:
            final_text += f"\n📑 Topic ID: {topic_id}"
        final_text += f"\n📅 {datetime.datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}"
        
        await status_msg.edit(final_text)

    except Exception as e:
        await message.reply(f"**[⛔]** Error: {e}")

def is_playlist(url):
    return "/playlist/" in url

def spotuserinfo():
    try:
        with open(get_config_file(), "r") as file:
            userinfo = json.load(file)
            client_id = userinfo["client_id"]
            client_secret = userinfo["client_secret"]
            file.close()
        print(f"client_id: {client_id}\nclient_secret: {client_secret}")
        return client_id, client_secret
    except:
        os.system("echo Y | spotdl --generate-config")

@handle_errors
async def download_music(client: Client, message: Message):
    if message.from_user.id in OWNER_ID:
        if len(message.command) < 2:
            await message.reply(
                "**[❌] Error:** Debes proporcionar una URL de Spotify.\n**Uso:** `-dlmusic URL`",
                quote=True
            )
            return

        url = message.command[1]
        status_msg = await message.reply("**[🔍] Procesando enlace...**", quote=True)
        temp_dir = "downloads"

        try:
            client_id, client_secret = spotuserinfo()
            print(f"client_id: {client_id}\nclient_secret: {client_secret}")
            if not SpotifyClient._instance:
                spotdl = Spotdl(
                    client_id=client_id, client_secret=client_secret
                )

            options = DownloaderOptions(
                output=temp_dir,
                format="mp3",
                quality="best",
                save_file=False,
                overwrite="skip",
                log_level="CRITICAL",
                log_level_console="ERROR",
                simple_tui=True
            )

            if is_playlist(url):
                await status_msg.edit("**[📂] Detectada playlist, obteniendo canciones...**")
                songs = spotdl.search(url)
                if not songs:
                    await message.reply("**[❌] No se encontraron canciones en la playlist.**", quote=True)
                    return
            else:
                songs = [Song.from_url(url)]

            await status_msg.edit("**[🎵] Canción encontrada**\n**[⏬] Iniciando descarga...**")
            processed = 0

            def sync_download_song(song, options):
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    local_downloader = Downloader(options)
                    return local_downloader.download_song(song)
                finally:
                    new_loop.close()

            for song in songs:
                await status_msg.edit(f"**[⏬] Descargando:** `{song.name}` - `{song.artists[0]}`")
                file_path_str = None
                try:
                    download_path = await asyncio.to_thread(sync_download_song, song, options)
                    _, file_path = download_path
                    file_path_str = str(file_path) if file_path else None
                except Exception as e:
                    print(f"Error al descargar {song.name}: {e}")
                    download_path = None

                if file_path_str and os.path.exists(file_path_str):
                    await status_msg.edit(f"**[📤] Subiendo:** `{song.name}` - `{song.artists[0]}`")
                    try:
                        await client.send_audio(
                            chat_id=message.chat.id,
                            audio=file_path_str,
                            caption=f"**Título:** `{song.name}`\n**Artista:** `{song.artists[0]}`\n**Álbum:** `{song.album_name}`",
                            title=song.name,
                            performer=song.artists[0]
                        )
                        processed += 1
                    except Exception as upload_error:
                        await message.reply(
                            f"**[❌] Error al subir:** `{str(upload_error)}`", quote=True
                        )

                    try:
                        os.remove(file_path_str)
                    except Exception as file_error:
                        print(f"Error al eliminar archivo: {file_error}")
                else:
                    await message.reply(
                        f"**[❌] Error al descargar:** `{song.name}`", quote=True
                    )

            if processed > 0:
                await status_msg.edit(
                    f"**[✅] Descarga completada:** {processed}/{len(songs)} canción(es) procesada(s)."
                )
            else:
                await status_msg.edit("**[❌] No se pudo descargar ninguna canción.**")

        except Exception as e:
            error_msg = str(e)
            print(f"Error en download_music: {error_msg}")
            await status_msg.edit(f"**[❌] Error:** `{error_msg}`")

# Registrar los handlers
bot.add_handler(MessageHandler(
    ping,
    filters.command("ping", prefixes=['.']) & owner_only
))
bot.add_handler(MessageHandler(
    start,
    filters.command("start", prefixes=['-']) & owner_only
))
bot.add_handler(MessageHandler(
    save_and_forward_message,
    filters.command("urlsave", prefixes=['-']) & owner_only
))
bot.add_handler(MessageHandler(
    userinfo, 
    filters.command("userinfo", prefixes=['-']) & owner_only
))
bot.add_handler(MessageHandler(
    get_chat_info, 
    filters.command("chatinfo", prefixes=['-']) & owner_only
))
bot.add_handler(MessageHandler(
    upload_to_story,
    filters.command("story", prefixes=['-']) & owner_only
))
bot.add_handler(MessageHandler(
    clear,
    filters.command("clear", prefixes=['-']) & owner_only
))
bot.add_handler(MessageHandler(
    stream_video,
    filters.command("stream", prefixes=['-']) & owner_only
))
bot.add_handler(MessageHandler(
    stop_stream,
    filters.command("stopstream", prefixes=['-']) & owner_only
))
bot.add_handler(MessageHandler(
    gemini,
    filters.command("ai", prefixes=['-']) & owner_only
))
bot.add_handler(MessageHandler(gemini_audio,
    filters.command("aiaudio", prefixes=['-']) & owner_only
))
bot.add_handler(MessageHandler(gemini_file,
    filters.command("aifile", prefixes=['-']) & owner_only
))
bot.add_handler(MessageHandler(gemini_image,
    filters.command("aiimage", prefixes=['-']) & owner_only
))
bot.add_handler(MessageHandler(
    set_afk,
    filters.command("afk", prefixes=['-']) & owner_only
))
bot.add_handler(MessageHandler(
    unset_afk,
    filters.command("unafk", prefixes=['-']) & owner_only
))
bot.add_handler(MessageHandler(
    save_forward_message,
    filters.command("save", prefixes=['-']) & owner_only
))
bot.add_handler(MessageHandler(
    download_music,
    filters.command("dlmusic", prefixes=['-']) & owner_only
))
bot.add_handler(MessageHandler(
    help,
    filters.command("help", prefixes=['-']) & owner_only
))
bot.add_handler(MessageHandler(
    compress_video,
    filters.command("compress", prefixes=['-']) & owner_only
))
bot.add_handler(MessageHandler(
    set_compression_settings,
    filters.command("setcompression", prefixes=['-']) & owner_only
))
bot.add_handler(MessageHandler(
    download,
    filters.command("dl", prefixes=['.']) & owner_only
))
bot.add_handler(MessageHandler(
    collect_afk_messages,
    ((filters.group & filters.mentioned) | filters.private) & ~filters.me
))
bot.add_handler(MessageHandler(
    auto_unset_afk,
    filters.me
))

async def startup_message():
    try:
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        startup_text = f"""**[👾] Bot Iniciado**
        
┎ Estado: Operativo
┠ Fecha: {current_time}
┠ Versión: {VERSION}
┖ Engine: {ENGINE}
"""
        
        for owner in OWNER_ID:
            try:
                await bot.send_message("me", startup_text)
            except Exception as e:
                print(f"Error enviando mensaje de inicio a {owner}: {e}")
                
    except Exception as e:
        print(f"Error en startup_message: {e}")

def web_home(request):
    resp = requests.get('https://v2.jokeapi.dev/joke/Programming?blacklistFlags=nsfw,religious,political,racist,sexist,explicit&format=txt&type=single').text
    return web.Response(text=f"👾 {resp} 👾")

async def server():
    app = web.Application()
    cors = aiohttp_cors.setup(
        app,
        defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
            )
        },
    )
    
    app.router.add_get("/", web_home)

    for route in list(app.router.routes()):
        cors.add(route)
    
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 7860))
    site = web.TCPSite(runner, "0.0.0.0", port)

    print("Starting server")
    await site.start()
    await asyncio.Future()

async def main():
    await bot.start()
    print("👾 Bot Started...")
    bot.loop.create_task(startup_message())
    asyncio.create_task(server())
    await pyrogram.idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    with suppress(KeyboardInterrupt):
        loop.run_until_complete(main())