"""Safely download the original 13 yearly datasets with atomic replacement."""
from __future__ import annotations
import csv
import datetime as dt
import math
import re
from pathlib import Path
import os
import sys
import tempfile
from urllib.request import urlopen,Request
from data import FIELDS, YEARS
from source_reference import matches_reference

ROOT='https://raw.githubusercontent.com/Kulikova-A18/python-iu8-13M-2026-2027/main/rk-2/cve_datasets'
DEST=Path(os.environ.get('CVE_DATA_DIR', str(Path(__file__).resolve().parent/'cve_datasets')))


def valid_csv(path, year=None, verify_reference=False):
    """Reject incomplete CSV files, malformed rows and inconsistent year metadata."""
    try:
        if not path.is_file() or path.stat().st_size < 100:
            return False
        with path.open('r', encoding='utf-8-sig', newline='') as f:
            reader = csv.reader(f, strict=True)
            header = next(reader)
            if len(set(header)) != len(header) or not set(FIELDS).issubset(set(header)):
                return False
            ix = {name: header.index(name) for name in ('cve_id', 'date', 'cvss_score', 'affected_hosts')}
            count = 0
            seen_ids = set()
            for row in reader:
                if len(row) != len(header):
                    return False
                if year is not None:
                    identifier = row[ix['cve_id']]
                    if not re.fullmatch(fr'CVE-{year}-[0-9]{{4,}}',identifier):
                        return False
                    if identifier in seen_ids:
                        return False
                    seen_ids.add(identifier)
                    if dt.date.fromisoformat(row[ix['date']]).year != year:
                        return False
                try:
                    score = float(row[ix['cvss_score']])
                    hosts = int(row[ix['affected_hosts']])
                    if not math.isfinite(score) or not 0 <= score <= 10 or hosts < 0:
                        return False
                except (ValueError, OverflowError):
                    return False
                count += 1
            return count > 0 and (not verify_reference or (year is not None and matches_reference(path,year)))
    except (OSError, StopIteration, ValueError, UnicodeError, csv.Error):
        return False


def download_year(year: int, dest: Path=DEST, verify_reference: bool | None=None):
    if verify_reference is None:
        verify_reference = Path(dest).resolve() == DEST.resolve()
    dest.mkdir(parents=True,exist_ok=True)
    path=dest/f'cyberattacks_cve_{year}.csv'
    if valid_csv(path,year,verify_reference=verify_reference):
        return f'Есть: {path.name}'
    url=f'{ROOT}/{path.name}'
    temp_name=None
    try:
        req=Request(url,headers={'User-Agent':'IU8-CVE-Academic-Demo/2.0'})
        with urlopen(req,timeout=40) as source:
            with tempfile.NamedTemporaryFile(dir=dest,suffix='.part',delete=False) as file:
                temp_name=file.name
                while True:
                    chunk=source.read(65536)
                    if not chunk:break
                    file.write(chunk)
        staged=Path(temp_name)
        if not valid_csv(staged,year,verify_reference=verify_reference):
            raise ValueError('Получен повреждённый CSV или отсутствуют обязательные поля')
        os.replace(staged,path)
        return f'Загружено: {path.name} ({path.stat().st_size} байт)'
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def main():
    failures=0
    for year in YEARS:
        try:print(download_year(year))
        except (OSError,ValueError,TimeoutError) as exc:
            failures+=1
            print(f'ОШИБКА {year}: {exc}',file=sys.stderr)
    return 1 if failures else 0


if __name__=='__main__':
    sys.exit(main())
