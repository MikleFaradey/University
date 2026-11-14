"""UI-level smoke test using official Streamlit AppTest (when installed)."""
from __future__ import annotations
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

streamlit=pytest.importorskip('streamlit',reason='Для UI-теста установите requirements.txt')
from streamlit.testing.v1 import AppTest


def test_guests_see_login_and_registration(tmp_path,monkeypatch):
    monkeypatch.setenv('CVE_DB',str(tmp_path/'test_users.sqlite3'))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=20).run()
    assert not app.exception
    assert any('CVE Analytics' in h.value for h in app.title)
    assert len(app.text_input)>=5


def test_first_login_has_no_dashboard_until_authenticated(tmp_path,monkeypatch):
    monkeypatch.setenv('CVE_DB',str(tmp_path/'test_users.sqlite3'))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=20).run()
    assert not app.exception
    assert not app.metric  # KPI only accessible after authentication


def test_register_login_dashboard_and_persist_settings(tmp_path,monkeypatch):
    from data import FIELDS
    import pandas as pd
    data_dir=tmp_path/'cve_datasets'
    data_dir.mkdir()
    record={f:'Low' for f in FIELDS}
    record.update(cve_id='CVE-2020-12345',date='2020-01-01',attack_type='RCE',vendor='Acme',product='Widget',cvss_score=9.1,severity='Critical',attack_vector='Network',attacker_country='USA',target_sector='IT',affected_hosts=12,status='Exploited',exploit_available='Yes')
    pd.DataFrame([record]).to_csv(data_dir/'cyberattacks_cve_2020.csv',index=False)
    monkeypatch.setenv('CVE_DB',str(tmp_path/'userstore.sqlite3'))
    monkeypatch.setenv('CVE_DATA_DIR',str(data_dir))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=25).run()
    assert not app.exception
    # Login form has fields 0-1, registration has 2-5.
    app.text_input[2].set_value('student')
    app.text_input[3].set_value('student@example.org')
    app.text_input[4].set_value('strongpassword123')
    app.text_input[5].set_value('strongpassword123')
    app.button[1].click().run()
    assert not app.exception
    app.text_input[0].set_value('student')
    app.text_input[1].set_value('strongpassword123')
    app.button[0].click().run()
    assert not app.exception
    assert len(app.metric)==4
    assert any('Всего записей'==metric.label for metric in app.metric)
    assert any('Пользователь:' in str(item.value) for item in app.markdown)


def test_settings_change_dashboard_and_reset(tmp_path,monkeypatch):
    from data import FIELDS
    import pandas as pd
    data_dir=tmp_path/'csv'
    data_dir.mkdir()
    records=[]
    for year in [2020,2021]:
        record={f:'Low' for f in FIELDS}
        record.update(cve_id=f'CVE-{year}-12345',date=f'{year}-01-01',
                      attack_type='RCE',vendor='Acme',product='Widget',cvss_score=9.1,
                      severity='Critical',attack_vector='Network',attacker_country='USA',
                      target_sector='IT',affected_hosts=12,status='Exploited',exploit_available='Yes')
        records.append(record)
        pd.DataFrame([record]).to_csv(data_dir/f'cyberattacks_cve_{year}.csv',index=False)
    monkeypatch.setenv('CVE_DB',str(tmp_path/'users.sqlite3'))
    monkeypatch.setenv('CVE_DATA_DIR',str(data_dir))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=25).run()
    app.text_input[2].set_value('student')
    app.text_input[3].set_value('student@example.org')
    app.text_input[4].set_value('strongpassword123')
    app.text_input[5].set_value('strongpassword123')
    app.button[1].click().run()
    app.text_input[0].set_value('student')
    app.text_input[1].set_value('strongpassword123')
    app.button[0].click().run()
    assert not app.exception
    assert len(app.metric)==4
    assert '2' in app.metric[0].value
    app.sidebar.radio[0].set_value('Настройки').run()
    assert not app.exception
    app.multiselect[0].set_value([2020])
    # Save button is the first button in the settings form.
    next(b for b in app.button if b.label=='Сохранить настройки').click().run()
    assert not app.exception
    app.sidebar.radio[0].set_value('Аналитика').run()
    assert not app.exception
    assert '1' in app.metric[0].value
