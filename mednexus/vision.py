"""可选的视觉描述辅助：只生成描述，不参与判分、不进选项。

默认关闭。只有显式设置 ``MEDNEXUS_VISION_MODEL``（本机 Ollama 里已安装的视觉模型名，
例如 llava:7b）才会调用。返回值一律标 ``unverified``，界面必须写明"不能作为答案依据"。

图片只发往本机 Ollama（``tutor_model._config`` 只接受 127.0.0.1/localhost）。
"""
import base64
import os
from pathlib import Path

MAX_BYTES = 2_000_000
NOTICE = '模型描述，未经教师核验，不能作为答案依据；判分只看标注文件。'


def configured_model():
    return os.environ.get('MEDNEXUS_VISION_MODEL', '').strip()


def describe(image_path, model=None):
    """返回 ``{text, model, notice, unverified}`` 或 None（未配置/失败/图片过大）。"""
    name = (model or configured_model()).strip()
    if not name:
        return None
    path = Path(image_path)
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw or len(raw) > MAX_BYTES:
        return None
    try:
        import tutor_model
        base, _ = tutor_model._config()
        payload = {
            'model': name, 'stream': False, 'think': False,
            'messages': [{
                'role': 'user',
                'content': ('用中文客观描述这一页组胚复习资料：只描述可见的文字与图形，'
                            '不确定就说不确定，不要给诊断、结论或记忆建议。'),
                'images': [base64.b64encode(raw).decode('ascii')],
            }],
            'options': {'temperature': 0.2, 'num_predict': 300},
        }
        result = tutor_model._json_request(base + '/api/chat', payload, timeout=90)
    except Exception:
        return None
    content = result.get('message', {}) if isinstance(result, dict) else {}
    text = content.get('content')
    if not isinstance(text, str) or not text.strip():
        return None
    return {'text': text.strip()[:800], 'model': name, 'notice': NOTICE, 'unverified': True}