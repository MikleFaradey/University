import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from auth import UserStore,AuthError
from data import read_datasets,apply_filters,get_metrics,DEFAULTS

class TestAuth(unittest.TestCase):
    def test_registration_login_and_preferences(self):
        with tempfile.TemporaryDirectory() as d:
            store=UserStore(Path(d)/'users.db')
            uid=store.register('student','s@example.org','strongpass123','strongpass123')
            self.assertEqual(store.authenticate('student','strongpass123')['id'],uid)
            with self.assertRaises(AuthError):store.authenticate('student','wrong')
            with self.assertRaises(AuthError):store.register('student','x@example.org','strongpass123','strongpass123')
            store.save_settings(uid,{'years':[2020]})
            self.assertEqual(store.load_settings(uid),{'years':[2020]})
    def test_bad_password(self):
        with tempfile.TemporaryDirectory() as d:
            store=UserStore(Path(d)/'users.db')
            with self.assertRaises(AuthError):store.register('okuser','x@example.org','123','123')

class TestData(unittest.TestCase):
    def test_load_filter_metrics_and_missing_year(self):
        with tempfile.TemporaryDirectory() as d:
            base={name:'sample' for name in ['cve_id','date','attack_type','vendor','product','severity','attack_vector','access_complexity','privileges_required','user_interaction','confidentiality_impact','integrity_impact','availability_impact','attacker_country','target_sector','status','exploit_available']}
            rows=[]
            for year in [2020,2021]:
                row=dict(base,cve_id=f'CVE-{year}-12345',date=f'{year}-02-02',cvss_score=9.8,affected_hosts=150,severity='Critical',attack_type='RCE',status='Exploited',exploit_available='Yes')
                rows.append(row)
                pd.DataFrame([row]).to_csv(Path(d)/f'cyberattacks_cve_{year}.csv',index=False)
            frame,errors=read_datasets(d,[2020,2021,2022])
            self.assertEqual(len(frame),2)
            self.assertEqual(len(errors),1)
            result=apply_filters(frame,dict(DEFAULTS,years=[2020],cvss_min=9.0,exploit_only=True))
            self.assertEqual(len(result),1)
            self.assertEqual(get_metrics(result)['critical'],1)
            self.assertEqual(get_metrics(result)['affected'],150)
            self.assertEqual(len(apply_filters(frame,dict(DEFAULTS,years=[]))),0)

if __name__=='__main__': unittest.main()
