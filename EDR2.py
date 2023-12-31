import os
import time
import psutil
import concurrent.futures
import threading
from collections import defaultdict
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import logging

THRESHOLD = 10
MAX_THREADS = 4

class RansomwareFileHandler(FileSystemEventHandler):
    def __init__(self, valid_extensions, executor, edr_pid):
        super().__init__()
        self.file_changes = defaultdict(int)
        self.lock = threading.Lock()
        self.valid_extensions = valid_extensions
        self.executor = executor
        self.edr_pid = edr_pid

    def on_modified(self, event):
        if event.is_directory:
            return

        file_extension = os.path.splitext(event.src_path)[1]
        if file_extension in self.valid_extensions:
            self.executor.submit(self.process_file_change, event.src_path)

    def process_file_change(self, path):
        with self.lock:
            self.file_changes[path] += 1
            pid = os.getpid()
            ppid = os.getppid()
            process_name = psutil.Process(pid).name()
            parent_process_name = psutil.Process(ppid).name()
            logging.info(f"Suspected process (PID {pid}, PPID {ppid}): {process_name} (Parent: {parent_process_name}) modified file: {path}")

class HoneypotFileHandler(FileSystemEventHandler):
    def __init__(self, honeypot_files):
        super().__init__()
        self.honeypot_files = honeypot_files

    def on_modified(self, event):
        if event.is_directory:
            return

        if event.src_path in self.honeypot_files:
            print(f"Honeypot file modified: {event.src_path}")

class EDR:
    def __init__(self):
        self.suspicious_pids = set()
        self.lock = threading.Lock()
        self.valid_extensions = (".txt", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf", ".jpg", ".png", ".bmp", ".gif", ".mp3", ".mp4")
        self.executor = concurrent.futures.ThreadPoolExecutor(MAX_THREADS)


        self.edr_pid = os.getpid()


        logging.basicConfig(filename='edr.log', level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

        self.file_handler = RansomwareFileHandler(self.valid_extensions, self.executor, self.edr_pid)

    def start(self):
        try:
            self.print_edr_status("Iniciando EDR")
            pastas_monitoradas = [os.path.expanduser(f"~/{folder}") for folder in ["Desktop", "Documents", "Downloads"]]
            honeypot_files = self.create_honeypot_files()

            self.start_observer(pastas_monitoradas)
            honeypot_observer = self.start_honeypot_observer(honeypot_files)
            self.print_edr_status("EDR iniciado")

            while True:
                time.sleep(1)
                with self.lock:
                    self.identificar_processos_suspeitos()
        except KeyboardInterrupt:
            self.stop_observer()
            self.stop_honeypot_observer(honeypot_observer)
            self.finalizar_processos_suspeitos()
            self.print_edr_status("EDR finalizado")

    def start_observer(self, pastas_monitoradas):
        self.file_handler_observer = Observer()
        for pasta in pastas_monitoradas:
            self.file_handler_observer.schedule(self.file_handler, pasta, recursive=True)
        self.file_handler_observer.start()

    def stop_observer(self):
        if self.file_handler_observer:
            self.file_handler_observer.stop()
            self.file_handler_observer.join()

    def start_honeypot_observer(self, honeypot_files):
        honeypot_observer = Observer()
        honeypot_handler = HoneypotFileHandler(honeypot_files)
        for honeypot_file in honeypot_files:
            honeypot_observer.schedule(honeypot_handler, os.path.dirname(honeypot_file))
        honeypot_observer.start()
        return honeypot_observer

    def stop_honeypot_observer(self, honeypot_observer):
        if honeypot_observer:
            honeypot_observer.stop()
            honeypot_observer.join()

    def identificar_processos_suspeitos(self):
        IGNORAR_NOMES = ["test.exe", "powershell.exe"]
        with self.file_handler.lock:
            for path, mudanca in self.file_handler.file_changes.items():
                if mudanca >= THRESHOLD:
                    for processo_filho in psutil.process_iter(['pid', 'name', 'ppid']):
                        try:
                            processo_info = processo_filho.info
                            pid_filho = processo_info['pid']
                            ppid = processo_info['ppid']
                            nome_processo = processo_info['name']

                            if nome_processo not in IGNORAR_NOMES:
                                if self.processo_interagindo_arquivo(pid_filho, path):
                                    with self.lock:
                                        self.suspicious_pids.add(pid_filho)
                                        print(f"Processo filho suspeito encontrado (PID {pid_filho}): {nome_processo}")

                                    if ppid != self.edr_pid:
                                        try:
                                            processo_pai = psutil.Process(ppid)
                                            processo_pai.terminate()
                                            print(f"Processo pai (PID {ppid}) encerrado.")
                                        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                                            print(f"Não foi possível encerrar o processo pai (PID {ppid}).")
                        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                            print("Não foi possível identificar o processo suspeito.")
                            pass

    def processo_interagindo_arquivo(self, pid, path_arquivo):
        try:
            processo = psutil.Process(pid)
            abrir_arquivos = processo.open_files()
            for arquivo in abrir_arquivos:
                if path_arquivo == arquivo.path:
                    return True
            return False
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

    def finalizar_processos_suspeitos(self):
        for pid in self.suspicious_pids:
            try:
                process = psutil.Process(pid)
                process.terminate()
                print(f"Processo com PID {pid} finalizado.")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

    def create_honeypot_files(self):
        honeypot_files = []
        desktop_path = os.path.expandvars("%USERPROFILE%\\Desktop")
        honeypot_base_path = os.path.join(desktop_path, "Honeypots")

        if not os.path.exists(honeypot_base_path):
            os.makedirs(honeypot_base_path)
            self.print_edr_status("Criando honeypots")

        for i in range(1, 6):
            honeypot_file = os.path.join(honeypot_base_path, f"Honeypot{i}.txt")
            honeypot_files.append(honeypot_file)

            with open(honeypot_file, "w") as f:
                f.write("This is a honeypot file. Do not access it.")

        self.print_edr_status("Honeypots criados")
        return honeypot_files

    def print_edr_status(self, status):
        print('/////////////////////////////////')
        print(f'-------- {status} ---------')
        print('---------------------------------')
        print('')

if __name__ == '__main__':
    try:
        edr = EDR()
        edr.start()
    except Exception as e:
        print(f"Erro inesperado: {e}")
