"""Lectura asíncrona de webcam, cámara IP, video o imagen para la GUI."""
import os
import threading

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal


class LectorFuente(QThread):
    """Abre y lee la fuente fuera del hilo de la interfaz.

    El búfer es de un solo elemento: si la GUI va más lenta, los cuadros viejos
    se sustituyen y nunca se acumula una cola de frames.
    """
    abierta = Signal(bool, str, int)  # correcta, descripción/error, intervalo ms
    fallo = Signal(str)

    def __init__(self, tipo, valor, padre=None):
        super().__init__(padre)
        self.tipo = tipo              # 'camera', 'video' o 'image'
        self.valor = valor            # índice/url, ruta de video o ruta de imagen
        self._detener = threading.Event()
        self._lock = threading.Lock()
        self._ultimo = None
        self._numero = 0
        self._cap = None
        self._descripcion = ""

    def obtener_cuadro(self, numero_anterior=-1, repetir=False):
        with self._lock:
            if self._ultimo is None or (not repetir and self._numero == numero_anterior):
                return None, self._numero
            return self._ultimo.copy(), self._numero

    def detener(self):
        self._detener.set()
        # No liberar VideoCapture desde otro hilo: algunos backends no lo toleran.
        self.wait(2500)

    def _publicar(self, frame):
        with self._lock:
            self._ultimo = frame
            self._numero += 1

    def run(self):
        try:
            if self.tipo == "image":
                try:
                    frame = cv2.imdecode(np.fromfile(self.valor, dtype=np.uint8), cv2.IMREAD_COLOR)
                except (OSError, ValueError):
                    frame = None
                if frame is None:
                    self.abierta.emit(False, f"No se pudo abrir la imagen: {os.path.basename(self.valor)}", 33)
                    return
                self._descripcion = f"Foto ({os.path.basename(self.valor)})"
                self._publicar(frame)
                self.abierta.emit(True, self._descripcion, 33)
                while not self._detener.wait(0.1):
                    pass
                return

            if self.tipo == "camera":
                valor = self.valor
                if isinstance(valor, int) or str(valor).isdigit():
                    indice = int(valor)
                    backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
                    self._cap = cv2.VideoCapture(indice, backend)
                    self._descripcion = f"Cámara WEB ({indice})" if indice == 0 else f"Cámara IP/local ({indice})"
                else:
                    try:
                        self._cap = cv2.VideoCapture(
                            str(valor), cv2.CAP_FFMPEG,
                            [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 6000,
                             cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000]
                        )
                    except (TypeError, cv2.error):
                        self._cap = cv2.VideoCapture(str(valor))
                    self._descripcion = f"Cámara IP ({valor})"
                self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            else:
                self._cap = cv2.VideoCapture(self.valor)
                self._descripcion = f"Video ({os.path.basename(self.valor)})"

            if self._cap is None or not self._cap.isOpened():
                self.abierta.emit(False, f"No se pudo abrir: {self._descripcion or self.valor}", 33)
                return

            fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
            intervalo = int(1000 / fps) if self.tipo == "video" and 1 <= fps <= 120 else 33
            self.abierta.emit(True, self._descripcion, intervalo)

            while not self._detener.is_set():
                ok, frame = self._cap.read()
                if not ok:
                    if self.tipo == "video" and not self._detener.is_set():
                        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        self._detener.wait(0.01)
                        continue
                    if self._detener.wait(0.02):
                        break
                    # Una cámara en vivo puede perder cuadros momentáneamente.
                    continue
                self._publicar(frame)
        except Exception as exc:
            if not self._detener.is_set():
                self.fallo.emit(f"Error al leer la fuente: {exc}")
        finally:
            if self._cap is not None:
                self._cap.release()
                self._cap = None
