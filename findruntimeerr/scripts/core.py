# core.py
<<<<<<< Updated upstream
import astroid
import sys
import networkx as nx
from typing import List, Dict, Any, Set, Tuple, Optional, Union
# utils.py 함수 사용 (get_type, is_compatible, collect_defined_variables)
=======
import parso # astroid 대신 parso 사용
import sys
import networkx as nx
from typing import List, Dict, Any, Set, Tuple, Optional, Union
# parso 기반으로 수정된 utils 함수 사용
>>>>>>> Stashed changes
from utils import collect_defined_variables, get_type, is_compatible
# parso 기반으로 수정된 checkers 모듈 사용
from checkers import RT_CHECKERS_CLASSES, STATIC_CHECKERS_CLASSES, BaseChecker
# networkx JSON 변환 import
from networkx.readwrite import json_graph
import traceback

class Linter:
    """AST를 순회하며 등록된 체커를 실행하고 결과를 수집하는 클래스 (parso 기반)."""
    def __init__(self, mode='realtime'):
        print(f"[Linter.__init__] Initializing Linter for mode: {mode}", file=sys.stderr)
        self.mode = mode
        self.checkers: List[BaseChecker] = []
        self.errors: List[Dict[str, Any]] = []
        self.call_graph = nx.DiGraph()
        self.current_node: Optional[parso.tree.BaseNode] = None # 현재 방문 노드 (스코프 변수 조회용)
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
                 # 초기화 오류 시에도 일관된 오류 객체 사용 고려
                 error_node_mock = type('obj', (object,), {'start_pos': (1,0), 'end_pos': (1,1)})() # 임시 위치
                 self.add_message('CheckerInitError', error_node_mock, error_msg)


<<<<<<< Updated upstream
    def add_message(self, msg_id: str, node: astroid.NodeNG, message: str):
        """체커가 오류 메시지를 추가할 때 사용하는 메서드 (중복 방지 포함)."""
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

=======
    def add_message(self, msg_id: str, node: parso.tree.BaseNode, message: str):
        """체커가 오류 메시지를 추가할 때 사용하는 메서드 (parso 노드)."""
        try:
            # parso 노드의 위치 정보 사용 (start_pos, end_pos)
            line, col = node.start_pos
            to_line, end_col = node.end_pos
            # end_pos는 exclusive일 수 있으므로, 1문자 길이를 위해 조정 필요 시 고려
            # 하지만 일반적으로 에디터에서 밑줄은 start_pos 기준으로 그리는 경우가 많음
>>>>>>> Stashed changes
            line = max(1, line); col = max(0, col)
            to_line = max(line, to_line); end_col = max(col + 1, end_col) # 최소 1문자 폭 보장

            # SyntaxError는 파싱 단계에서 별도 처리됨 (이 함수 호출 안 됨)
            if msg_id == 'SyntaxError': msg_id = 'InternalError' # 혹시 모르니 변경

            error_key = (msg_id, line, col, to_line, end_col) # 중복 방지 키

            if not any(err.get('_key') == error_key for err in self.errors):
                error_info = {
                    'message': message,'line': line,'column': col,
                    'to_line': to_line, 'end_column': end_col,
                    'errorType': msg_id, '_key': error_key
                }
                self.errors.append(error_info)
                # print(f"[Linter.add_message] Added: {msg_id} at L{line}:C{col}-L{to_line}:C{end_col} - {message}", file=sys.stderr)
        except Exception as e:
             print(f"Error adding message for parso node {node!r}: {e}", file=sys.stderr)
             # 오류 발생 시에도 최소한의 정보 추가 시도
             fallback_key = (msg_id, 1, 0, 1, 1)
             if not any(err.get('_key') == fallback_key for err in self.errors):
                  fallback_info = {'message': message, 'line': 1, 'column': 0, 'to_line': 1, 'end_column': 1, 'errorType': msg_id, '_key': fallback_key}
                  self.errors.append(fallback_info)


    # --- 그래프 관련 메서드 (parso 기반으로 수정) ---
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

    # --- 스코프 관리 (parso API 사용) ---
    def get_current_scope_variables(self) -> Set[str]:
        """현재 방문 중인 노드의 스코프에서 정의된 변수 반환."""
        if self.current_node:
             try:
                 # 현재 노드 또는 부모 스코프에서 정의된 변수 가져오기
                 # parso에서 스코프 경계는 Function, Class, Lambda, Module
                 scope = self.current_node
                 while scope and scope.type not in ('funcdef', 'classdef', 'lambdef', 'file_input', 'module'): # file_input/module이 최상위
                       scope = scope.parent
                 if scope:
                     return collect_defined_variables(scope) # utils 함수 호출
                 else: # 스코프를 찾지 못한 경우 (이론상 발생 어려움)
                      print(f"Warning: Could not find parent scope for node {self.current_node!r}", file=sys.stderr)

             except Exception as e:
                  print(f"Error getting scope variables for node {self.current_node!r}: {e}", file=sys.stderr)
        return set()


    # --- AST 순회 및 분석 실행 (parso 노드 순회) ---
    def visit_node(self, node: parso.tree.BaseNode): # 타입 BaseNode로 변경
         """parso AST 노드를 방문하여 그래프 생성 및 체커 실행."""
         self.current_node = node # 현재 노드 업데이트
         # print(f"[Linter.visit_node] Visiting node: {node.type} at L{node.start_pos[0]}", file=sys.stderr) # 로그 필요시 활성화

         # 1. 그래프 생성 로직 (static 모드)
         if self.mode == 'static':
             try:
                 if node.type == 'funcdef':
                      func_name = node.name.value # parso Name 노드의 값
                      caller_scope = node.get_parent_scope(); caller = getattr(caller_scope, 'name', None) # 부모 스코프 이름 시도
                      caller = getattr(caller, 'value', '<module>') # 이름 노드의 실제 값 또는 모듈
                      self.add_node_to_graph(func_name, type='function', lineno=node.start_pos[0])
                      if caller == '<module>': self.add_edge_to_graph(caller, func_name, type='defines', lineno=node.start_pos[0])
                 elif node.type == 'atom_expr' and len(node.children) > 1 and node.children[1].type == 'trailer' and node.children[1].children[0].value == '(': # 함수 호출
                      caller_scope = node.get_parent_scope(); caller = getattr(caller_scope, 'name', None)
                      caller = getattr(caller, 'value', '<module>')
                      func_part = node.children[0]; called_func_name = None; call_type = 'calls'
                      if func_part.type == 'name': called_func_name = func_part.value
                      elif func_part.type == 'power' and len(func_part.children)>1 and func_part.children[1].type == 'trailer' and func_part.children[1].children[0].value == '.': # 메서드 호출
                          call_type = 'calls_method'
                          attr_name_node = func_part.children[1].children[1]
                          if attr_name_node.type == 'name':
                               obj_expr_str = func_part.children[0].get_code(include_prefix=False).strip()
                               called_func_name = f"{obj_expr_str}.{attr_name_node.value}"
                      if called_func_name and caller: self.add_edge_to_graph(caller, called_func_name, type=call_type, lineno=node.start_pos[0])
                 elif node.type == 'classdef': # 클래스 정의
                      class_name = node.name.value; caller_scope = node.get_parent_scope(); caller = getattr(caller_scope, 'name', None)
                      caller = getattr(caller, 'value', '<module>')
                      self.add_node_to_graph(class_name, type='class', lineno=node.start_pos[0])
                      if caller == '<module>': self.add_edge_to_graph(caller, class_name, type='defines_class', lineno=node.start_pos[0])
             except Exception as e: print(f"Error building graph for parso node {node!r}: {e}", file=sys.stderr)

         # 2. 등록된 체커 실행
         node_type_str = node.type
         for checker in self.checkers:
             if not checker.node_types or node_type_str in checker.node_types:
                 # check_<nodetype> 메서드 호출
                 check_method_name = f'check_{node_type_str}'
                 visitor_method = getattr(checker, check_method_name, None)
                 if visitor_method and callable(visitor_method):
                     try: visitor_method(node)
                     except Exception as e: print(f"Error in checker {checker.__class__.__name__}.{check_method_name}: {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr)

         # 3. 자식 노드 재귀 방문 (Leaf가 아닌 경우만)
         if hasattr(node, 'children'):
             for child in node.children:
                 self.visit_node(child)


    def analyze(self, tree: parso.python.tree.Module):
        """parso AST를 순회하며 분석을 수행합니다."""
        self.errors = [] # 오류 초기화
        self.call_graph = nx.DiGraph() # 그래프 초기화
        self.current_node = None

        print("[Linter.analyze] Starting analysis (parso)...", file=sys.stderr)
        try:
            self.visit_node(tree) # AST 순회 시작
        except Exception as e:
            print(f"!!! Exception during AST traversal: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            # 순회 오류 시 에러 추가
            error_node_mock = type('obj', (object,), {'start_pos': (1,0), 'end_pos': (1,1)})()
            self.add_message('AnalysisError', error_node_mock , f"An error occurred during AST traversal: {e}")
        print("[Linter.analyze] Analysis finished (parso).", file=sys.stderr)

        # 함수 단위 체커 실행 (Recursion 등) - parso 기반 수정 필요
        if self.mode == 'static':
             for checker in self.checkers:
                 if hasattr(checker, 'check_function_recursion'):
                      print(f"[Linter.analyze] Running checker {checker.__class__.__name__} for function recursion.", file=sys.stderr)
                      try:
                          for func_node in tree.iter_funcdefs(): # parso 함수 찾기
                               checker.check_function_recursion(func_node)
                      except Exception as e: print(f"Error in recursion checker {checker.__class__.__name__}: {e}", file=sys.stderr)

        # 그래프 후처리
        if '<module>' in self.call_graph:
             try:
                 if self.call_graph.has_node('<module>'): self.call_graph.remove_node('<module>')
             except Exception as e: print(f"Error removing <module> node from graph: {e}", file=sys.stderr)


# --- analyze_code 함수 (parso 사용) ---
def analyze_code(code: str, mode: str = 'realtime') -> Dict[str, Any]:
    print(f"analyze_code (parso based) called with mode: {mode}", file=sys.stderr)
    syntax_errors = [] # SyntaxError만 저장할 리스트
    runtime_errors = [] # Linter가 찾은 런타임 오류 저장 리스트
    call_graph_data = None
    linter = Linter(mode=mode) # Linter는 항상 생성
    tree: Optional[parso.python.tree.Module] = None

    try:
        # 1. parso로 파싱, 오류 정보 수집
        # error_recovery=True (기본값)로 오류 있어도 계속 파싱
        grammar = parso.load_grammar()
        tree = grammar.parse(code)
        print(f"Parso AST parsed (potentially with errors)", file=sys.stderr)

        # 파싱 오류(SyntaxError) 수집
        for error in grammar.iter_errors(tree):
             line, col = error.start_pos
             to_line, end_col = error.end_pos
             syntax_errors.append({
                 'message': f"SyntaxError: {error.message}",
                 'line': line, 'column': col, 'to_line': to_line, 'end_column': end_col,
                 'errorType': 'SyntaxError'
             })
        print(f"Found {len(syntax_errors)} syntax errors during parsing.", file=sys.stderr)

    except Exception as e: # parso 파싱 자체의 심각한 예외
        print(f"!!! Exception during parso parsing: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        syntax_errors.append({'message': f"An error occurred during parsing: {e}", 'line': 1, 'column': 0, 'errorType': 'AnalysisError'})
        tree = None # 파싱 실패

    # 2. Linter 분석 실행 (파싱 성공 여부와 관계없이 시도 - tree가 None일 수 있음)
    if tree is not None:
        try:
            print("[analyze_code] Starting Linter analysis (parso tree)...", file=sys.stderr)
            linter.analyze(tree) # 불완전한 트리라도 분석 시도
            print("[analyze_code] Linter analysis finished (parso tree).", file=sys.stderr)
            runtime_errors = linter.errors # Linter 오류 저장

            # 그래프 데이터 생성 (static 모드)
            if mode == 'static':
                try:
                    call_graph_data = json_graph.node_link_data(linter.call_graph)
                    print("[analyze_code] Call graph converted to JSON.", file=sys.stderr)
                except ImportError: print("Error: networkx library not found...", file=sys.stderr)
                except Exception as e: print(f"Error converting graph to JSON: {e}", file=sys.stderr); call_graph_data = None
        except Exception as e: # Linter 분석 중 예외
            print(f"!!! Exception during Linter analysis (parso): {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            runtime_errors.append({'message': f"An error occurred during Linter analysis: {e}",'line': 1,'column': 0, 'errorType': 'AnalysisError'})

    # 3. SyntaxError와 Linter 오류 합치기
    all_errors = syntax_errors + runtime_errors

    # 오류 객체에서 내부 키(_key) 제거 (add_message에서 추가한 경우)
    cleaned_errors = [{k: v for k, v in err.items() if k != '_key'} for err in all_errors]
    result = {'errors': cleaned_errors, 'call_graph': call_graph_data}

    if not isinstance(result.get('errors'), list): result['errors'] = []
    print(f"analyze_code returning result with {len(result['errors'])} errors.", file=sys.stderr)
    return result