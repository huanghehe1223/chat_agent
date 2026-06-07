from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_initial_project_structure_exists():
    expected_paths = [
        ".env.example",
        "README.md",
        "TASK_BREAKDOWN.md",
        "TASK_TRACKING.md",
        "PROMPTS_AND_NOTES.md",
        "pytest.ini",
        "requirements.txt",
        "src/__init__.py",
        "src/main.py",
        "src/web.py",
        "src/agent/__init__.py",
        "src/agent/config.py",
        "src/agent/runtime.py",
        "src/agent/llm.py",
        "src/agent/memory.py",
        "src/agent/schemas.py",
        "src/agent/trace.py",
        "src/tools/__init__.py",
        "src/tools/calculator.py",
        "src/tools/search.py",
        "src/tools/todo.py",
        "src/tools/registry.py",
        "data/sessions/.gitkeep",
        "data/traces/.gitkeep",
    ]

    missing = [path for path in expected_paths if not (ROOT / path).exists()]

    assert missing == []


def test_env_example_contains_required_keys():
    content = (ROOT / ".env.example").read_text(encoding="utf-8")

    for key in [
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "MAX_AGENT_STEPS",
        "TAVILY_API_KEY",
    ]:
        assert key in content
