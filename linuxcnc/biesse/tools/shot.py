import sys
from PyQt5.QtWidgets import QApplication
app = QApplication(sys.argv)
img = app.primaryScreen().grabWindow(0)
img.save(sys.argv[1] if len(sys.argv) > 1 else "/tmp/shot.png")
print(img.width(), img.height())
