

class BiesseCloseFilter(QtCore.QObject):
    # Intercepts the main window's close so Biesse can offer to park first.
    def __init__(self, handler):
        super().__init__()
        self.handler = handler

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Close and self.handler.biesse_close_requested():
            event.ignore()
            return True
        return False
