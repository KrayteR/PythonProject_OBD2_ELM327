import sys
import serial
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QTextEdit


class SerialHandler(QThread):
    data_received = pyqtSignal(str)  # Sygnał wysyłany przy każdym odebraniu danych

    def __init__(self, port, baud=38400, timeout=1):
        super().__init__()
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.running = True
        self.ser = None

    def run(self):
        # Próba otwarcia portu
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
            self.data_received.emit(f"Otwarto port {self.port} z prędkością {self.baud} bps")
        except Exception as e:
            self.data_received.emit("Błąd przy otwarciu portu: " + str(e))
            return

        # Inicjalizacja interfejsu – wysyłamy komendy startowe
        self.send_direct("ATZ")  # Reset interfejsu
        self.msleep(1000)  # krótka przerwa
        self.send_direct("ATSP0")  # Ustawienie automatycznego wyboru protokołu
        self.msleep(1000)

        # Główna pętla odczytu – zamiast czekać na odpowiedź, sprawdzamy bufor
        while self.running:
            if self.ser.in_waiting:
                try:
                    data = self.ser.read_all().decode('utf-8', errors='ignore')
                    if data:
                        self.data_received.emit("Odebrano: " + data.strip())
                except Exception as e:
                    self.data_received.emit("Błąd przy odczycie: " + str(e))
            self.msleep(20)  # krótka pauza, aby nie obciążać CPU

        self.ser.close()
        self.data_received.emit("Port został zamknięty.")

    @pyqtSlot(str)
    def writeCommand(self, command):
        """
        Metoda wywoływana przez slot – wysyła komendę do portu.
        Upewnia się, że komenda kończy się znakiem CR.
        """
        if self.ser is not None:
            try:
                if not command.endswith("\r"):
                    command += "\r"
                self.ser.write(command.encode('utf-8'))
                self.data_received.emit("Wysłano: " + command.strip())
            except Exception as e:
                self.data_received.emit("Błąd przy wysyłce: " + str(e))

    def send_direct(self, command):
        """
        Funkcja pomocnicza wykorzystywana w trakcie inicjalizacji,
        nie korzystająca bezpośrednio z mechanizmu slotów.
        """
        if self.ser is not None:
            if not command.endswith("\r"):
                command += "\r"
            try:
                self.ser.write(command.encode('utf-8'))
                self.data_received.emit("Wysłano: " + command.strip())
            except Exception as e:
                self.data_received.emit("Błąd przy wysyłce: " + str(e))

    def stop(self):
        self.running = False
        self.wait()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VGATE ICAR2 OBD2 Monitor (asychroniczny odczyt)")
        self.resize(600, 400)

        # Pole tekstowe do wyświetlania logów
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)

        # Przycisk do startu, zatrzymania i wysłania polecenia
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        self.poll_button = QPushButton("Wyślij polecenie 010C")

        self.stop_button.setEnabled(False)

        layout = QVBoxLayout()
        layout.addWidget(self.text_edit)
        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.poll_button)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # Połączenie przycisków z funkcjami (slotami)
        self.start_button.clicked.connect(self.start_serial)
        self.stop_button.clicked.connect(self.stop_serial)
        self.poll_button.clicked.connect(self.send_poll)

        self.serialHandler = None

    def start_serial(self):
        # Dostosuj nazwę portu – np. "COM5" (Windows) lub "/dev/ttyUSB0" (Linux/Mac)
        port = "COM24"
        # Możesz też zmienić baud_rate, jeśli urządzenie na to pozwala
        self.serialHandler = SerialHandler(port, baud=38400)
        # Łączymy sygnał z funkcją aktualizującą logi w GUI
        self.serialHandler.data_received.connect(self.update_text)
        self.serialHandler.start()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    def stop_serial(self):
        if self.serialHandler:
            self.serialHandler.stop()
            self.serialHandler = None
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def send_poll(self):
        """
        Wysyłamy komendę "010C" – nie czekamy na odpowiedź,
        bo odebranie danych jest obsługiwane asynchronicznie poprzez sygnał.
        """
        if self.serialHandler:
            self.serialHandler.writeCommand("010C")

    def update_text(self, text):
        self.text_edit.append(text)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
