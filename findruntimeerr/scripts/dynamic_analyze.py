# core.py
import astroid
import networkx as nx # networkx 추가
from typing import List, Dict, Any, Set, Tuple, Optional
from checkers import (
    check_name_errors,
    check_zero_division_error,
    check_type_error,
    check_attribute_error,
    check_index_error,
    check_key_error,
    check_infinite_loop,
    check_recursion_error,
    check_file_not_found_error,
)
from utils import collect_defined_variables, get_type, is_compatible # 추가

def _build_call_graph_during_analysis(tree: astroid.Module) -> nx.DiGraph:
    """AST 분석 중 함수 호출 그래프를 생성합니다."""
    graph = nx.DiGraph()
    current_func_stack = ["<module>"] # 함수 호출 스택

    def process_node_for_graph(node):
        """그래프 생성을 위해 AST 노드를 처리합니다."""
        try:
            if isinstance(node, astroid.FunctionDef):
                func_name = node.name
                graph.add_node(func_name, type='function', lineno=node.lineno)
                caller_func = current_func_stack[-1]
                if caller_func == '<module>':
                     graph.add_edge(caller_func, func_name, type='defines', lineno=node.lineno)

                current_func_stack.append(func_name)
                # 재귀적으로 자식 노드 처리
                for child in node.get_children():
                    process_node_for_graph(child)
                current_func_stack.pop()

            elif isinstance(node, astroid.Call):
                caller_func = current_func_stack[-1]
                called_func_name = None
                call_type = 'calls'

                if isinstance(node.func, astroid.Name):
                    called_func_name = node.func.name
                    if called_func_name not in graph:
                        graph.add_node(called_func_name, type='unknown', lineno=None)
                    call_type = 'calls'

                elif isinstance(node.func, astroid.Attribute):
                    call_type = 'calls_method'
                    try:
                        expr_str = node.func.expr.as_string()
                        called_func_name = f"{expr_str}.{node.func.attrname}"
                        graph.add_node(called_func_name, type='method', lineno=None)
                    except Exception:
                        called_func_name = f"?.{node.func.attrname}"
                        graph.add_node(called_func_name, type='method', lineno=None)

                if called_func_name and caller_func:
                    if caller_func not in graph:
                       graph.add_node(caller_func, type='module' if caller_func=='<module>' else 'unknown', lineno=None)

                    if graph.has_edge(caller_func, called_func_name):
                         if 'call_sites' in graph.edges[caller_func, called_func_name]:
                             graph.edges[caller_func, called_func_name]['call_sites'].append(node.lineno)
                         else:
                              graph.edges[caller_func, called_func_name]['call_sites'] = [node.lineno]
                    else:
                         graph.add_edge(caller_func, called_func_name, type=call_type, call_sites=[node.lineno])

                # 자식 노드 (인자 등) 처리
                for child in node.get_children():
                    process_node_for_graph(child)

            else:
                # 다른 노드 타입 처리
                for child in node.get_children():
                    process_node_for_graph(child)
        except Exception as e:
            # 그래프 생성 중 오류 발생 시 로그 기록 (선택적)
            print(f"  Error building graph for node {node!r}: {e}", file=sys.stderr)

    print("Starting call graph building within analysis...", file=sys.stderr)
    process_node_for_graph(tree) # AST 전체 순회하며 그래프 생성
    print("Call graph building finished.", file=sys.stderr)

     # '<module>' 노드 제거 및 관련 간선 처리
    if '<module>' in graph:
        module_defines = [v for u, v, data in graph.edges(data=True) if u == '<module>' and data.get('type') == 'defines']
        graph.remove_node('<module>')
        for node_name in module_defines:
             if node_name not in graph:
                 graph.add_node(node_name, type='function', lineno=None)

    return graph


def analyze_code(code: str, mode: str = 'realtime') -> Dict[str, Any]: # 반환 타입 변경
    """
    Python 코드를 분석하여 잠재적인 런타임 에러와 함수 호출 그래프를 찾습니다.

    Args:
        code: 분석할 Python 코드 문자열.
        mode: 'realtime', 'static'.

    Returns:
        분석 결과를 담은 딕셔너리: {'errors': 오류 리스트, 'call_graph': 호출 그래프 데이터 (JSON)}
    """
    print(f"analyze_code called with mode: {mode}", file=sys.stderr)
    try:
        tree = astroid.parse(code)
        print(f"AST parsed successfully", file=sys.stderr)
    # ... (예외 처리 동일) ...
    except astroid.AstroidSyntaxError as e:
         # ...
         return {'errors': [{'message': f"SyntaxError: {e.msg}", 'line': e.line, 'column': e.col, 'errorType': 'SyntaxError'}], 'call_graph': None}
    except Exception as e:
         # ...
         return {'errors': [{'message': f"An error occurred during analysis: {e}", 'line': 1, 'column': 0, 'errorType': 'AnalysisError'}], 'call_graph': None}


    errors = []
    call_graph = None

    # 1. 함수 호출 그래프 생성 (static 모드에서만)
    if mode == 'static':
        call_graph = _build_call_graph_during_analysis(tree)

    # 2. 오류 분석 수행
    # 함수별 분석
    for func_node in tree.body:
        if isinstance(func_node, astroid.FunctionDef):
            _analyze_function(func_node, errors, mode)

    # 모듈 수준 분석
    if mode == 'static': # static 모드에서만 모듈 분석 수행
        _analyze_module(tree, errors)


    # 3. 결과 조합
    result = {'errors': errors}
    if call_graph is not None:
         from networkx.readwrite import json_graph # 필요할 때 import
         try:
             result['call_graph'] = json_graph.node_link_data(call_graph)
         except Exception as e:
             print(f"Error converting graph to JSON: {e}", file=sys.stderr)
             result['call_graph'] = None # 변환 실패 시 null
    else:
         result['call_graph'] = None # 그래프 데이터가 없는 경우 null

    print(f"analyze_code returning result", file=sys.stderr)
    return result


def _analyze_function(func_node: astroid.FunctionDef, errors: list, mode: str):
    """함수 단위 분석."""
    defined_vars: Set[str] = collect_defined_variables(func_node)

    # 재귀 호출 검사
    check_recursion_error(func_node, errors)

    # 함수 본문 분석
    for node in func_node.body:
        check_name_errors(node, defined_vars, errors)  # 모든 모드에서 NameError 검사

        if mode == 'realtime':
            if isinstance(node, astroid.BinOp):
                check_zero_division_error(node, errors)  # ZeroDivisionError

        elif mode == 'static':
            if isinstance(node, astroid.BinOp):
                check_zero_division_error(node, errors)  # ZeroDivisionError
                check_type_error(node, errors)  # TypeError
            elif isinstance(node, astroid.Attribute):
                check_attribute_error(node, errors)  # AttributeError
            elif isinstance(node, astroid.Subscript):
                check_index_error(node, errors)  # IndexError
                check_key_error(node, errors)  # KeyError


def _analyze_module(module_node: astroid.Module, errors: list):
    """모듈 단위 분석."""
    for node in module_node.body:
        if isinstance(node, astroid.Call) and isinstance(node.func, astroid.Name) and node.func.name == "open":
            check_file_not_found_error(node, errors)
        elif isinstance(node, astroid.While):
            check_infinite_loop(node, errors)  # 최상위 while 루프