"""Regression tests for authentication, data quality, user isolation and charts."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auth import UserStore, AuthError
from charts import build_figures
from data import FIELDS, YEARS, default_filters, normalize_filters, read_datasets, apply_filters, get_metrics


def row(year=2020, number=12345, **changes):
    data={key:'Low' for key in FIELDS}
    data.update(cve_id=f'CVE-{year}-{number}', date=f'{year}-02-02',
                attack_type='RCE', vendor='Acme', product='Widget', cvss_score=9.5,
                severity='Critical', attack_vector='Network', attacker_country='USA',
                target_sector='Education', affected_hosts=200,
                status='Exploited', exploit_available='Yes')
    data.update(changes)
    return data


def save_csv(folder,year,rows):
    pd.DataFrame(rows).to_csv(folder/f'cyberattacks_cve_{year}.csv',index=False)


def test_in_memory_database_survives_multiple_connections():
    store=UserStore(':memory:')
    uid=store.register('alice','alice@example.org','strongpass123','strongpass123')
    assert store.authenticate('alice','strongpass123')['id']==uid
    store.save_settings(uid, {'years':[2020]})
    assert store.load_settings(uid)=={'years':[2020]}
    store.close()


def test_per_user_preferences_never_leak(tmp_path):
    store=UserStore(tmp_path/'users.sqlite3')
    a=store.register('alice','alice@example.org','password123','password123')
    b=store.register('bobby','bobby@example.org','password456','password456')
    store.save_settings(a,{'years':[2020],'cvss_min':8.0})
    store.save_settings(b,{'years':[2025],'cvss_min':1.0})
    assert store.load_settings(a)['years']==[2020]
    assert store.load_settings(b)['years']==[2025]
    assert store.load_settings(b)['cvss_min']==1.0
    with pytest.raises(AuthError): store.save_settings(999999,{'years':[2024]})
    with pytest.raises(AuthError): store.load_settings(999999)


def test_case_insensitive_login_email_and_invalid_password(tmp_path):
    store=UserStore(tmp_path/'users.sqlite3')
    store.register('Alice','ONE@EXAMPLE.ORG','password123','password123')
    assert store.authenticate('ALICE','password123')['login']=='Alice'
    with pytest.raises(AuthError):store.register('alice','two@example.org','password123','password123')
    with pytest.raises(AuthError):store.register('other','one@example.org','password123','password123')
    with pytest.raises(AuthError):store.authenticate('ALICE','wrong-password')


def test_parallel_registration_creates_all_users(tmp_path):
    path=tmp_path/'users.sqlite3'
    store=UserStore(path)
    def register(i):
        return store.register(f'user{i}',f'user{i}@example.org','password123','password123')
    with ThreadPoolExecutor(max_workers=6) as pool:
        ids=list(pool.map(register,range(15)))
    assert len(set(ids))==15
    assert store.authenticate('user14','password123')['id'] in ids


def test_data_quality_invalid_rows_are_reported(tmp_path):
    save_csv(tmp_path,2020,[row(),row(number=3,cvss_score=12),row(number=4,date='wrong'),
                            row(number=5,affected_hosts=-5),row(number=6,cve_id='not-a-cve'),
                            row()])
    data,warnings=read_datasets(tmp_path,[2020])
    assert len(data)==1
    assert 'пропущено 5' in warnings[0]
    assert get_metrics(data)['total']==1


def test_malformed_file_does_not_prevent_other_year(tmp_path):
    (tmp_path/'cyberattacks_cve_2020.csv').write_text('broken,headers\n1,2',encoding='utf8')
    save_csv(tmp_path,2021,[row(2021)])
    data,warnings=read_datasets(tmp_path,[2020,2021])
    assert len(data)==1 and int(data.iloc[0]['year'])==2021
    assert any('Отсутствуют поля' in s for s in warnings)


def test_missing_year_and_empty_filters(tmp_path):
    save_csv(tmp_path,2020,[row()])
    frame,warnings=read_datasets(tmp_path,[2020,2021])
    assert len(warnings)==1
    assert apply_filters(frame,{'years':[]}).empty
    assert len(apply_filters(frame,{'years':[2020],'cvss_min':9.0,'exploited_only':True}))==1
    assert apply_filters(frame,{'years':[2020],'exploit_only':True,'severity':['Low']}).empty


def test_legacy_and_corrupt_preferences_are_normalized():
    assert normalize_filters({'years':[2020,9999], 'cvss_min':50})['cvss_min']==10
    assert normalize_filters({'years':[], 'exploit_only':True})['years']==[]
    assert normalize_filters({'years':'garbage','cvss_min':'oops'})['years']==YEARS
    assert default_filters()['years'] is not default_filters()['years']


def test_four_figures_are_plotly_with_expected_counts(tmp_path):
    save_csv(tmp_path,2020,[row(),row(number=7777,vendor='Other',attack_type='XSS')])
    frame,warnings=read_datasets(tmp_path,[2020])
    figures=build_figures(frame)
    assert not warnings
    assert set(figures)=={'trend','attacks','vendors','heatmap'}
    for fig in figures.values():
        assert len(fig.data)>0
        assert 'data' in fig.to_plotly_json()
    assert int(figures['heatmap'].data[0].z.sum())==2
    assert build_figures(frame.iloc[0:0])=={}


def test_csv_export_round_trip_is_utf8(tmp_path):
    save_csv(tmp_path,2020,[row(product='Продукт')])
    frame,warnings=read_datasets(tmp_path,[2020])
    payload=frame.to_csv(index=False).encode('utf-8-sig')
    result=pd.read_csv(__import__('io').BytesIO(payload))
    assert result.loc[0,'product']=='Продукт'


def test_download_is_atomic_and_existing_valid_dataset_is_not_replaced(tmp_path,monkeypatch):
    import fetch_datasets
    import io
    source=pd.DataFrame([row(2020)]).to_csv(index=False).encode('utf-8')
    class FakeHTTPResponse(io.BytesIO):
        def __enter__(self):return self
        def __exit__(self,*args):self.close()
    calls=[]
    def fake_urlopen(req,timeout):
        calls.append(req.full_url)
        return FakeHTTPResponse(source)
    monkeypatch.setattr(fetch_datasets,'urlopen',fake_urlopen)
    assert 'Загружено:' in fetch_datasets.download_year(2020,tmp_path)
    path=tmp_path/'cyberattacks_cve_2020.csv'
    assert path.read_bytes()==source
    assert 'Есть:' in fetch_datasets.download_year(2020,tmp_path)
    assert len(calls)==1


def test_download_invalid_response_does_not_leave_partial_file(tmp_path,monkeypatch):
    import fetch_datasets
    import io
    class FakeHTTPResponse(io.BytesIO):
        def __enter__(self):return self
        def __exit__(self,*args):self.close()
    monkeypatch.setattr(fetch_datasets,'urlopen',lambda *args,**kw:FakeHTTPResponse(b'<html>error</html>'))
    with pytest.raises(ValueError):
        fetch_datasets.download_year(2019,tmp_path)
    assert list(tmp_path.iterdir())==[]
