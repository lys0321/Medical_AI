import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tutor_model


class TutorModelTests(unittest.TestCase):
    def setUp(self):
        tutor_model._cache = None
        # 这组用例只验证本机 Ollama 传输；显式清空云端密钥，避免开发者本机
        # 的 .env（内置 API）把状态切换到云端而让断言失真。
        self.env = patch.dict(os.environ, {'MEDNEXUS_TUTOR_URL':'http://127.0.0.1:11434','MEDNEXUS_TUTOR_MODEL':'',
                                           'MEDNEXUS_API_KEY':'','MEDNEXUS_BASE_URL':'','MEDNEXUS_MODEL':''})
        self.env.start()

    def tearDown(self):
        self.env.stop(); tutor_model._cache = None

    def test_no_local_service_is_honestly_reported_without_generator(self):
        with patch.object(tutor_model,'_json_request',side_effect=OSError):
            self.assertFalse(tutor_model.status()['available'])
            self.assertIsNone(tutor_model.generator())

    def test_remote_or_credential_urls_are_not_contacted(self):
        for base in ['https://example.com','http://192.168.1.1:11434','http://u:p@localhost:11434','http://localhost:11434/other']:
            with patch.dict(os.environ,{'MEDNEXUS_TUTOR_URL':base}), patch.object(tutor_model,'_json_request') as request:
                self.assertFalse(tutor_model.status()['available']);request.assert_not_called()

    def test_requested_missing_model_does_not_silently_choose_another(self):
        with patch.dict(os.environ,{'MEDNEXUS_TUTOR_MODEL':'missing'}), patch.object(tutor_model,'_json_request',return_value={'models':[{'name':'qwen3:1.7b'}]}):
            self.assertFalse(tutor_model.status()['available'])

    def test_real_roles_history_and_grounding_reach_local_api(self):
        calls=[]
        def request(url,payload=None,timeout=2):
            calls.append((url,payload))
            if payload is None:
                return {'models':[{'name':'qwen3:1.7b'}]}
            return {'message':{'content':json.dumps({'message':'fixture','follow_up':'fixture','sources':[]})}}
        dialogue=[{'role':'user','content':'first'},{'role':'assistant','content':'previous explanation'}, {'role':'user','content':'why'}]
        with patch.object(tutor_model,'_json_request',side_effect=request):
            result=tutor_model.generator()('SYSTEM',{'learning_card':{'id':'note-fixture','text':'known passage'},'dialogue':dialogue})
        self.assertEqual(result['message'],'fixture')
        payload=calls[-1][1]
        self.assertEqual(payload['messages'][1:],dialogue)
        self.assertIn('known passage',payload['messages'][0]['content'])
        self.assertFalse(payload['think'])
        self.assertEqual(calls[-1][0],'http://127.0.0.1:11434/api/chat')

    def test_builtin_cloud_key_is_used_without_ollama(self):
        """配了内置 API 就该在没装 Ollama 的电脑/手机后端上直接可用。"""
        cloud = {'MEDNEXUS_API_KEY':'fixture-key','MEDNEXUS_BASE_URL':'https://open.bigmodel.cn/api/paas/v4',
                 'MEDNEXUS_MODEL':'glm-4-flash'}
        with patch.dict(os.environ, cloud), patch.object(tutor_model,'_json_request',side_effect=OSError) as local:
            status = tutor_model.status()
            self.assertTrue(status['available'])
            self.assertEqual(status['mode'],'cloud')
            self.assertIn('glm-4-flash',status['label'])
            self.assertIn('glm-4-flash',status['note'])
            generator = tutor_model.generator()
            local.assert_not_called()
        self.assertIsNotNone(generator)

    def test_cloud_can_be_switched_off(self):
        cloud = {'MEDNEXUS_API_KEY':'fixture-key','MEDNEXUS_BASE_URL':'https://open.bigmodel.cn/api/paas/v4',
                 'MEDNEXUS_MODEL':'glm-4-flash','MEDNEXUS_CLOUD':'0'}
        with patch.dict(os.environ, cloud), patch.object(tutor_model,'_json_request',side_effect=OSError):
            self.assertFalse(tutor_model.status()['available'])


if __name__ == '__main__':
    unittest.main()
