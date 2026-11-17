import sys
import cv2
import numpy as np
from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QHBoxLayout, QVBoxLayout, QWidget, QSizePolicy


from placas_main import analizar, Seguimiento, dibujar, SALIDAS
from qr_placa import guardar_qr
from modelos import cargar, RUTA_DETECTOR, RUTA_OCR


try:
    import logos_rc
except ImportError:
    print("Advertencia: No se encontró 'logos_rc.py'. El Logo 1 no se mostrará.")


class TrabajadorCamara(QThread):
    senal_frame = Signal(QImage)
    senal_qr = Signal(QPixmap)
    senal_texto = Signal(str)

    def run(self):
        # 1. Cargar modelos
        detector = cargar(RUTA_DETECTOR)
        ocr = cargar(RUTA_OCR)

        # 2. Calentamiento (Warm-up)
        imagen_dummy = np.zeros((320, 320, 3), dtype=np.uint8)
        analizar(imagen_dummy, detector, ocr)

        # 3. Iniciar cámara y seguimiento
        video = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        seguimiento = Seguimiento()

        while not self.isInterruptionRequested():
            ok, frame = video.read()
            if not ok:
                break

            # ---------------------------------------------------------
            # PASO 1: Analizar el frame ORIGINAL para no confundir al OCR
            # ---------------------------------------------------------
            pistas = seguimiento.actualizar(analizar(frame, detector, ocr))

            # ---------------------------------------------------------
            # PASO 2: Voltear el frame SOLO para que el usuario lo vea como espejo
            # ---------------------------------------------------------
            frame_espejo = cv2.flip(frame, 1)
            ancho_frame = frame_espejo.shape[1]

            # Actualizar y dibujar sobre el frame volteado
            for pista in pistas:
                r = pista["resultado"]

                # Hacemos una copia del diccionario para no alterar el seguimiento interno
                r_dibujo = dict(r)

                # Invertimos las coordenadas X de la caja para que coincidan con el espejo
                x0, y0, x1, y1 = r["caja"]
                r_dibujo["caja"] = (ancho_frame - x1, y0, ancho_frame - x0, y1)

                # Dibujamos sobre la imagen volteada (el texto se verá derecho)
                dibujar(frame_espejo, r_dibujo)

                # Si hay una placa nueva y válida
                if r["aceptada"] and r["matricula"] != pista["emitida"]:
                    pista["emitida"] = r["matricula"]

                    ruta, qr_img = guardar_qr(r["matricula"], r["estado"], SALIDAS)
                    qr_rgb = cv2.cvtColor(qr_img, cv2.COLOR_GRAY2RGB)
                    h_q, w_q, ch_q = qr_rgb.shape
                    qimg_qr = QImage(qr_rgb.data, w_q, h_q, ch_q * w_q, QImage.Format_RGB888)
                    self.senal_qr.emit(QPixmap.fromImage(qimg_qr))

                    texto_lectura = f"{r['matricula']} - {r['estado']}"
                    self.senal_texto.emit(texto_lectura)

            # Convertir el frame_espejo para la interfaz
            frame_rgb = cv2.cvtColor(frame_espejo, cv2.COLOR_BGR2RGB)
            h, w, ch = frame_rgb.shape
            qimg_frame = QImage(frame_rgb.data, w, h, ch * w, QImage.Format_RGB888)
            self.senal_frame.emit(qimg_frame)

        video.release()


class VentanaSencilla(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lector de Placas Vehiculares")
        self.resize(1000, 700)
        self.setStyleSheet("background-color: #1e1e22; color: white;")


        layout_cabecera = QHBoxLayout()
        layout_cabecera.setContentsMargins(10, 10, 10, 10)

        # Logo Izquierdo (Desde archivo de recursos logos_rc)
        self.logo_izq = QLabel()
        self.logo_izq.setFixedSize(120, 80)
        self.logo_izq.setAlignment(Qt.AlignCenter)
        pixmap_izq = QPixmap(":/ItcLince/maxLince.png")
        if not pixmap_izq.isNull():
            self.logo_izq.setPixmap(pixmap_izq.scaled(self.logo_izq.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.logo_izq.setText("LOGO 1")
            self.logo_izq.setStyleSheet("border: 1px dashed gray;")

        # Pantalla central de lectura (Estilo LCD Arcade)
        self.label_placa = QLabel("PLACA: EN ESPERA...")
        self.label_placa.setAlignment(Qt.AlignCenter)
        self.label_placa.setStyleSheet("""
            background-color: #040c06;
            color: #33ff33;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 20pt;
            font-weight: bold;
            border: 2px solid #1a4d1a;
            border-radius: 6px;
            padding: 10px;
            min-width: 400px;
        """)

        # Logo Derecho (Desde ruta de archivo local)
        self.logo_der = QLabel()
        self.logo_der.setFixedSize(120, 80)
        self.logo_der.setAlignment(Qt.AlignCenter)


        ruta_logo_2 = r"C:\Users\Asus\Documents\Python Scripts\Identificador_placas_carro\Placas_IA\logs\itc.webp"  # Cambia esta ruta según tu estructura de carpetas

        pixmap_der = QPixmap(ruta_logo_2)
        if not pixmap_der.isNull():
            self.logo_der.setPixmap(pixmap_der.scaled(self.logo_der.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.logo_der.setText("LOGO 2")
            self.logo_der.setStyleSheet("border: 1px dashed gray;")

        layout_cabecera.addWidget(self.logo_izq)
        layout_cabecera.addStretch()
        layout_cabecera.addWidget(self.label_placa)
        layout_cabecera.addStretch()
        layout_cabecera.addWidget(self.logo_der)


        self.label_video = QLabel("Iniciando cámara y cargando IA...\nPor favor espera.")
        self.label_video.setAlignment(Qt.AlignCenter)
        self.label_video.setStyleSheet("font-size: 18px; border: 3px solid #003399; background-color: #000000; border-radius: 8px;")

        # Ignorar tamaño de contenido para evitar expansión infinita
        self.label_video.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        self.label_qr = QLabel("Esperando placa...")
        self.label_qr.setAlignment(Qt.AlignCenter)
        self.label_qr.setFixedSize(250, 250)
        self.label_qr.setStyleSheet("background-color: white; color: black; border: 3px solid #003399; border-radius: 5px;")

        layout_cuerpo = QHBoxLayout()
        layout_cuerpo.setContentsMargins(15, 5, 15, 15)
        layout_cuerpo.setSpacing(15)

        layout_cuerpo.addWidget(self.label_video, stretch=1)

        layout_lateral = QVBoxLayout()
        titulo_qr = QLabel("Último QR Detectado")
        titulo_qr.setAlignment(Qt.AlignCenter)
        titulo_qr.setStyleSheet("font-size: 16px; font-weight: bold; color: #e1e1e6;")

        layout_lateral.addWidget(titulo_qr)
        layout_lateral.addWidget(self.label_qr)
        layout_lateral.addStretch()

        layout_cuerpo.addLayout(layout_lateral)

        # ==========================================
        # 3. ENSAMBLE FINAL
        # ==========================================
        layout_global = QVBoxLayout()
        layout_global.addLayout(layout_cabecera)
        layout_global.addLayout(layout_cuerpo)

        widget_central = QWidget()
        widget_central.setLayout(layout_global)
        self.setCentralWidget(widget_central)

        # --- Iniciar procesamiento ---
        self.hilo = TrabajadorCamara()
        self.hilo.senal_frame.connect(self.actualizar_video)
        self.hilo.senal_qr.connect(self.actualizar_qr)
        self.hilo.senal_texto.connect(self.actualizar_texto_placa)
        self.hilo.start()

    @Slot(QImage)
    def actualizar_video(self, qimage):
        pixmap = QPixmap.fromImage(qimage)
        self.label_video.setPixmap(pixmap.scaled(
            self.label_video.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    @Slot(QPixmap)
    def actualizar_qr(self, qpixmap):
        self.label_qr.setPixmap(qpixmap.scaled(
            self.label_qr.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    @Slot(str)
    def actualizar_texto_placa(self, texto):
        self.label_placa.setText(f"PLACA: {texto}")

    # ==========================================
    # 4. EVENTOS DE CIERRE Y TECLADO
    # ==========================================
    def keyPressEvent(self, event):
        # Cerrar la aplicación al presionar la tecla 'Q' o 'Esc'
        if event.key() == Qt.Key_Q or event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        # Detener la cámara y el hilo de forma segura al cerrar
        self.hilo.requestInterruption()
        self.hilo.wait()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ventana = VentanaSencilla()
    ventana.show()
    sys.exit(app.exec())