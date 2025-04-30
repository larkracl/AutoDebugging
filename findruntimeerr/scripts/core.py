# core.py
# core.py
import astroid
import sys
import networkx as nx
from typing import List, Dict, Any, Set, Tuple, Optional, Union
import re
# utils.py 함수 사용 (get_type, is_compatible, collect_defined_variables)
from utils import collect_defined_variables, get_type, is_compatible
# checkers 모듈에서 체커 클래스 목록과 BaseChecker import
from checkers import RT_CHECKERS_CLASSES, STATIC_CHECKERS_CLASSES, BaseChecker
# networkx JSON 변환 import
from networkx.readwrite import json_graph
import traceback # 상세 예외 로깅

class Linter:
    """AST를 순회하며 등록된 체커를 실행하고 결과를 수집하는 클래스."""
    def __init__(self, mode='realtime'):
        print(f"[Linter.__init__] Initializing Linter for mode: {mode}", file=sys.stderr)
        self.mode = mode
        self.checkers: List[BaseChecker] = []
        self.errors: List[Dict[str, Any]] = []
        self.call_graph = nx.DiGraph()
        # 스코프 노드 스택 (astroid 노드 객체 저장)
        self.current_scope_stack: List[Union[astroid.Module, astroid.FunctionDef, astroid.ClassDef, astroid.Lambda]] = []
        # 스코프별 정의된 변수 (노드 객체를 키로 사용)
        self.scope_defined_vars: Dict[astroid.NodeNG, Set[str]] = {}
        self._load_checkers()

    def _load_checkers(self):
        """모드에 맞는 체커들을 로드하고 인스턴스화합니다."""
        checker_classes = RT_CHECKERS_CLASSES if self.mode == 'realtime' else STATIC_CHECKERS_CLASSES
        print(f"[Linter._load_checkers] Loading {len(checker_classes)} checkers for mode: {self.mode}", file=sys.stderr)
        for checker_class in checker_classes:
            try:
                checker_instance = checker_class(self)
                self.checkers.append(checker_instance)
                print(f"[Linter._load_checkers] Loaded checker: {checker_class.__name__}", file=sys.stderr)
            except Exception as e:
                 error_msg = f"Error initializing checker {checker_class.__name__}: {e}"
                 print(error_msg, file=sys.stderr)
                 # 내부 오류로 추가 (선택적)
                 self.errors.append({'message': error_msg, 'line': 1, 'column': 0, 'errorType': 'CheckerInitError', '_key': ('CheckerInitError', 1, 0, 1, 1)})


    def add_message(self, msg_id: str, node: astroid.NodeNG, message: str):
        """체커가 오류 메시지를 추가할 때 사용하는 메서드 (중복 방지 포함)."""
        # --- SyntaxError 예외 객체 특수 처리 ---
        if isinstance(node, astroid.AstroidSyntaxError):
            # Extract line number from error message
            msg = str(node)
            match = re.search(r'line (\d+)', msg)
            line_num = int(match.group(1)) if match else 1
            col_num = getattr(node, 'col_offset', 0) or 0
            error_key = (self.MSG_ID if hasattr(self, 'MSG_ID') else msg_id, line_num, col_num, line_num, col_num + 1)
            if not any(err.get('_key') == error_key for err in self.errors):
                error_info = {
                    'message': f"SyntaxError: {msg}",
                    'line': line_num,
                    'column': col_num,
                    'to_line': line_num,
                    'end_column': col_num + 1,
                    'errorType': 'SyntaxError',
                    '_key': error_key
                }
                self.errors.append(error_info)
            return
        try: # 노드 속성 접근 시 오류 방지
            line = getattr(node, 'fromlineno', None) or getattr(node, 'lineno', 1) or 1
            col = getattr(node, 'col_offset', 0) or 0
            if col is None: col = 0

            to_line = getattr(node, 'tolineno', line) or line
            end_col = getattr(node, 'end_col_offset', None)

            # SyntaxError 예외 객체 처리
            if msg_id == 'SyntaxError' and isinstance(node, astroid.AstroidSyntaxError):
                line = node.lineno or 1
                col = node.col or 0 # astroid.AstroidSyntaxError는 col 속성 사용
                to_line = line
                end_col = col + 1 # SyntaxError는 보통 한 지점
            elif end_col is None or end_col <= col: # 일반 노드의 end_col_offset이 없을 경우
                 end_col = col + 1 # 최소 1 문자 길이

            line = max(1, line); col = max(0, col)
            to_line = max(line, to_line); end_col = max(col + 1, end_col)

            error_key = (msg_id, line, col, to_line, end_col)

            if not any(err.get('_key') == error_key for err in self.errors):
                error_info = {
                    'message': message,'line': line,'column': col,
                    'to_line': to_line, 'end_column': end_col,
                    'errorType': msg_id, '_key': error_key
                }
                self.errors.append(error_info)
                print(f"[Linter.add_message] Added: {msg_id} at L{line}:C{col} - {message}", file=sys.stderr)
        except Exception as e:
             print(f"Error adding message for node {node!r}: {e}", file=sys.stderr)
             traceback.print_exc(file=sys.stderr)


    # --- 그래프 관련 메서드 ---
    def add_node_to_graph(self, node_name: str, **kwargs):
        """호출 그래프에 노드를 추가/업데이트합니다."""
        if not isinstance(node_name, str) or not node_name: return
        if node_name not in self.call_graph:
            self.call_graph.add_node(node_name, **kwargs)
        else:
            for key, value in kwargs.items():
                 if self.call_graph.nodes[node_name].get(key) in (None, 'unknown'):
                     self.call_graph.nodes[node_name][key] = value
                 elif key == 'lineno' and 'lineno' not in self.call_graph.nodes[node_name]:
                      self.call_graph.nodes[node_name][key] = value

    def add_edge_to_graph(self, caller: str, callee: str, **kwargs):
        """호출 그래프에 간선을 추가/업데이트합니다."""
        if not isinstance(caller, str) or not caller or not isinstance(callee, str) or not callee: return
        self.add_node_to_graph(caller, type='module' if caller=='<module>' else 'unknown', lineno=None)
        self.add_node_to_graph(callee, type='unknown', lineno=None)
        call_site_line = kwargs.pop('lineno', None)
        edge_data = kwargs
        if self.call_graph.has_edge(caller, callee):
            existing_data = self.call_graph.edges[caller, callee]
            if 'call_sites' in existing_data and call_site_line is not None:
                 if call_site_line not in existing_data['call_sites']: existing_data['call_sites'].append(call_site_line); existing_data['call_sites'].sort()
            elif call_site_line is not None: existing_data['call_sites'] = [call_site_line]
            for key, value in edge_data.items():
                 if key not in existing_data or existing_data.get(key) == 'unknown': existing_data[key] = value
        else:
             if call_site_line is not None: edge_data['call_sites'] = [call_site_line]
             self.call_graph.add_edge(caller, callee, **edge_data)

    # --- 스코프 관리 ---
    def enter_scope(self, node: Union[astroid.Module, astroid.FunctionDef, astroid.ClassDef, astroid.Lambda]):
        """새로운 스코프 진입."""
        scope_name = node.name if hasattr(node, 'name') else type(node).__name__
        print(f"[Linter.enter_scope] Entering scope: {scope_name}", file=sys.stderr)
        self.current_scope_stack.append(node)
        self.scope_defined_vars[node] = collect_defined_variables(node)
        print(f"  [enter_scope] Defined vars in {scope_name}: {self.scope_defined_vars.get(node, 'N/A')}", file=sys.stderr)
        for checker in self.checkers:
             if hasattr(checker, 'handle_function_entry') and isinstance(node, astroid.FunctionDef):
                  try: checker.handle_function_entry(node)
                  except Exception as e: print(f"Error in checker {checker.__class__.__name__}.handle_function_entry: {e}", file=sys.stderr)

    def leave_scope(self, node: Union[astroid.Module, astroid.FunctionDef, astroid.ClassDef, astroid.Lambda]):
        """스코프 탈출."""
        scope_name = node.name if hasattr(node, 'name') else type(node).__name__
        print(f"[Linter.leave_scope] Leaving scope: {scope_name}", file=sys.stderr)
        if self.current_scope_stack and self.current_scope_stack[-1] == node:
             self.current_scope_stack.pop()
        else: print(f"Warning: Scope stack mismatch when leaving node {node!r}", file=sys.stderr)
        if node in self.scope_defined_vars: del self.scope_defined_vars[node]
        for checker in self.checkers:
             if hasattr(checker, 'handle_function_exit') and isinstance(node, astroid.FunctionDef):
                  try: checker.handle_function_exit(node)
                  except Exception as e: print(f"Error in checker {checker.__class__.__name__}.handle_function_exit: {e}", file=sys.stderr)

    def get_current_scope_variables(self) -> Set[str]:
        """현재 스코프에서 정의된 변수 집합 반환."""
        if self.current_scope_stack:
             current_scope_node = self.current_scope_stack[-1]
             return self.scope_defined_vars.get(current_scope_node, set())
        return set()

    # --- AST 순회 및 분석 실행 ---
    def visit_node(self, node: astroid.NodeNG):
         """AST 노드를 방문하여 그래프 생성 및 체커 실행."""
         print(f"[Linter.visit_node] Visiting node: {node.__class__.__name__} at L{getattr(node, 'lineno', '?')}", file=sys.stderr)
         # 1. 스코프 진입 처리
         is_scope_node = isinstance(node, (astroid.FunctionDef, astroid.Module, astroid.ClassDef, astroid.Lambda))
         if is_scope_node:
              self.enter_scope(node)

         # 2. 그래프 생성 로직 (static 모드에서만)
         if self.mode == 'static':
             try:
                 if isinstance(node, astroid.FunctionDef):
                     func_name = node.name; caller = self.current_scope_stack[-2].name if len(self.current_scope_stack) > 1 and hasattr(self.current_scope_stack[-2], 'name') else '<module>'
                     self.add_node_to_graph(func_name, type='function', lineno=node.lineno)
                     if caller == '<module>': self.add_edge_to_graph(caller, func_name, type='defines', lineno=node.lineno)
                 elif isinstance(node, astroid.Call):
                     caller_node = self.current_scope_stack[-1] if self.current_scope_stack else None
                     caller = caller_node.name if caller_node and hasattr(caller_node, 'name') else '<module>'
                     called_func_name = None; call_type = 'calls'
                     if isinstance(node.func, astroid.Name): called_func_name = node.func.name; call_type = 'calls'
                     elif isinstance(node.func, astroid.Attribute):
                         call_type = 'calls_method'
                         try: called_func_name = f"{node.func.expr.as_string()}.{node.func.attrname}"
                         except Exception: called_func_name = f"?.{node.func.attrname}"
                     if called_func_name and caller: self.add_edge_to_graph(caller, called_func_name, type=call_type, lineno=node.lineno)
                 elif isinstance(node, astroid.ClassDef):
                      class_name = node.name; caller = self.current_scope_stack[-2].name if len(self.current_scope_stack) > 1 and hasattr(self.current_scope_stack[-2], 'name') else '<module>'
                      self.add_node_to_graph(class_name, type='class', lineno=node.lineno)
                      if caller == '<module>': self.add_edge_to_graph(caller, class_name, type='defines_class', lineno=node.lineno)
             except Exception as e: print(f"Error during graph building for node {node!r}: {e}", file=sys.stderr)

         # 3. 등록된 체커 실행
         node_type = type(node)
         for checker in self.checkers:
             if not checker.node_types or node_type in checker.node_types:
                 if hasattr(checker, 'check'):
                     try: checker.check(node)
                     except Exception as e:
                          print(f"Error in checker {checker.__class__.__name__} for node {node!r}: {e}", file=sys.stderr)
                          traceback.print_exc(file=sys.stderr)

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

        print("[Linter.analyze] Starting analysis and graph building...", file=sys.stderr)
        # 모듈 노드를 첫 스코프로 시작
        self.visit_node(tree)
        print("[Linter.analyze] Analysis and graph building finished.", file=sys.stderr)

        # --- 함수 단위 체커 실행 (Recursion 등) ---
        if self.mode == 'static':
            recursion_checker_found = False
            for checker in self.checkers:
                 if hasattr(checker, 'check_function_recursion'):
                      recursion_checker_found = True
                      print(f"[Linter.analyze] Running checker {checker.__class__.__name__} for function recursion.", file=sys.stderr)
                      try:
                          for func_node in tree.nodes_of_class(astroid.FunctionDef):
                               checker.check_function_recursion(func_node)
                      except Exception as e: print(f"Error in recursion checker {checker.__class__.__name__}: {e}", file=sys.stderr)

        # 그래프 후처리
        if '<module>' in self.call_graph:
             try:
                 if self.call_graph.has_node('<module>'): self.call_graph.remove_node('<module>')
             except Exception as e: print(f"Error removing <module> node from graph: {e}", file=sys.stderr)


# --- analyze_code 함수 (Linter 사용 및 SyntaxError 처리 수정) ---
def analyze_code(code: str, mode: str = 'realtime') -> Dict[str, Any]:
    print(f"analyze_code (Linter based) called with mode: {mode}", file=sys.stderr)
    errors = []
    call_graph_data = None
    linter = Linter(mode=mode) # Linter 생성

    try:
        tree = astroid.parse(code)
        print(f"AST parsed successfully", file=sys.stderr)
        linter.analyze(tree)     # 분석 실행
        errors = linter.errors

        if mode == 'static':
             try:
                 # networkx가 import 되어 있다고 가정
                 call_graph_data = json_graph.node_link_data(linter.call_graph)
                 print("[analyze_code] Call graph converted to JSON.", file=sys.stderr)
             except ImportError:
                 print("Error: networkx library not found for JSON conversion.", file=sys.stderr)
             except Exception as e:
                 print(f"Error converting graph to JSON: {e}", file=sys.stderr)

    except astroid.AstroidSyntaxError as e:
        print(f"!!! Caught SyntaxError in analyze_code: {e}", file=sys.stderr)
        # --- 수정: str(e) 또는 e.args 사용 ---
        syntax_error_message = str(e) # 예외 객체 자체를 문자열로 변환
        # 또는 더 구체적으로: syntax_error_message = e.args[0] if e.args else "Unknown syntax error"

        # line, col 정보는 예외 객체에서 가져오기
        # linter.add_message 호출 시 node 인자로 예외 객체 e 전달
        linter.add_message('SyntaxError', e, f"SyntaxError: {syntax_error_message}")
        errors = linter.errors # 업데이트된 오류 목록 가져오기
        call_graph_data = None
        # ------------------------------------
    except Exception as e:
        print(f"!!! Exception during analysis in analyze_code: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        # 임시 노드 대신 기본 위치 정보 사용
        linter.add_message('AnalysisError', e, f"An error occurred during analysis: {e}") # 노드로 e 전달 시도
        errors = linter.errors
        call_graph_data = None

    # 오류 객체에서 내부 키(_key) 제거
    cleaned_errors = [{k: v for k, v in err.items() if k != '_key'} for err in errors]

    result = {'errors': cleaned_errors, 'call_graph': call_graph_data}

    if not isinstance(result.get('errors'), list):
        print("Critical Error: 'errors' is not a list before returning!", file=sys.stderr)
        result['errors'] = []

    print(f"analyze_code returning result with {len(result['errors'])} errors.", file=sys.stderr)
    return result