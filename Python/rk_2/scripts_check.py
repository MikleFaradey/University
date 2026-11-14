from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys
from charts import build_figures
from data import YEARS, read_datasets, get_metrics
from source_reference import REFERENCE_COUNTS, matches_reference

def main(argv=None):
    parser = argparse.ArgumentParser(description='Проверка всех CSV РК-2')
    parser.add_argument('--folder', default=os.environ.get('CVE_DATA_DIR', str(Path(__file__).resolve().parent / 'cve_datasets')))
    parser.add_argument('--strict', action='store_true', help='Ошибка выхода при отсутствии файлов или плохих строках')
    parser.add_argument('--check-reference', action='store_true', help='Сверить количество строк каждого года с исходными файлами преподавателя')
    args = parser.parse_args(argv)
    df, warnings = read_datasets(args.folder, YEARS)
    print('=== Проверка исходных CSV за 2014–2026 ===')
    for year in YEARS:
        count = int(df['year'].eq(year).sum()) if not df.empty else 0
        print(f'{year}: {count} строк')
        if args.check_reference:
            if count != REFERENCE_COUNTS[year]:
                warnings.append(f'{year}: ожидалось {REFERENCE_COUNTS[year]} записей по эталону, получено {count}')
            filepath = Path(args.folder) / f'cyberattacks_cve_{year}.csv'
            if filepath.exists() and (not matches_reference(filepath, year)):
                warnings.append(f'{year}: контрольная сумма не совпадает с оригинальным CSV преподавателя')
    print('Итого:', len(df))
    if args.strict and len(df) > 0:
        loaded = set(df['year'].astype(int).unique())
        missing = set(YEARS) - loaded
        if missing:
            warnings.append('Отсутствуют записи за годы: ' + ', '.join(map(str, sorted(missing))))
    if args.check_reference and len(df) != sum(REFERENCE_COUNTS.values()):
        warnings.append(f'Неверное общее количество: {len(df)}; ожидалось {sum(REFERENCE_COUNTS.values())}')
    if not df.empty:
        print('KPI:', get_metrics(df))
        fig = build_figures(df)
        print('Графики:', ', '.join(fig))
    for problem in warnings:
        print('ПРЕДУПРЕЖДЕНИЕ:', problem)
    print('Итог:', 'OK' if len(df) > 0 and (not warnings) else 'ТРЕБУЕТ ВНИМАНИЯ')
    return 1 if not len(df) or (args.strict and warnings) else 0
if __name__ == '__main__':
    sys.exit(main())
