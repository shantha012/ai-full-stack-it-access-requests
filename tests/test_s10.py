import dataclasses
import json
from test_s09 import DurableCase

class T21(DurableCase):
    def test_each_producing_setting_invalidates_and_refreshes(self):
        from access_requests.config import Settings
        from access_requests.engine import Engine
        original=Settings()
        first=Engine(self.store,original).intake([self.one],self.provider('it-001'))[0]
        variants=[dataclasses.replace(original,model='test-model-2'),
                  dataclasses.replace(original,max_output_tokens=1234),
                  dataclasses.replace(original,prompt=original.prompt+' Extract carefully.'),
                  dataclasses.replace(original,schema=dict(original.schema,description='test schema version')),
                  dataclasses.replace(original,policy=original.policy+'\nTest comment.'),
                  dataclasses.replace(original,policy=original.policy.replace('go to System Owner','go to Test Reviewer'))]
        fingerprints={first['settings_fingerprint']}
        for setting in variants:
            engine=Engine(self.store,setting)
            result=engine.intake([self.one],self.provider('it-001'))[0]
            self.assertNotIn(result['settings_fingerprint'],fingerprints)
            fingerprints.add(result['settings_fingerprint'])
            self.assertEqual(result['producing_settings'],setting.public())
            self.assertEqual(result['policy_version'],setting.policy_version)
        self.assertEqual(result['owner'],'Test Reviewer')
        refreshed=Engine(self.store,original).refresh('IT-001.json',self.provider('it-001'))
        self.assertEqual(refreshed['owner'],'System Owner')
        self.assertNotEqual(first['attempt_id'],refreshed['attempt_id'])
        self.assertEqual(self.store.attempts()[0],first)
