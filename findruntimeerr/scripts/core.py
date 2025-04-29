# core.py
import astroid
import sys
import networkx as nx
from typing import List, Dict, Any, Set, Tuple, Optional, Union
from utils import collect_defined_variables # utils 함수 사용
# checkers 모듈에서 체커 목록과 BaseChecker import
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
        self.current_func_stack = ["<module>"]
        # 스코프 관리: 현재 노드의 스코프(함수/모듈)에 정의된 변수 저장
        self.scope_defined_vars: Dict[astroid.NodeNG, Set[str]] = {}
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
        line = max(1, line); col = max(0, col) # 유효 범위 보정
        error_key = (msg_id, line, col) # 중복 검사를 위한 키

        if not any(err.get('_key') == error_key for err in self.errors):
            error_info = {'message': message,'line': line,'column': col,'errorType': msg_id, '_key': error_key}
            self.errors.append(error_info)

    # --- 그래프 관련 메서드 (이전과 유사) ---
    def add_node_to_graph(self, node_name: str, **kwargs):
        """호출 그래프에 노드를 추가/업데이트합니다."""
        if node_name not in self.call_graph:
            self.call_graph.add_node(node_name, **kwargs)
        else:
            for key, value in kwargs.items():
                 if key not in self.call_graph.nodes[node_name] or self.call_graph.nodes[node_name].get(key) in ('unknown', None) :
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
                 if call_site_line not in existing_data['call_sites']: # 중복 호출 위치 방지
                     existing_data['call_sites'].append(call_site_line)
                     existing_data['call_sites'].sort() # 정렬
            elif call_site_line is not None:
                 existing_data['call_sites'] = [call_site_line]
            for key, value in edge_data.items(): # 다른 속성 업데이트
                 existing_data[key] = value
        else:
             if call_site_line is not None:
                 edge_data['call_sites'] = [call_site_line]
             self.call_graph.add_edge(caller, callee, **edge_data)


    # --- 스코프 관리 메서드 ---
    def enter_scope(self, node: Union[astroid.FunctionDef, astroid.Module, astroid.ClassDef, astroid.Lambda]):
        """새로운 스코프 진입 시 호출됩니다."""
        self.scope_defined_vars[node] = collect_defined_variables(node)
        # NameError 체커 등에 현재 스코프 정보 전달 가능
        if isinstance(node, astroid.FunctionDef):
             self.current_func_stack.append(node.name)
             # 필요한 체커에게 알림
             for checker in self.checkers:
                  if hasattr(checker, 'handle_function_entry'):
                      checker.handle_function_entry(node)


    def leave_scope(self, node: Union[astroid.FunctionDef, astroid.Module, astroid.ClassDef, astroid.Lambda]):
        """스코프를 벗어날 때 호출됩니다."""
        if node in self.scope_defined_vars:
            del self.scope_defined_vars[node]
        if isinstance(node, astroid.FunctionDef):
             if self.current_func_stack and self.current_func_stack[-1] == node.name:
                 self.current_func_stack.pop()
             # 필요한 체커에게 알림
             for checker in self.checkers:
                  if hasattr(checker, 'handle_function_exit'):
                      checker.handle_function_exit(node)


    def get_current_scope_variables(self) -> Set[str]:
        """현재 스코프에서 정의된 변수 집합을 반환합니다."""
        # 스택을 사용하여 현재 스코프 노드를 찾아 변수 반환 (개선 필요)
        # 여기서는 간단하게 마지막 함수 스코프의 변수 반환 (모듈 스코프 고려 필요)
        current_scope_node = self.current_func_stack[-1] # 이름만 있음
        # 실제 노드를 찾아야 함
        # 이 부분은 Linter가 스코프 노드 스택을 직접 관리하는 것이 더 좋음
        # 임시로 빈 집합 반환 또는 다른 방식 구현
        # return self.scope_defined_vars.get(current_scope_node, set()) # 이름으로 노드 찾기 불가

        # Linter가 스코프 스택을 관리한다고 가정
        if self.current_scope_stack: # Linter에 current_scope_stack = [module_node] 추가 가정
             return self.scope_defined_vars.get(self.current_scope_stack[-1], set())
        return set()


    # --- AST 순회 및 분석 실행 ---
    def visit_node(self, node: astroid.NodeNG):
         """AST 노드를 방문하여 그래프 생성 및 체커 실행."""
         # 1. 스코프 진입 처리
         if isinstance(node, (astroid.FunctionDef, astroid.Module, astroid.ClassDef, astroid.Lambda)):
              self.enter_scope(node)

         # 2. 그래프 생성 로직
         try:
             # 함수 정의
             if isinstance(node, astroid.FunctionDef):
                 func_name = node.name
                 self.add_node_to_graph(func_name, type='function', lineno=node.lineno)
                 caller = self.current_func_stack[-1] # 스택 수정 후 스택 접근 방식 변경 필요
                 if caller == '<module>':
                      self.add_edge_to_graph(caller, func_name, type='defines', lineno=node.lineno)

             # 함수 호출
             elif isinstance(node, astroid.Call):
                 caller = self.current_func_stack[-1] # 스택 수정 후 스택 접근 방식 변경 필요
                 called_func_name = None
                 call_type = 'calls'
                 if isinstance(node.func, astroid.Name):
                     called_func_name = node.func.name; call_type = 'calls'
                 elif isinstance(node.func, astroid.Attribute):
                     call_type = 'calls_method'
                     try: called_func_name = f"{node.func.expr.as_string()}.{node.func.attrname}"
                     except Exception: called_func_name = f"?.{node.func.attrname}"
                 if called_func_name and caller:
                     self.add_edge_to_graph(caller, called_func_name, type=call_type, lineno=node.lineno)

             # 클래스 정의
             elif isinstance(node, astroid.ClassDef):
                  class_name = node.name
                  self.add_node_to_graph(class_name, type='class', lineno=node.lineno)
                  caller = self.current_func_stack[-1] # 스택 수정 후 스택 접근 방식 변경 필요
                  if caller == '<module>':
                       self.add_edge_to_graph(caller, class_name, type='defines_class', lineno=node.lineno)
         except Exception as e:
             print(f"Error during graph building for node {node!r}: {e}", file=sys.stderr)

         # 3. 등록된 체커 실행
         for checker in self.checkers:
             # 체커가 특정 노드 타입을 처리하는지 확인하고 check 메서드 호출
             # (이전 답변의 isinstance 검사 방식 사용 또는 더 효율적인 디스패치 방식 구현)
             node_type = type(node)
             if checker.node_types and node_type not in checker.node_types:
                  continue # 체커가 이 노드 타입에 관심 없으면 건너뜀

             if hasattr(checker, 'check'):
                 try:
                      checker.check(node) # 각 체커의 check 메서드 호출
                 except Exception as e:
                      print(f"Error in checker {checker.__class__.__name__} for node {node!r}: {e}", file=sys.stderr)


         # 4. 자식 노드 재귀 방문
         for child in node.get_children():
             self.visit_node(child)

         # 5. 스코프 종료 처리
         if isinstance(node, (astroid.FunctionDef, astroid.Module, astroid.ClassDef, astroid.Lambda)):
              self.leave_scope(node)


    def analyze(self, tree: astroid.Module):
        """AST를 순회하며 분석을 수행합니다."""
        self.errors = []
        self.call_graph = nx.DiGraph()
        # Linter가 스코프 스택을 직접 관리하도록 수정
        self.current_scope_stack = [tree] # 모듈 노드를 기본 스코프로 시작
        self.scope_defined_vars = {tree: collect_defined_variables(tree)}

        print("Starting analysis and graph building...", file=sys.stderr)
        self.visit_node(tree) # AST 순회 시작
        print("Analysis and graph building finished.", file=sys.stderr)

        # --- 함수 단위 체커 실행 (Recursion 등) ---
        if self.mode == 'static':
            for node in tree.body: # 모듈의 최상위 항목만 확인
                if isinstance(node, astroid.FunctionDef):
                    for checker in self.checkers:
                        # 특정 체커가 함수 전체를 분석하는 메서드를 가지는지 확인
                        if hasattr(checker, 'check_function_recursion'):
                             try:
                                 checker.check_function_recursion(node)
                             except Exception as e:
                                  print(f"Error in checker {checker.__class__.__name__} (function check) for {node.name}: {e}", file=sys.stderr)


        # 그래프 후처리
        if '<module>' in self.call_graph:
             # 모듈에서 정의된 노드는 유지하면서 <module> 노드 제거
             successors = list(self.call_graph.successors('<module>'))
             self.call_graph.remove_node('<module>')
             # 필요 시 successors를 루트 노드로 간주하는 로직 추가


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
             # networkx가 import 되어 있다고 가정
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