"""channel_adapters/__init__.py — adapter registry"""
import json, pathlib
from .cluster_a import REGISTRY as _A, get_all as get_a
from .cluster_b import REGISTRY as _B, get_all as get_b
from .cluster_c import REGISTRY as _C, get_all as get_c
from .cluster_d import REGISTRY as _D, get_all as get_d

ALL_REGISTRY = {**_A, **_B, **_C, **_D}

_PLATFORM_STATUS = pathlib.Path('/root/my_personal_ai/data/platform_status.json')
_LIVE_STATUSES = {'logged_in', 'already_exists', 'registered', 'partial'}

# adapter_name -> keys to look up in platform_status.json
_PLATFORM_KEY_MAP = {
    'n8n':            ['n8n', 'n8n_cloud'],
    'zapier':         ['zapier', 'zapier_login'],
    'relevance_ai':   ['relevance_ai'],
    'pipedream':      ['pipedream'],
    'make_com':       ['make', 'make_com'],
    'vellum':         ['vellum'],
    'flowise':        ['flowise_cloud', 'flowise'],
    'langflow':       ['langflow_cloud', 'langflow'],
    'coze':           ['coze'],
    'poe':            ['poe'],
    'huggingface':    ['huggingface'],
    'github_actions': ['github'],
    'gpt_store':      ['gpt_store'],
    'dify_ai':        ['dify'],
}

def _load_platform_status():
    try:
        if _PLATFORM_STATUS.exists():
            return json.loads(_PLATFORM_STATUS.read_text())
    except Exception:
        pass
    return {}

def _is_registered(adapter_name, ps):
    keys = _PLATFORM_KEY_MAP.get(adapter_name, [adapter_name])
    for k in keys:
        entry = ps.get(k) or {}
        if isinstance(entry, dict):
            status = entry.get('status', '')
        else:
            status = str(entry)
        if status in _LIVE_STATUSES:
            return True, status
    return False, 'unknown'

def get_all_adapters():
    return {**get_a(), **get_b(), **get_c(), **get_d()}

def get_adapter(platform: str):
    cls = ALL_REGISTRY.get(platform)
    return cls() if cls else None

def get_fleet_status():
    adapters = get_all_adapters()
    ps = _load_platform_status()
    result = {}
    for name, a in adapters.items():
        h = a.health()
        registered, reg_status = _is_registered(name, ps)
        if registered:
            h['mock'] = False
            h['key_set'] = True
            h['reg_status'] = reg_status
        result[name] = h
    return result

CLUSTERS = {
    "A": {"name":"Labor Marketplaces","adapters":list(_A.keys())},
    "B": {"name":"DePIN / Off-chain","adapters":list(_B.keys())},
    "C": {"name":"Corporate Divisions","adapters":list(_C.keys())},
    "D": {"name":"Discovery Hubs","adapters":list(_D.keys())},
}
