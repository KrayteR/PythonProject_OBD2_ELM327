import logging
import re
import sys
import threading
import time
from configparser import ConfigParser

import serial
from PyQt5 import uic
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot, QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QTextEdit
from PyQt5 import uic, QtCore, QtWidgets
from PyQt5.QtCore import Qt, Q_ARG

SEND = ""
RECEIVED_BACK = True

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
            self.data_received.emit("Błąd przy otwieraniu portu: " + str(e))
            return

        # Inicjalizacja interfejsu – wysyłamy komendy startowe
        # self.send_direct("ATZ")      # Reset interfejsu
        # self.msleep(1000)            # krótka przerwa
        # self.send_direct("ATSP0")    # Ustawienie automatycznego wyboru protokołu
        # self.msleep(1000)
        self.send_direct("ATE0")
        self.msleep(1000)
        self.send_direct("ATL0")
        self.msleep(1000)
        # self.send_direct("ATR0")
        # self.msleep(1000)

        # Główna pętla odczytu – sprawdzamy bufor danych
        while self.running:
            if self.ser.in_waiting:
                try:
                    data = self.ser.read_all().decode('utf-8', errors='ignore')
                    if data:
                        self.data_received.emit(data.strip())
                except Exception as e:
                    self.data_received.emit("Błąd przy odczycie: " + str(e))
            self.msleep(20)  # krótka pauza, by nie obciążać CPU

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
                # Dla celów debugowania wypisujemy wysłaną komendę
                print("Wyslano:", command.strip())
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
                self.data_received.emit("Wyslano: " + command.strip())
            except Exception as e:
                self.data_received.emit("Błąd przy wysyłce: " + str(e))

    def stop(self):
        self.running = False
        self.wait()


UI_main_path = uic.loadUiType("UI\\main.ui")[0]

class MainWindow(QtWidgets.QMainWindow, UI_main_path):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowTitle("reader")
        self.cfg = self.load_cfg()
        self.setAcceptDrops(True)
        self.text_edit.setReadOnly(True)
        self.stop_button.setEnabled(False)
        self.timeout_timer = QTimer(self)
        self.timeout_timer.timeout.connect(self.handle_timeout)
        self.manual_commands_queue = []

        # Połączenie przycisków z funkcjami (slotami)
        self.start_button.clicked.connect(self.start_serial)
        self.stop_button.clicked.connect(self.stop_serial)
        self.poll_button.clicked.connect(self.send_poll_manually)

        # Podłączamy sygnał zmiany stanu checkboxa do slotu toggle_polling
        self.checkbox_loop.stateChanged.connect(self.toggle_polling)

        self.serialHandler = None

        # Ustawiamy timer do wysyłania zapytań co 20 ms.
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.send_poll)

        print("Początkowy stan checkboxa:", self.checkbox_loop.checkState())

    def load_cfg(self) -> dict:
        cfg = ConfigParser()
        cfg.read("cfg.ini")
        logging.info("Config loaded")
        return cfg

    def start_serial(self):
        # Dostosuj nazwę portu – np. "COM24" (Windows) lub "/dev/ttyUSB0" (Linux/Mac)
        port = "COM24"
        self.serialHandler = SerialHandler(port, baud=38400)
        # Łączymy sygnał z funkcją dekodującą odebrane dane
        self.serialHandler.data_received.connect(self.decoding)
        self.serialHandler.start()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.update_text("Port uruchomiony. Możesz włączyć automatyczne odpytywanie checkboxem.")


    def toggle_polling(self, state):
        # Sprawdzamy, czy mamy aktywne połączenie (serialHandler)
        if self.serialHandler:
            if state == Qt.Checked:
                self.poll_timer.start(200)  # uruchamiamy timer: co 20 ms wysyłamy zapytanie
                self.update_text("Automatyczne odpytywanie włączone.")
            else:
                self.poll_timer.stop()
                self.update_text("Automatyczne odpytywanie wyłączone.")


    def decoding(self, text):
        """
        Odbiera dane, aktualizuje GUI i zatrzymuje timeout.
        Po odebraniu odpowiedzi wysyłamy kolejną komendę.
        """
        try:
            self.update_text(text)
            received = text.replace(" ", "").replace("\r", "")
            received = re.findall('..', received)
            print(received)
            # Jeśli przyszła odpowiedź, zatrzymujemy timer i wysyłamy następną komendę
            if self.timeout_timer.isActive():
                self.timeout_timer.stop()

            # Po odebraniu odpowiedzi wysyłamy następną komendę z kolejki
            QtCore.QTimer.singleShot(500, self.send_next_manual_command)
        except Exception as e:
            print(e)


    def stop_serial(self):
        if self.poll_timer.isActive():
            self.poll_timer.stop()
        if self.serialHandler:
            self.serialHandler.stop()
            self.serialHandler = None
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.update_text("Połączenie zakończone.")


    def send_poll(self):
        """
        Funkcja wywoływana przez QTimer lub przycisk poll_button.
        Wysyła zapytanie "010C" do interfejsu.
        """

        if self.serialHandler:
            self.serialHandler.writeCommand(self.lineEdit_command.text())

    def send_poll_manually(self):
        """
        Inicjalizacja wysyłania komend w kolejności.
        Jeśli nie otrzymamy odpowiedzi w określonym czasie, komenda zostanie wysłana ponownie.
        """
        try:
            self.manual_commands_queue = list(self.cfg['commands'].items())
            self.current_command = None  # Przechowuje aktualną wysyłaną komendę
            self.timeout_timer = QTimer(self)
            self.timeout_timer.timeout.connect(self.handle_timeout)
            self.send_next_manual_command()
        except Exception as e: print(e)

    def send_next_manual_command(self):
        """
        Wysyła następną komendę z kolejki, jeśli istnieje.
        Uruchamia także timer, który sprawdzi, czy przyszła odpowiedź.
        """
        try:
            if self.manual_commands_queue:
                name, command = self.manual_commands_queue.pop(0)
                logging.info(f"Wysyłam komendę '{name}': {command}")
                self.current_command = command  # Zapamiętujemy aktualną komendę

                # Uruchamiamy wysyłanie komendy w nowym wątku
                threading.Thread(target=self.send, args=(command,), daemon=True).start()

                # Rozpoczynamy timeout na 2 sekundy
                self.timeout_timer.start(2000)
            else:
                logging.info("Wszystkie komendy zostały wysłane.")
        except Exception as e:
            print(e)


    def handle_timeout(self):
        """
        Funkcja wywoływana przez QTimer, jeśli nie przyszła odpowiedź na daną komendę.
        Powtarza wysłanie aktualnej komendy.
            """

        try:
            if self.current_command:
                logging.warning(f"Brak odpowiedzi, ponowne wysłanie: {self.current_command}")
                threading.Thread(target=self.send, args=(self.current_command,), daemon=True).start()
        except Exception as e:
            print(e)

    def send(self, text):
        """
        Metoda wysyłająca pojedynczą komendę do serialHandler.
        """
        if self.serialHandler:
            self.serialHandler.writeCommand(text)



    def update_text(self, text):
        self.text_edit.append(text)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s.%(msecs)03d %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("logss.log", mode="a", encoding="utf-8"),
        ]
    )
    logging.info("==============================Tablet_Tool start==============================")
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
