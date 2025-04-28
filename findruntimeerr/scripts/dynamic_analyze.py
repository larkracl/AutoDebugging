import sys
import json
import traceback
import astroid
import os
import requests

# Configuration for Gemini free API
GEMINI_API_URL = "https://api.gemini.com/v1/generate"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

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
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set in environment")
    prompt = (
        f"Generate exactly 10 test cases for the Python function `{func_name}`.\n"
        f"Description/comment: {comment}\n"
        "Return a JSON array of objects with fields: `input` (list of args) and `expected`."
    )
    headers = {
        "Authorization": f"Bearer {GEMINI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "prompt": prompt,
        "max_tokens": 512,
        "n": 1
    }
    resp = requests.post(GEMINI_API_URL, headers=headers, json=payload, timeout=10)
    resp.raise_for_status()
    body = resp.json()
    text = body.get("data", [{}])[0].get("generated_text", "")
    try:
        cases = json.loads(text)
    except Exception:
        # 파싱 실패 시 빈 리스트 반환
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