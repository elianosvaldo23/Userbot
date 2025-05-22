import ffmpeg
import os

def stream_to_telegram(stream_url, stream_key, video_path):
    # Validar que el archivo de video exista
    if not os.path.exists(video_path):
        print(f"Error: El archivo de video {video_path} no existe.")
        return

    # Configurar la transmisión con ffmpeg-python
    output_url = f"{stream_url}{stream_key}"
   
    try:
        # Usar un método más robusto para la configuración de ffmpeg
        stream = (
            ffmpeg
            .input(video_path)
            .output(
                output_url,
                format="flv",
                vcodec="libx264",  # Códec de video H.264
                acodec="aac",  # Códec de audio AAC
                preset="medium",  # Equilibrio entre velocidad y calidad
                maxrate="2500k",  # Límite de tasa de bits
                bufsize="3750k",  # Tamaño del búfer (recomendado: 1.5x maxrate)
                pix_fmt="yuv420p",  # Formato de píxeles compatible
                r=30,  # Frames por segundo
                g=60   # Intervalo de keyframes
            )
            .global_args(
                "-loglevel", "info",  # Mostrar información en la terminal
                "-stream_loop", "-1"  # Repetir transmisión indefinidamente (opcional)
            )
        )
        
        # Ejecutar la transmisión
        ffmpeg.run(stream, overwrite_output=True)

    except ffmpeg.Error as e:
        print("Ocurrió un error al transmitir a Telegram:")
        print(f"Código de salida: {e.returncode}")
        print(f"Salida estándar: {e.stdout.decode() if e.stdout else 'N/A'}")
        print(f"Salida de error: {e.stderr.decode() if e.stderr else 'N/A'}")

# Configuración
stream_url = "rtmps://dc1-1.rtmp.t.me/s/"  # URL del servidor de Telegram
stream_key = "2243092863:TI4b_cU0IonzaaC78sjQVw"  # Reemplázalo con la clave de transmisión
video_path = "01.mp4"  # Ruta al video local que deseas transmitir

# Ejecutar la función
if __name__ == "__main__":
    stream_to_telegram(stream_url, stream_key, video_path)