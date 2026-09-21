import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

@pytest.fixture(autouse=True)
def mock_translation(monkeypatch):
    from app import llm_generation
    
    def mock_translate(q):
        return q, 'English'
    monkeypatch.setattr(llm_generation, 'translate_to_english', mock_translate)

    def mock_llm_answer(evidence, target_language='English'):
        return None
    monkeypatch.setattr(llm_generation, 'llm_answer', mock_llm_answer)
