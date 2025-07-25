import ast
import astor
import sys
import json
import traceback
import astroid
import os
import re
import tracemalloc

from google import genai

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

client = genai.Client(api_key=GEMINI_API_KEY)

def parse_functions(code: str):
    """
    AST를 사용해 코드에서 함수 정의를 추출하고, 각 함수의 코드, 주석, 의존성을 반환합니다.
    """
    module = astroid.parse(code)
    # Prepare raw code lines for inline comment extraction
    code_lines = code.splitlines()
    functions = {}
    for node in module.body:
        if isinstance(node, astroid.FunctionDef):
            name = node.name
            # Extract inline comment after function signature, if any
            inline_comment = ""
            def_line_idx = node.lineno - 1
            if 0 <= def_line_idx < len(code_lines):
                line_text = code_lines[def_line_idx]
                if "#" in line_text:
                    inline_comment = line_text.split("#", 1)[1].strip()
            # 함수 docstring 또는 주석 추출
            comment = node.doc_node.value if node.doc_node else ""
            # Use docstring comment if present, else inline comment
            comment = comment or inline_comment
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
    prompt = (
        "You are a helpful assistant that outputs test cases in pure JSON format only.\n"
        "Do NOT include any explanations, markdown, or code fences—only the JSON array.\n"
        "Each element in the array must be an object with two keys:\n"
        "  - \"input\": a JSON array of argument values for the function\n"
        "  - \"expected\": the expected return value for that input\n"
        "\n"
        "For example:\n"
        "[\n"
        "  {\"input\": [1, 2], \"expected\": 3},\n"
        "  {\"input\": [0, 5], \"expected\": 5},\n"
        "  {\"input\": [-1, -1], \"expected\": -2}\n"
        "]\n"
        "\n"
        "Do NOT use single quotes—only valid JSON with double quotes.\n"
        f"Now, generate exactly 10 test cases for the Python function `{func_name}`.\n"
        f"Use the function’s comment/description to guide the cases:\n"
        f"{comment}\n"
    )
    # 새 Gemini API 클라이언트 사용
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
    )
    # --- Clean Gemini response before parsing ---
    raw = response.text.strip()
    # Remove Markdown code fences like ```json
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = re.sub(r"'([^']*)'", r'"\1"', raw)
    print(f"[Gemini] Cleaned response for `{func_name}`: {raw}", file=sys.stderr)
    try:
        cases = json.loads(raw)
    except Exception as e:
        print(f"[Gemini] Failed to parse JSON for `{func_name}`: {e}", file=sys.stderr)
        cases = []
    return cases

def execute_function_tests(func_code, func_name, test_cases, memory_limit=None):
    """
    단일 함수 정의(func_code)를 실행 환경에 로드하고, 각 테스트케이스를 호출해 결과 수집.
    """
    results = []
    namespace = {}
    # Ensure tracemalloc is available (imported at top)
    # Instrument code to guard against infinite loops with per-loop counters
    try:
        tree = ast.parse(func_code)
        # Transformer to wrap While nodes and collect loop counter names
        class LoopGuardTransformer(ast.NodeTransformer):
            def __init__(self):
                super().__init__()
                self.loop_id = 0
                self.counter_names = []
                self.current_func_lineno = None
                
            def visit_FunctionDef(self, node):
                # 현재 함수 시작 줄 번호 저장
                self.current_func_lineno = node.lineno
                return self.generic_visit(node)

            def visit_While(self, node):
                self.loop_id += 1
                counter_name = f"_loop_counter_{self.loop_id}"
                self.counter_names.append(counter_name)
                # guard code to insert, include the original while line number
                # 함수 시작 기준 상대적 줄 번호 계산
                func_start = self.current_func_lineno or 0
                rel_line = node.lineno - func_start + 1
                guard_code = f"""
{counter_name} += 1
if {counter_name} > 100:
    raise TimeoutError("Infinite loop detected in loop #{self.loop_id} starting at line {rel_line} (>100 iterations)")
"""
                guard_nodes = ast.parse(guard_code).body
                # Preserve original line number for guard statements
                for guard in guard_nodes:
                    ast.copy_location(guard, node)
                node.body = guard_nodes + node.body
                # visit child nodes
                self.generic_visit(node)
                return node

        transformer = LoopGuardTransformer()
        tree = transformer.visit(tree)
        # Insert counter initializations at start of function body
        func_def = tree.body[0]
        for name in transformer.counter_names:
            init = ast.parse(f"{name} = 0").body[0]
            func_def.body.insert(0, init)
        ast.fix_missing_locations(tree)
        func_code = astor.to_source(tree)
    except Exception as e:
        # If instrumentation fails, fall back to original code
        print(f"[LoopGuard] Instrumentation failed: {e}", file=sys.stderr)
    # 함수 정의 로드
    exec(func_code, namespace)
    func = namespace.get(func_name)
    for case in test_cases:
        inp = case.get("input", [])
        exp = case.get("expected")
        # Start memory tracing for this test case
        tracemalloc.start()
        out = None
        success = False
        e = None
        try:
            out = func(*inp)
            success = out == exp
        except Exception as exc:
            e = exc
        # Get peak memory usage
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        if memory_limit is not None and peak > memory_limit:
            results.append({
                "input": inp,
                "expected": exp,
                "error": f"Memory limit exceeded: used {peak} bytes > limit {memory_limit} bytes",
                "success": False,
                "peak_memory": peak
            })
            continue
        result_entry = {
            "input": inp,
            "expected": exp,
            "peak_memory": peak,
            "success": success
        }
        if success:
            result_entry["output"] = out
        else:
            result_entry["error"] = str(e) if e is not None else f"Expected {exp}, got {out}"
        results.append(result_entry)
        continue
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
    memory_limit = runtime_data.get("memory_limit")
    for fname in order:
        data = functions[fname]
        cases = generate_test_cases(fname, data["comment"])
        results = execute_function_tests(data["code"], fname, cases, memory_limit)
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
    # 전체 파일 코드 전달 및 memory_limit 파싱
    raw = sys.stdin.read()
    try:
        runtime_data = json.loads(raw)
    except json.JSONDecodeError:
        runtime_data = {"code": raw}
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