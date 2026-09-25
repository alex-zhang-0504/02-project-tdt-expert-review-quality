from copy import deepcopy
from io import BytesIO
from unittest.mock import patch
from openpyxl import load_workbook
from tests.test_policy_admin import PolicyAdminTests
from tests.test_assessment import sample, payload
from tdt_scoring import questionnaire, scoring_policy
from tdt_scoring.assessment import confirm_roster
from tdt_scoring.subjective import save_review
from tdt_scoring.score_statistics import build_statistics, build_statistics_workbook


class QuestionnaireConfigTests(PolicyAdminTests):
    def setUp(self):
        super().setUp()
        self.qpath = self.path / 'subjective.json'
        self.qpath.write_bytes(questionnaire.POLICY_PATH.read_bytes())
        p = patch('tdt_scoring.questionnaire.POLICY_PATH', self.qpath)
        p.start(); self.addCleanup(p.stop)

    def update_subjective(self, parameters, previous=None):
        return self.request('policy/subjective', {'parameters': parameters,
            'previous_hash': previous or questionnaire.load()['sha256']}, method='PUT')

    def test_scopes_and_validation(self):
        original = questionnaire.load()
        self.assertEqual(self.update_subjective(deepcopy(original['parameters']))[0], 401)
        self.setup_admin()
        objective = scoring_policy.load_policy()['parameters']
        objective['subjective']['preparation']['high'] = 99
        self.assertEqual(self.update(objective)[0],400)
        objective = scoring_policy.load_policy()['parameters']
        objective['total_cap'] = 200
        self.assertEqual(self.update(objective)[0],400)
        for mutate in [lambda p:p.update(total_cap=200),
                       lambda p:p['dimensions'].pop(),
                       lambda p:p['dimensions'][0].update(title=''),
                       lambda p:p['scores']['preparation'].update(high=-1)]:
            changed=deepcopy(original['parameters']);mutate(changed)
            self.assertEqual(self.update_subjective(changed)[0],400)
        self.assertEqual(questionnaire.load(),original)
        with patch('tdt_scoring.policy_admin.atomic_write',side_effect=OSError()):
            self.assertEqual(self.update_subjective(deepcopy(original['parameters']))[0],500)
        self.assertEqual(questionnaire.load(),original)

    def test_old_batch_freezes_text_scores_and_export(self):
        old=sample(); name=old.experts[0].expert_name
        confirm_roster(old,[name],'old')
        original=deepcopy(old.assessment['questionnaire'])
        for mid in ('a','b'): save_review(old,payload(old,mid,name))
        old_total=build_statistics(old)['rows'][0]['subjective_total']
        self.setup_admin()
        changed=deepcopy(original['parameters'])
        changed['dimensions'][0]['title']='虚拟新版题目'
        changed['dimensions'][0]['options'][0]['title']='虚拟新版行为'
        changed['scores']['preparation']['high']=11
        code, receipt=self.update_subjective(changed)
        self.assertEqual(code,200)
        self.assertEqual(receipt['version'],str(int(original['version'])+1))
        self.assertEqual(questionnaire.snapshot(old),original)
        self.assertEqual(build_statistics(old)['rows'][0]['subjective_total'],old_total)
        book=load_workbook(BytesIO(build_statistics_workbook(old,True,'subjective')))
        self.assertEqual(book['主观打分']['B1'].value,original['parameters']['dimensions'][0]['title'])
        new=sample();confirm_roster(new,[name],'new')
        for mid in ('a','b'): save_review(new,payload(new,mid,name))
        self.assertEqual(build_statistics(new)['rows'][0]['subjective_total'],old_total+1)
        self.assertEqual(questionnaire.dimensions(new)[0]['title'],'虚拟新版题目')
        self.app=self.new_app()
        self.assertEqual(self.request('policy/subjective',method='GET')[1]['sha256'],receipt['sha256'])
        self.assertEqual(self.update_subjective(deepcopy(receipt['parameters']),original['sha256'])[0],401)
        self.setup_existing()
        self.assertEqual(self.update_subjective(deepcopy(receipt['parameters']),original['sha256'])[0],409)
        wrong=payload(new,'a',name);wrong.questionnaire_hash=original['sha256']
        with self.assertRaises(ValueError): save_review(new,wrong)

    def setup_existing(self):
        code,result=self.request('unlock',{'password':self.password})
        self.assertEqual(code,200);self.token=result['token']
