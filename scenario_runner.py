#!/usr/bin/env python3
"""
Executa cenários de disponibilidade definidos em CSV:
start,end,status,stage   (coluna stage é opcional)
"""
import argparse
import csv
import subprocess
import sys
import time
from pathlib import Path

def parse_ts(ts: str) -> int:
    parts = list(map(int, ts.strip().split(":")))
    return parts[-1] + parts[-2]*60 + (parts[-3] if len(parts)==3 else 0)*3600

def load_intervals(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    ints = []
    for r in rows:
        start, end, status = r["start"], r["end"], r["status"].lower()
        stage = r.get("stage", "").strip() or "Unnamed stage"
        if status not in {"up", "down"}:
            sys.exit("CSV inválido: status deve ser 'up' ou 'down'.")
        s, e = parse_ts(start), parse_ts(end)
        if e < s:
            sys.exit(f"Intervalo invertido: {start}-{end}")
        ints.append((s, e, status, stage))
    return ints

def send_once(cmd):
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        print(f"[{time.strftime('%H:%M:%S')}] ✅ Comando enviado com sucesso: {' '.join(cmd)}")
    except subprocess.CalledProcessError as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ Erro ao enviar comando: {e}")

def send_in_background(cmd):
    """
    Executa o comando em background e retorna o processo.
    """
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[{time.strftime('%H:%M:%S')}] ✅ Comando iniciado em background: {' '.join(cmd)} (PID: {process.pid})")
        return process
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ Erro ao iniciar comando em background: {e}")
        return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario-file", required=True)
    ap.add_argument("--rate", type=float, default=1.0)
    args = ap.parse_args()

    base_cmd = [sys.executable, "manage.py", "send_telemetry",
                "--use-influx", "--randomize"]

    intervals = load_intervals(args.scenario_file)
    t0 = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] ▶️  Executando {len(intervals)} intervalos para devices")

    try:
        for start, end, status, stage in intervals:
            # Aguarda o início do intervalo
            while time.time() - t0 < start:
                remaining = start - (time.time() - t0)
                print(f"[{time.strftime('%H:%M:%S')}] ⏳ Aguardando início do intervalo {stage} ({remaining:.1f}s restantes)")
                time.sleep(0.5)

            print(f"[{time.strftime('%H:%M:%S')}] -- {stage}: {status.upper()} {start}s → {end}s")

            # Executa dentro do intervalo
            process = None
            if status == "up":
                process = send_in_background(base_cmd)
            elif status == "down":
                print(f"[{time.strftime('%H:%M:%S')}] 🔴 Status DOWN...")

            while time.time() - t0 <= end:
                time.sleep(0.2)

            # Finaliza o processo em background, se existir
            if process:
                process.terminate()
                process.wait()  # Aguarda o término do processo
                print(f"[{time.strftime('%H:%M:%S')}] ⏹️  Comando encerrado (PID: {process.pid})")

            # Garante que o script avance mesmo se o tempo atual ultrapassar o final do intervalo
            current_time = time.time() - t0
            if current_time > end:
                print(f"[{time.strftime('%H:%M:%S')}] ⏭️  Finalizando intervalo {stage} ({end}s, atual: {current_time:.1f}s)")

        print(f"[{time.strftime('%H:%M:%S')}] 🏁  Cenário concluído.")
    except KeyboardInterrupt:
        print(f"\n[{time.strftime('%H:%M:%S')}] 🛑  Abortado pelo usuário.")

if __name__ == "__main__":
    if not Path("manage.py").is_file():
        sys.exit("Execute o script na pasta onde fica o manage.py.")
    main()

# python scenario_runner.py --device-id 1 --scenario-file scenario_runner_30min.csv