# core.py
import astroid
import sys
from typing import List, Dict, Any, Set
# utils는 공통으로 사용
from utils import collect_defined_variables, get_type, is_compatible

# 모드에 따라 다른 체커 모듈을 동적으로 import (또는 미리 import 해두고 선택)
# 예시: 동적 import (다른 방식도 가능)
def _import_checkers(mode: str):
    if mode == 'realtime':
        try:
            # 현재 스크립트 위치 기준으로 import 시도
            from . import RT_checkers as checkers
            print("Imported RT_checkers", file=sys.stderr)
            return checkers
        except ImportError:
            # 단독 실행 또는 다른 환경 대비 절대 import
            import RT_checkers as checkers
            print("Imported RT_checkers (absolute)", file=sys.stderr)
            return checkers
    elif mode == 'static':
        try:
            from . import static_checkers as checkers
            print("Imported static_checkers", file=sys.stderr)
            return checkers
        except ImportError:
            import static_checkers as checkers
            print("Imported static_checkers (absolute)", file=sys.stderr)
            return checkers
    else:
        # 다른 모드 (예: dynamic) 또는 오류 처리
        print(f"Warning: Unsupported analysis mode '{mode}' for importing checkers.", file=sys.stderr)
        return None # 또는 기본 체커 사용

def analyze_code(code: str, mode: str = 'realtime') -> Dict[str, Any]:
    print(f"analyze_code called with mode: {mode}", file=sys.stderr)
    errors = []
    call_graph = None
    checkers = _import_checkers(mode) # 모드에 맞는 체커 모듈 로드

    if checkers is None and mode != 'dynamic': # dynamic 제외하고 체커 로드 실패 시
         return {'errors': [{'message': f"Failed to load checkers for mode '{mode}'", 'line': 1, 'column': 0, 'errorType': 'CheckerLoadError'}], 'call_graph': None}

    try:
        tree = astroid.parse(code)
        print(f"AST parsed successfully", file=sys.stderr)

        # 그래프 생성 (static 모드에서만)
        if mode == 'static':
            from networkx import DiGraph # 필요할 때 import
            from utils import build_call_graph_during_analysis # utils로 이동 가정
            call_graph_obj = build_call_graph_during_analysis(tree)

        # 오류 분석 수행
        for node in tree.body:
            if isinstance(node, astroid.FunctionDef):
                _analyze_function(node, errors, mode, checkers)
            # 모듈 수준 노드에 대한 검사 (필요 시 checkers 모듈 함수 호출)
            if mode == 'static': # static 모드에서 모듈 분석
                 _analyze_module(node, errors, checkers)


    # ... (SyntaxError, Exception 처리 - 이전과 유사하게 errors 리스트에 추가) ...
    except astroid.AstroidSyntaxError as e:
        print(f"SyntaxError: {e}", file=sys.stderr)
        errors.append({'message': f"SyntaxError: {e.msg}",'line': e.line,'column': e.col,'errorType': 'SyntaxError'})
    except Exception as e:
        import traceback
        print(f"Exception during analysis: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        errors.append({'message': f"An error occurred during analysis: {e}",'line': 1,'column': 0,'errorType': 'AnalysisError'})


    # 결과 조합
    result = {'errors': errors}
    if call_graph is not None:
         from networkx.readwrite import json_graph
         try:
             result['call_graph'] = json_graph.node_link_data(call_graph_obj)
         except Exception as e:
             print(f"Error converting graph to JSON: {e}", file=sys.stderr)
             result['call_graph'] = None
    else:
         result['call_graph'] = None

    if not isinstance(result.get('errors'), list):
        result['errors'] = []

    print(f"analyze_code returning result with {len(result['errors'])} errors.", file=sys.stderr)
    return result


def _analyze_function(func_node: astroid.FunctionDef, errors: list, mode: str, checkers):
    """함수 단위 분석 (선택된 체커 모듈 사용)."""
    if checkers is None: return # 체커 없으면 분석 불가

    defined_vars: Set[str] = collect_defined_variables(func_node)

    # 재귀 호출 검사 (필요 시 checkers 모듈로 이동 가능)
    if hasattr(checkers, 'check_recursion_error'):
        checkers.check_recursion_error(func_node, errors)

    # 함수 본문 분석
    for node in func_node.body:
        if hasattr(checkers, 'check_name_errors'):
            checkers.check_name_errors(node, defined_vars, errors)

        if isinstance(node, astroid.BinOp):
            if hasattr(checkers, 'check_zero_division_error'):
                checkers.check_zero_division_error(node, errors)
            if mode == 'static' and hasattr(checkers, 'check_type_error'):
                checkers.check_type_error(node, errors)
        elif isinstance(node, astroid.Attribute):
            if mode == 'static' and hasattr(checkers, 'check_attribute_error'):
                checkers.check_attribute_error(node, errors)
        elif isinstance(node, astroid.Subscript):
            if mode == 'static' and hasattr(checkers, 'check_index_error'):
                checkers.check_index_error(node, errors)
            if mode == 'static' and hasattr(checkers, 'check_key_error'):
                checkers.check_key_error(node, errors)

        # defined_vars 업데이트 (Assign 노드 처리)
        if isinstance(node, astroid.Assign):
             for target in node.targets:
                 if isinstance(target, astroid.Name):
                     defined_vars.add(target.name)
        # TODO: 다른 변수 정의 케이스 (AugAssign, For 등) 처리

def _analyze_module(module_node: astroid.Module, errors: list, checkers):
    """모듈 단위 분석 (선택된 체커 모듈 사용)."""
    if checkers is None: return

    for node in module_node.body:
        if isinstance(node, astroid.Call) and isinstance(node.func, astroid.Name) and node.func.name == "open":
            if hasattr(checkers, 'check_file_not_found_error'):
                checkers.check_file_not_found_error(node, errors)
        elif isinstance(node, astroid.While):
             if hasattr(checkers, 'check_infinite_loop'):
                checkers.check_infinite_loop(node, errors)