"""MedNexus 入口：按域拆到 api/ 之后，这里只做兼容导出与启动。

`python server.py` 仍然可用；老代码里 `from server import report` 也仍然可用。
写 `server.DB_PATH = ...` 会同步到底座模块，所以既有的测试夹具不需要改。
"""
import sys
import types

# 保持拆分前的可见性：旧代码（含测试）会直接读 server.subprocess / server.time 等。
import argparse
import collections
import hashlib
import json
import math
import mimetypes
import os
import random
import re
import secrets
import shutil
import sqlite3
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

from api import core
from api.core import (ROOT, DB_PATH, QUICK_NOTES_PATH, QUICK_NOTES_SOURCE, LOCK,
                      TUTOR_LOCKS, API_KEY, MODEL, BASE_URL, DEFAULT_LEARNER,
                      is_private_ip, InputError, ClosingConnection, connect, init_db,
                      state_get, state_save, event, attempts_get, progress, recommend)
from api.task import (public_active, make_task, request_hint, tutor_context, tutor_messages, tutor_snapshot, tutor_turn)
from api.answer import (grade, answer_text, text_excerpts)
from api.study import (builtins, textbook_sources, all_sources, tokenize, retrieve, verify_citation, study_payload, import_sources, image_attempts, image_stats, image_quiz)
from api.ask import (model_json, ask, ask_compat, _textbook_key_points)
from api.research import (research_gate, ncbi_get, ncbi_get_url, windows_https_get, xmltext, pubmed, cached_paper, fetch_fulltext, export_citations, _check_research_privacy, research_query_for, research_request, pubmed_compat)
from api.report import (snapshot, report, export_learning, reset_learning, _book_stats, _recent, _weak, overview_payload,
                        record_study_seconds, time_stats, unit_stats)
from api.routing import Handler, main, ThreadingHTTPServer
import api.task as _task
import api.answer as _answer
import api.study as _study
import api.ask as _ask
import api.research as _research
import api.report as _report
import api.routing as _routing
from knowledge import CONCEPTS, CONCEPT_MAP, QUESTION_MAP, SOURCES, COURSE
import materials
import textbook
import tutor_model
import tutor_chat
import text_grading
import citations
import evidence
import pmc
import histology_quiz
import vision

_CORE_NAMES = {'attempts_get', 'DEFAULT_LEARNER', 'TUTOR_LOCKS', 'event', 'connect', 'DB_PATH', 'progress', 'ROOT', 'init_db', 'API_KEY', 'QUICK_NOTES_PATH', 'state_get', 'LOCK', 'BASE_URL', 'recommend', 'MODEL', 'state_save', 'InputError', 'ClosingConnection', 'QUICK_NOTES_SOURCE', 'is_private_ip'}

# 拆分后同一个名字可能在多个域模块里各有一份绑定。既有代码（含测试夹具）习惯
# 写 `server.X = ...` 来替换实现，这里把赋值同步到所有持有该名字的模块，
# 保证“改 server.X”仍然等于“改真正被调用的那个实现”。
_DOMAIN_MODULES = (core, _task, _answer, _study, _ask, _research, _report, _routing)


class _CompatModule(types.ModuleType):
    """写 server.X 时同步到持有该名字的域模块。"""

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for module in _DOMAIN_MODULES:
            if hasattr(module, name):
                setattr(module, name, value)


sys.modules[__name__].__class__ = _CompatModule

if __name__ == "__main__":
    main()
