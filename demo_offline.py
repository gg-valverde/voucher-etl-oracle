"""Demuestra la transformación con datos ficticios. No realiza conexiones."""
import csv
import json
from pathlib import Path
from voucher_etl import preparar_fila

def demo():
    root = Path(__file__).resolve().parent
    vouchers = json.loads((root / 'sample_vouchers.json').read_text(encoding='utf-8'))
    rows = [preparar_fila(v, 'Campaña ficticia de portafolio') for v in vouchers]
    columns = ['id', 'voucher_config', 'campana_voucher', 'amount', 'generated', 'used', 'expiration', 'status_label']
    output = root / 'output'
    output.mkdir(exist_ok=True)
    with (output / 'vouchers_demo.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    print('Demo sin API ni Oracle: {} vouchers ficticios transformados.'.format(len(rows)))
    print('Salida: output/vouchers_demo.csv. Las fechas se convierten de UTC a UTC-4.')
    return rows

if __name__ == '__main__':
    demo()
