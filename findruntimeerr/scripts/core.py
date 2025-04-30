# core.py
import astroid
import sys
import networkx as nx
from typing import List, Dict, Any, Set, Tuple, Optional, Union # Union 추가
from utils import collect_defined_variables, get_type, is_compatible # utils 함수 사용
# checkers 모듈에서 체커 클래스 목록과 BaseChecker import
from checkers import RT_CHECKERS_CLASSES, STATIC_CHECKERS_CLASSES, BaseChecker
# networkx JSON 변환 import
from networkx.readwrite import json_graph

class Linter:
    """AST를 순회하며 등록된 체커를 실행하고 결과를 수집하는 클래스."""
    def __init__(self, mode='realtime'):
        self.mode = mode
        self.checkers: List[BaseChecker] = []
        self.errors: List[Dict[str, Any]] = []
        self.call_graph = nx.DiGraph()
        self.current_scope_stack: List[Union[astroid.Module, astroid.FunctionDef, astroid.ClassDef, astroid.Lambda]] = [] # 스코프 노드 스택
        self.scope_defined_vars: Dict[astroid.NodeNG, Set[str]] = {} # 스코프별 정의된 변수
        self._load_checkers()

    def _load_checkers(self):
        """모드에 맞는 체커들을 로드하고 인스턴스화합니다."""
        checker_classes = RT_CHECKERS_CLASSES if self.mode == 'realtime' else STATIC_CHECKERS_CLASSES
        for checker_class in checker_classes:
            try:
                self.checkers.append(checker_class(self))
            except Exception as e:
                 print(f"Error initializing checker {checker_class.__name__}: {e}", file=sys.stderr)


    def add_message(self, msg_id: str, node: astroid.NodeNG, message: str):
        """체커가 오류 메시지를 추가할 때 사용하는 메서드 (중복 방지 포함)."""
        line = getattr(node, 'fromlineno', 1) or getattr(node, 'lineno', 1) or 1
        col = getattr(node, 'col_offset', 0) or 0
        to_line = getattr(node, 'tolineno', line) or line
        end_col = getattr(node, 'end_col_offset', col + 1) or (col + 1)
        line = max(1, line); col = max(0, col)
        to_line = max(1, to_line); end_col = max(0, end_col)
        error_key = (msg_id, line, col, to_line, end_col)

        if not any(err.get('_key') == error_key for err in self.errors):
            error_info = {'message': message,'line': line,'column': col, 'to_line': to_line, 'end_column': end_col,'errorType': msg_id, '_key': error_key}
            self.errors.append(error_info)

    # --- 그래프 관련 메서드 ---
    def add_node_to_graph(self, node_name: str, **kwargs):
        """호출 그래프에 노드를 추가/업데이트합니다."""
        if node_name not in self.call_graph:
            self.call_graph.add_node(node_name, **kwargs)
        else:
            for key, value in kwargs.items():
                 # 타입이 unknown일 경우 업데이트, lineno는 처음 정의된 것 유지?
                 if key == 'type' and self.call_graph.nodes[node_name].get('type') == 'unknown':
                      self.call_graph.nodes[node_name][key] = value
                 elif key not in self.call_graph.nodes[node_name]:
                      self.call_graph.nodes[node_name][key] = value


    def add_edge_to_graph(self, caller: str, callee: str, **kwargs):
        """호출 그래프에 간선을 추가/업데이트합니다."""
        self.add_node_to_graph(caller, type='module' if caller=='<module>' else 'unknown', lineno=None)
        self.add_node_to_graph(callee, type='unknown', lineno=None)

        call_site_line = kwargs.pop('lineno', None)
        edge_data = kwargs

        if self.call_graph.has_edge(caller, callee):
            existing_data = self.call_graph.edges[caller, callee]
            if 'call_sites' in existing_data and call_site_line is not None:
                 if call_site_line not in existing_data['call_sites']:
                     existing_data['call_sites'].append(call_site_line)
                     existing_data['call_sites'].sort()
            elif call_site_line is not None:
                 existing_data['call_sites'] = [call_site_line]
            for key, value in edge_data.items(): # 타입 등 다른 속성 업데이트
                 if key not in existing_data or existing_data.get(key) == 'unknown':
                      existing_data[key] = value
        else:
             if call_site_line is not None: edge_data['call_sites'] = [call_site_line]
             self.call_graph.add_edge(caller, callee, **edge_data)

    # --- 스코프 관리 ---
    def enter_scope(self, node: Union[astroid.FunctionDef, astroid.Module, astroid.ClassDef, astroid.Lambda]):
        """새로운 스코프 진입."""
        self.current_scope_stack.append(node)
        self.scope_defined_vars[node] = collect_defined_variables(node)
        # RTNameErrorChecker 등에 스코프 진입 알림 (선택적)
        for checker in self.checkers:
             if hasattr(checker, 'handle_function_entry') and isinstance(node, astroid.FunctionDef):
                  checker.handle_function_entry(node)


    def leave_scope(self, node: Union[astroid.FunctionDef, astroid.Module, astroid.ClassDef, astroid.Lambda]):
        """스코프 탈출."""
        if self.current_scope_stack and self.current_scope_stack[-1] == node:
             self.current_scope_stack.pop()
        # 스코프 변수 정보 제거 (메모리 관리)
        if node in self.scope_defined_vars:
             del self.scope_defined_vars[node]
        # RTNameErrorChecker 등에 스코프 종료 알림 (선택적)
        for checker in self.checkers:
             if hasattr(checker, 'handle_function_exit') and isinstance(node, astroid.FunctionDef):
                  checker.handle_function_exit(node)


    def get_current_scope_variables(self) -> Set[str]:
        """현재 스코프에서 정의된 변수 집합 반환."""
        # 현재 스코프 노드에 대한 변수 반환
        if self.current_scope_stack:
             return self.scope_defined_vars.get(self.current_scope_stack[-1], set())
        return set()

    # --- AST 순회 및 분석 실행 ---
    def visit_node(self, node: astroid.NodeNG):
         """AST 노드를 방문하여 그래프 생성 및 체커 실행."""
         # 1. 스코프 진입 처리
         is_scope_node = isinstance(node, (astroid.FunctionDef, astroid.Module, astroid.ClassDef, astroid.Lambda))
         if is_scope_node:
              self.enter_scope(node)

         # 2. 그래프 생성 로직
         try:
             if isinstance(node, astroid.FunctionDef):
                 func_name = node.name; caller = self.current_scope_stack[-2] if len(self.current_scope_stack) > 1 else '<module>'
                 self.add_node_to_graph(func_name, type='function', lineno=node.lineno)
                 if caller == '<module>': self.add_edge_to_graph(caller, func_name, type='defines', lineno=node.lineno)
             elif isinstance(node, astroid.Call):
                 caller = self.current_scope_stack[-1].name if self.current_scope_stack and hasattr(self.current_scope_stack[-1],'name') else '<module>' # 현재 스코프 이름
                 called_func_name = None; call_type = 'calls'
                 if isinstance(node.func, astroid.Name): called_func_name = node.func.name; call_type = 'calls'
                 elif isinstance(node.func, astroid.Attribute):
                     call_type = 'calls_method'
                     try: called_func_name = f"{node.func.expr.as_string()}.{node.func.attrname}"
                     except Exception: called_func_name = f"?.{node.func.attrname}"
                 if called_func_name and caller: self.add_edge_to_graph(caller, called_func_name, type=call_type, lineno=node.lineno)
             elif isinstance(node, astroid.ClassDef):
                  class_name = node.name; caller = self.current_scope_stack[-2] if len(self.current_scope_stack) > 1 else '<module>'
                  self.add_node_to_graph(class_name, type='class', lineno=node.lineno)
                  if caller == '<module>': self.add_edge_to_graph(caller, class_name, type='defines_class', lineno=node.lineno)
         except Exception as e: print(f"Error during graph building for node {node!r}: {e}", file=sys.stderr)

         # 3. 등록된 체커 실행
         node_type = type(node)
         for checker in self.checkers:
             # 체커가 이 노드 타입에 관심 있는지 확인
             if checker.node_types and node_type not in checker.node_types:
                  continue
             # check 메서드 호출
             if hasattr(checker, 'check'):
                 try: checker.check(node)
                 except Exception as e: print(f"Error in checker {checker.__class__.__name__} for node {node!r}: {e}", file=sys.stderr)

         # 4. 자식 노드 재귀 방문
         for child in node.get_children():
             self.visit_node(child)

         # 5. 스코프 종료 처리
         if is_scope_node:
              self.leave_scope(node)

    def analyze(self, tree: astroid.Module):
        """AST를 순회하며 분석을 수행합니다."""
        self.errors = []
        self.call_graph = nx.DiGraph()
        self.current_scope_stack = [] # 스택 초기화
        self.scope_defined_vars = {}

        print("Starting analysis and graph building...", file=sys.stderr)
        self.visit_node(tree) # AST 순회 시작
        print("Analysis and graph building finished.", file=sys.stderr)

        # --- 함수 단위 체커 실행 (Recursion 등) ---
        if self.mode == 'static':
            # 모든 함수 정의 노드를 찾아서 재귀 검사 수행
            for func_node in tree.nodes_of_class(astroid.FunctionDef):
                 for checker in self.checkers:
                     if hasattr(checker, 'check_function_recursion'):
                          try: checker.check_function_recursion(func_node)
                          except Exception as e: print(f"Error in recursion checker for {func_node.name}: {e}", file=sys.stderr)

        # 그래프 후처리
        if '<module>' in self.call_graph:
             self.call_graph.remove_node('<module>')

# --- analyze_code 함수 (Linter 사용) ---
def analyze_code(code: str, mode: str = 'realtime') -> Dict[str, Any]:
    print(f"analyze_code (Linter based) called with mode: {mode}", file=sys.stderr)
    errors = []
    call_graph_data = None

    try:
        tree = astroid.parse(code)
        print(f"AST parsed successfully", file=sys.stderr)

        linter = Linter(mode=mode)
        linter.analyze(tree)
        errors = linter.errors

        if mode == 'static':
             try:
                 call_graph_data = json_graph.node_link_data(linter.call_graph)
             except Exception as e:
                 print(f"Error converting graph to JSON: {e}", file=sys.stderr)

    except astroid.AstroidSyntaxError as e:
        print(f"SyntaxError: {e}", file=sys.stderr)
        errors.append({'message': f"SyntaxError: {e.msg}",'line': e.line,'column': e.col,'errorType': 'SyntaxError'})
    except Exception as e:
        import traceback
        print(f"Exception during analysis: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        errors.append({'message': f"An error occurred during analysis: {e}",'line': 1,'column': 0,'errorType': 'AnalysisError'})

    result = {'errors': errors, 'call_graph': call_graph_data}

    if not isinstance(result.get('errors'), list):
        print("Critical Error: 'errors' is not a list before returning!", file=sys.stderr)
        result['errors'] = []

    print(f"analyze_code returning result with {len(result['errors'])} errors.", file=sys.stderr)
    return result