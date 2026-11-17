import time, numpy as np
from modelos import cargar, RUTA_DETECTOR
det = cargar(RUTA_DETECTOR)
x = np.random.randint(0, 255, (1, 320, 320, 3)).astype("float32")
for i in range(5):
    t = time.perf_counter()
    det(x, training=False)
    print(i, round(time.perf_counter() - t, 2), "s")