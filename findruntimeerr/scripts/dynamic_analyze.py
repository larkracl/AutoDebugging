import sys
import json
import traceback
import astroid
import os
import requests  # remove this line

# Google GenAI client for Gemini API
import base64
from google import genai
from google.genai import types

# Load API key from secret.properties if present, else from environment
script_dir = os.path.dirname(__file__)
project_root = os.path.abspath(os.path.join(script_dir, os.pardir))
properties_file = os.path.join(project_root, "secret.properties")
api_key = None
if os.path.exists(properties_file):
    try:
        with open(properties_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    key, sep, val = line.partition("=")
                    if key.strip() == "GEMINI_API_KEY" and sep == "=":
                        api_key = val.strip()
                        break
    except Exception:
        pass
GEMINI_API_KEY = api_key or os.getenv("GEMINI_API_KEY")

# Configuration for Gemini free API
GEMINI_API_URL = "https://api.gemini.com/v1/generate"

def parse_functions(code: str):
    """
    AST를 사용해 코드에서 함수 정의를 추출하고, 각 함수의 코드, 주석, 의존성을 반환합니다.
    """
    module = astroid.parse(code)
    functions = {}
    for node in module.body:
        if isinstance(node, astroid.FunctionDef):
            name = node.name
            # 함수 docstring 또는 주석 추출
            comment = node.doc_node.value if node.doc_node else ""
            func_code = node.as_string()
            functions[name] = {"code": func_code, "comment": comment, "node": node}

    # 각 함수가 호출하는 다른 사용자 함수 의존성 추출
    deps = {}
    for name, data in functions.items():
        calls = []
        for call in data["node"].nodes_of_class(astroid.Call):
            if isinstance(call.func, astroid.Name) and call.func.name in functions:
                calls.append(call.func.name)
        deps[name] = sorted(set(calls))
    return functions, deps

def generate_test_cases(func_name, comment):
    """
    Gemini API를 이용해 함수별 10개의 테스트케이스 생성 요청.
    """
    # Use Google GenAI client for Gemini API
    client = genai.Client(
        vertexai=True,
        project="",    # TODO: set your project ID or read from config
        location="",   # TODO: set your location or read from config
    )
    model = "gemini-2.5-flash-preview-04-17"
    prompt = (
        f"Generate exactly 10 test cases for the Python function `{func_name}`.\n"
        f"Description/comment: {comment}\n"
        "Return a JSON array of objects with fields: `input` (list of args) and `expected`."
    )
    print(f"[Gemini] Prompt for `{func_name}`: {prompt}", file=sys.stderr)
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=prompt),
            ],
        ),
    ]
    generate_content_config = types.GenerateContentConfig(
        response_mime_type="text/plain",
    )
    text = ""
    for chunk in client.models.generate_content_stream(
        model=model,
        contents=contents,
        config=generate_content_config,
    ):
        text += chunk.text
        print(f"[Gemini] Stream chunk for `{func_name}`: {chunk.text}", file=sys.stderr)
    try:
        cases = json.loads(text)
    except Exception as e:
        print(f"[Gemini] Failed to parse JSON for `{func_name}`: {e}", file=sys.stderr)
        cases = []
    return cases

def execute_function_tests(func_code, func_name, test_cases):
    """
    단일 함수 정의(func_code)를 실행 환경에 로드하고, 각 테스트케이스를 호출해 결과 수집.
    """
    results = []
    namespace = {}
    # 함수 정의 로드
    exec(func_code, namespace)
    func = namespace.get(func_name)
    for case in test_cases:
        inp = case.get("input", [])
        exp = case.get("expected")
        try:
            out = func(*inp)
            success = out == exp
            results.append({
                "input": inp,
                "expected": exp,
                "output": out,
                "success": success
            })
        except Exception as e:
            results.append({
                "input": inp,
                "expected": exp,
                "error": str(e),
                "success": False
            })
    return results

def analyze_dynamic_data(runtime_data: dict) -> list:
    """
    메인 진입점: 입력 코드에서 함수별로 테스트케이스 생성 및 실행,
    의존성 고려하여 순차적으로 검사 후 오류 리스트 반환.
    """
    code = runtime_data.get("code", "")
    functions, deps = parse_functions(code)

    # 의존성 기반 토폴로지 정렬
    tested = set()
    order = []
    def visit(fname):
        if fname in tested:
            return
        for dep in deps.get(fname, []):
            if dep not in tested:
                visit(dep)
        tested.add(fname)
        order.append(fname)
    for fname in functions:
        visit(fname)

    errors = []
    for fname in order:
        data = functions[fname]
        cases = generate_test_cases(fname, data["comment"])
        results = execute_function_tests(data["code"], fname, cases)
        for r in results:
            if not r["success"]:
                msg = r.get("error") or f"Expected {r['expected']}, got {r.get('output')}"
                errors.append({
                    "message": f"Function `{fname}` failed on input {r['input']}: {msg}",
                    "line": data["node"].lineno,
                    "column": 0,
                    "errorType": "DynamicTestFailure"
                })
    return errors

if __name__ == "__main__":
    # 전체 파일 코드 전달
    code = sys.stdin.read()
    runtime_data = {"code": code}
    try:
        errors = analyze_dynamic_data(runtime_data)
    except Exception as e:
        # 분석 자체 실패 시 단일 오류로 보고
        tb = traceback.format_exc()
        errors = [{
            "message": f"Dynamic analysis error: {e}\\n{tb}",
            "line": 0,
            "column": 0,
            "errorType": "AnalysisError"
        }]
    print(json.dumps({"errors": errors, "call_graph": None}))