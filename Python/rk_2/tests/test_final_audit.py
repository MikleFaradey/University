"""Final instructor-spec regression tests for exact source integrity and fault recovery."""
from __future__ import annotations
from pathlib import Path
import sys
import pandas as pd
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source_reference import REFERENCE_COUNTS, REFERENCE_GIT_SHA, git_blob_sha, matches_reference
from fetch_datasets import valid_csv
from data import FIELDS, YEARS, read_datasets, get_metrics
from scripts_check import main as audit_main


def _sample(year=2020):
    row={name:'Low' for name in FIELDS}
    row.update(cve_id=f'CVE-{year}-12345',date=f'{year}-01-01',cvss_score=7.5,
               affected_hosts=20,attack_type='RCE',vendor='Acme',product='Tool',
               severity='High',attack_vector='Network',attacker_country='USA',
               target_sector='Education',status='Patched',exploit_available='No')
    return row


def _save(folder,year,rows):
    file=folder/f'cyberattacks_cve_{year}.csv'
    pd.DataFrame(rows).to_csv(file,index=False)
    return file


def test_reference_manifest_covers_exactly_all_instructor_years():
    assert sorted(REFERENCE_COUNTS)==YEARS
    assert sorted(REFERENCE_GIT_SHA)==YEARS
    assert sum(REFERENCE_COUNTS.values())==15847
    assert all(len(sha)==40 for sha in REFERENCE_GIT_SHA.values())


def test_csv_reader_rejects_duplicate_invalid_dates_and_missing_rows(tmp_path):
    file=_save(tmp_path,2020,[_sample(),_sample()])
    assert not valid_csv(file,2020)
    file=_save(tmp_path,2020,[_sample() | {'date':'2020-02-30'}])
    assert not valid_csv(file,2020)
    file=_save(tmp_path,2020,[_sample()])
    assert valid_csv(file,2020)
    assert not valid_csv(file,2020,verify_reference=True)  # a partial CSV is NOT the original file


def test_git_blob_checksum_detects_corruption(tmp_path):
    file=_save(tmp_path,2020,[_sample()])
    original=git_blob_sha(file)
    assert not matches_reference(file,2020)
    file.write_bytes(file.read_bytes()+b'\n')
    assert original!=git_blob_sha(file)


def test_strict_audit_rejects_missing_years(tmp_path,capsys):
    _save(tmp_path,2020,[_sample()])
    assert audit_main(['--folder',str(tmp_path),'--strict'])==1
    assert 'ТРЕБУЕТ ВНИМАНИЯ' in capsys.readouterr().out


def test_all_invalid_or_missing_csv_graceful(tmp_path):
    _save(tmp_path,2019,[_sample(2019, ) | {'cvss_score':99}])
    frame,warnings=read_datasets(tmp_path,[2019,2020])
    assert frame.empty
    assert warnings
    assert get_metrics(frame)=={'total':0,'avg_cvss':0.0,'critical':0,'affected':0}
