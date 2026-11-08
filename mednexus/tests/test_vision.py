"""可选视觉模型：默认关闭，只返回未核验的描述。"""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tutor_model
import vision

IMAGE = Path(__file__).resolve().parents[1] / 'web' / 'mark.svg'


def with_env(model):
    environment = dict(os.environ)
    environment.pop('MEDNEXUS_VISION_MODEL', None)
    if model is not None:
        environment['MEDNEXUS_VISION_MODEL'] = model
    return patch.dict(os.environ, environment, clear=True)


class VisionTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with with_env(None):
            self.assertEqual(vision.configured_model(), '')
            self.assertIsNone(vision.describe(IMAGE))

    def test_configured_model_returns_unverified_description(self):
        with with_env('llava:7b'), \
                patch.object(tutor_model, '_config', return_value=('http://127.0.0.1:11434', '')), \
                patch.object(tutor_model, '_json_request',
                             return_value={'message': {'content': '一页组胚复习笔记。'}}) as request:
            result = vision.describe(IMAGE)
        self.assertEqual(result['text'], '一页组胚复习笔记。')
        self.assertEqual(result['model'], 'llava:7b')
        self.assertTrue(result['unverified'])
        self.assertIn('不能作为答案依据', result['notice'])
        payload = request.call_args[0][1]
        self.assertIn('images', payload['messages'][0])
        self.assertFalse(payload['stream'])

    def test_model_failure_returns_none_instead_of_raising(self):
        with with_env('llava:7b'), \
                patch.object(tutor_model, '_config', return_value=('http://127.0.0.1:11434', '')), \
                patch.object(tutor_model, '_json_request', side_effect=OSError('offline')):
            self.assertIsNone(vision.describe(IMAGE))

    def test_missing_image_returns_none(self):
        with with_env('llava:7b'):
            self.assertIsNone(vision.describe(IMAGE.parent / 'no-such-image.png'))

    def test_empty_model_reply_is_not_passed_off_as_description(self):
        with with_env('llava:7b'), \
                patch.object(tutor_model, '_config', return_value=('http://127.0.0.1:11434', '')), \
                patch.object(tutor_model, '_json_request', return_value={'message': {'content': '   '}}):
            self.assertIsNone(vision.describe(IMAGE))


if __name__ == '__main__':
    unittest.main()