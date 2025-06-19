# scripts/core.py (Linter 로직 재설계: 재귀 방문, 스코프 직접 전달)
import parso
from parso.python import tree as pt
import astroid
import sys
import networkx as nx
from typing import List, Dict, Any, Optional, Tuple, cast
from networkx.readwrite import json_graph
import traceback

# 새로 만든 symbol_table 과 개선된 utils import
from symbol_table import Scope
from utils import populate_scope_from_parso
from utils import get_type_astroid, is_compatible_astroid, collect_defined_variables_astroid
# 체커들은 이제 checkers 패키지에서 가져옴
from checkers import RT_CHECKERS_CLASSES, STATIC_CHECKERS_CLASSES, BaseParsoChecker, BaseAstroidChecker

class Linter:
    def __init__(self):
        print(f"[Linter.__init__] Initializing Linter", file=sys.stderr)
        self.parso_checkers: List[BaseParsoChecker] = []
        self.astroid_checkers: List[BaseAstroidChecker] = []
        self.errors: List[Dict[str, Any]] = []
        self.call_graph = nx.DiGraph()
        self.grammar: Optional[parso.Grammar] = None
        try:
            self.grammar = parso.load_grammar()
        except Exception as e:
            print(f"FATAL: Could not load parso grammar: {e}", file=sys.stderr)
        self._load_parso_checkers()

        # 스코프 관리용 속성
        self.root_scope: Optional[Scope] = None
        # 노드 -> 스코프 객체 매핑. key를 노드의 id()로 사용하여 객체 자체를 키로 사용
        self.scope_map: Dict[int, Scope] = {}

    def _load_parso_checkers(self):
        if not self.grammar:
             print("[Linter._load_parso_checkers] Parso grammar not loaded. Skipping Parso checker loading.", file=sys.stderr)
             return
        checker_classes = RT_CHECKERS_CLASSES
        print(f"[Linter._load_parso_checkers] Loading {len(checker_classes)} Parso checkers (RT).", file=sys.stderr)
        for checker_class in checker_classes:
            try:
                checker_instance = checker_class(self)
                self.parso_checkers.append(checker_instance)
                print(f"[Linter._load_parso_checkers] Loaded Parso checker: {checker_class.__name__}", file=sys.stderr)
            except Exception as e:
                 self.add_message('CheckerInitError', None, f"Error initializing parso checker {checker_class.__name__}: {e}")

    def _build_and_visit_parso(self, node: parso.tree.BaseNode, current_scope: Scope):
        """
        AST를 재귀적으로 방문하며 스코프 트리를 구축하고, 동시에 체커를 실행합니다.
        """
        # 현재 노드가 새로운 스코프를 정의하는지 확인
        new_scope = current_scope
        if isinstance(node, (pt.Function, pt.Class, pt.Lambda)):
            # 이미 이 노드에 대한 스코프가 생성되지 않았다면 새로 생성
            if id(node) not in self.scope_map:
                new_scope = Scope(node, parent_scope=current_scope)
                self.scope_map[id(node)] = new_scope
                # 새로 생성된 스코프에 심볼 채우기 (파라미터 등)
                populate_scope_from_parso(new_scope)
            else:
                new_scope = self.scope_map[id(node)]

        # 현재 노드에 대해 체커 실행 (현재 스코프 정보 전달)
        for checker in self.parso_checkers:
            if not checker.node_types or node.type in checker.node_types:
                try:
                    # check 메서드가 이제 scope를 인자로 받음
                    # 체커의 check 메서드가 2개의 인자만 받으면 TypeError 발생 가능
                    checker.check(node, new_scope)
                except TypeError as te:
                    # 인자 개수 불일치 문제 디버깅
                    if "takes 2 positional arguments but 3 were given" in str(te):
                        # 스코프 인자 없이 다시 호출 (오래된 체커 호환용)
                        try:
                            checker.check(node)
                        except Exception as e:
                            error_msg = f"Error in legacy parso checker {checker.NAME}: {e}"; print(error_msg, file=sys.stderr); traceback.print_exc(file=sys.stderr)
                            self.add_message('InternalParsoCheckerError', node, error_msg)
                    else:
                        error_msg = f"TypeError in parso checker {checker.NAME}: {te}"; print(error_msg, file=sys.stderr); traceback.print_exc(file=sys.stderr)
                        self.add_message('InternalParsoCheckerError', node, error_msg)
                except Exception as e:
                    error_msg = f"Error in parso checker {checker.NAME}: {e}"; print(error_msg, file=sys.stderr); traceback.print_exc(file=sys.stderr)
                    self.add_message('InternalParsoCheckerError', node, error_msg)

        # 자식 노드 방문
        if hasattr(node, 'children'):
            # 현재 노드가 생성한 새 스코프(new_scope)를 자식들에게 전달
            for child in node.children:
                self._build_and_visit_parso(child, new_scope)

    def get_scope_for_node(self, node: parso.tree.BaseNode) -> Optional[Scope]:
        """주어진 Parso 노드가 속한 가장 가까운 스코프를 반환합니다."""
        current = node
        while current:
            # get_parent_scope()는 가장 가까운 함수/클래스/모듈 스코프 노드를 반환함
            scope_defining_node = current.get_parent_scope()
            if scope_defining_node and id(scope_defining_node) in self.scope_map:
                 return self.scope_map[id(scope_defining_node)]
            # 만약 못찾으면 한 단계 위 부모로 이동
            current = current.parent
        return self.root_scope # 최후의 수단으로 root 스코프 반환

    def analyze_parso(self, tree: pt.Module):
        if not self.grammar:
             self.add_message('ParsoSetupError', None, "Parso grammar not loaded, cannot perform Parso analysis.")
             return
        
        # 1. 루트 스코프 생성 및 심볼 테이블 초기화
        self.root_scope = Scope(tree, parent_scope=None)
        self.scope_map = {id(tree): self.root_scope}
        
        # 2. 스코프 빌드와 체커 실행을 동시에 시작
        print("[Linter.analyze_parso] Starting scope building and analysis...", file=sys.stderr)
        try:
            # 먼저 루트 스코프(모듈)에 대해 심볼을 채움
            populate_scope_from_parso(self.root_scope)
            # 그 다음 재귀적으로 방문 시작
            self._build_and_visit_parso(tree, self.root_scope)
        except Exception as e:
            print(f"!!! Exc during Parso AST traversal: {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr)
            self.add_message('ParsoTraversalError', None, f"Error: {e}")
        print("[Linter.analyze_parso] Analysis finished.", file=sys.stderr)

    def add_message(self, msg_id: str, node: Optional[parso.tree.BaseNode], message: str):
        try:
            line, col, to_line, end_col = 1, 0, 1, 1
            if node:
                line, col = node.start_pos; to_line, end_col = node.end_pos
                line = max(1, line); col = max(0, col)
                to_line = max(line, to_line); end_col = max(col + 1, end_col)
            error_key = (msg_id, line, col, to_line, end_col)
            if not any(err.get('_key') == error_key for err in self.errors):
                self.errors.append({ 'message': message, 'line': line, 'column': col, 'to_line': to_line, 'end_column': end_col, 'errorType': msg_id, '_key': error_key })
        except Exception as e:
            print(f"Error adding parso message '{msg_id}': {e}", file=sys.stderr)
            fallback_key = (msg_id, 1, 0, 1, 1)
            if not any(err.get('_key') == fallback_key for err in self.errors):
                 self.errors.append({'message': message, 'line': 1, 'column': 0, 'to_line': 1, 'end_column': 1, 'errorType': msg_id, '_key': fallback_key})

    def add_astroid_message(self, msg_id: str, node: astroid.NodeNG, message: str):
         try:
             line = node.fromlineno or 1; col = node.col_offset or 0
             to_line = node.tolineno or line; end_col = node.end_col_offset or (col + 1)
             line = max(1, line); col = max(0, col); to_line = max(line, to_line); end_col = max(col + 1, end_col)
             error_key = (msg_id, line, col, to_line, end_col)
             if not any(err.get('_key') == error_key for err in self.errors):
                 # --- 디버깅 로그 추가 ---
                 print(f"DEBUG: [Astroid Linter] ADDING error: {msg_id} - {message}", file=sys.stderr)
                 self.errors.append({ 'message': message, 'line': line, 'column': col, 'to_line': to_line, 'end_column': end_col, 'errorType': msg_id, '_key': error_key })
         except Exception as e:
             print(f"Error adding astroid message '{msg_id}': {e}", file=sys.stderr)
             fallback_key = (msg_id, 1, 0, 1, 1)
             if not any(err.get('_key') == fallback_key for err in self.errors):
                  self.errors.append({'message': message, 'line': 1, 'column': 0, 'to_line': 1, 'end_column': 1, 'errorType': msg_id, '_key': fallback_key})

    def _load_astroid_checkers(self):
        if not self.astroid_checkers:
             checker_classes = STATIC_CHECKERS_CLASSES
             print(f"[Linter._load_astroid_checkers] Loading {len(checker_classes)} Astroid checkers.", file=sys.stderr)
             for CClass in checker_classes:
                 try: self.astroid_checkers.append(CClass(self)); print(f"[Linter._load_astroid_checkers] Loaded Astroid checker: {CClass.__name__}", file=sys.stderr)
                 except Exception as e: self.add_message('CheckerInitError', None, f"Error initializing astroid checker {CClass.__name__}: {e}")

    def visit_astroid_node(self, node: astroid.NodeNG):
         try:
             if isinstance(node, astroid.FunctionDef): self.add_node_to_graph(node.qname(), type='function', lineno=node.fromlineno)
             elif isinstance(node, astroid.Call):
                  caller_qname = node.scope().qname() if hasattr(node.scope(), 'qname') else '<module>'
                  called_qname = None; call_type = 'calls'
                  try:
                       inferred = list(node.func.infer(context=None));
                       if inferred and inferred[0] is not astroid.Uninferable:
                            called_qname = getattr(inferred[0], 'qname', getattr(inferred[0], 'name', None));
                            if isinstance(inferred[0], astroid.BoundMethod): call_type = 'calls_method'
                  except astroid.InferenceError: pass
                  if caller_qname and called_qname: self.add_edge_to_graph(caller_qname, called_qname, type=call_type, lineno=node.fromlineno)
             elif isinstance(node, astroid.ClassDef): self.add_node_to_graph(node.qname(), type='class', lineno=node.fromlineno)
         except Exception as e: print(f"Error building graph for astroid node: {repr(node)[:100]}...: {e}", file=sys.stderr)
         for checker in self.astroid_checkers:
             if not checker.node_types or isinstance(node, checker.node_types):
                 try:
                      if hasattr(checker, 'check') and callable(checker.check): checker.check(node)
                 except Exception as e: error_msg = f"Error in astroid checker {checker.NAME}: {e}"; print(error_msg, file=sys.stderr); traceback.print_exc(file=sys.stderr); self.add_astroid_message('InternalAstroidCheckerError', node, error_msg)
         for child in node.get_children(): self.visit_astroid_node(child)

    def analyze_astroid(self, tree: astroid.Module):
        self._load_astroid_checkers(); self.call_graph = nx.DiGraph()
        print("[Linter.analyze_astroid] Starting analysis (astroid)...", file=sys.stderr)
        try:
            self.visit_astroid_node(tree)
            print("[Linter.analyze_astroid] Running function-level astroid checkers...", file=sys.stderr)
            for checker in self.astroid_checkers:
                if hasattr(checker, 'check_function_recursion') and callable(checker.check_function_recursion):
                     print(f"[Linter.analyze_astroid] Running {checker.NAME} for recursion.")
                     try:
                          for func_node in tree.nodes_of_class(astroid.FunctionDef): checker.check_function_recursion(func_node)
                     except Exception as e: print(f"Error in recursion checker {checker.NAME}: {e}", file=sys.stderr)
        except Exception as e: print(f"!!! Exc during Astroid AST traversal: {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr); self.add_message('AstroidTraversalError', None, f"Error: {e}")
        print("[Linter.analyze_astroid] Analysis finished.", file=sys.stderr)

    def add_node_to_graph(self, node_name: str, **kwargs):
        if not isinstance(node_name, str) or not node_name: return
        if node_name not in self.call_graph: self.call_graph.add_node(node_name, **kwargs)
        else:
            nd = self.call_graph.nodes[node_name]
            for k, v in kwargs.items():
                 if k == 'lineno' and 'lineno' not in nd: nd[k] = v
                 elif nd.get(k) in (None, 'unknown'): nd[k] = v

    def add_edge_to_graph(self, caller: str, callee: str, **kwargs):
        if not isinstance(caller, str) or not caller or not isinstance(callee, str) or not callee: return
        self.add_node_to_graph(caller, type='unknown'); self.add_node_to_graph(callee, type='unknown')
        ln = kwargs.pop('lineno', None); ed = kwargs
        if self.call_graph.has_edge(caller, callee):
            exd = self.call_graph.edges[caller, callee]
            if 'call_sites' in exd and ln is not None:
                 if ln not in exd['call_sites']: exd['call_sites'].append(ln); exd['call_sites'].sort()
            elif ln is not None: exd['call_sites'] = [ln]
            for k, v in ed.items():
                 if k not in exd or exd.get(k) == 'unknown': exd[k] = v
        else:
             if ln is not None: ed['call_sites'] = [ln]
             self.call_graph.add_edge(caller, callee, **ed)


def analyze_code(code: str, mode: str = 'realtime') -> Dict[str, Any]:
    print(f"analyze_code (Mode-Separated) called with mode: {mode}", file=sys.stderr)
    linter = Linter()
    call_graph_data: Optional[Dict[str, Any]] = None
    final_errors: List[Dict[str, Any]] = []

    # ====================================================================
    # 'realtime' 모드: Parso 파싱 + Parso RT 체커 실행
    # ====================================================================
    if mode == 'realtime':
        syntax_errors: List[Dict[str, Any]] = []
        parso_tree: Optional[pt.Module] = None
        if not linter.grammar:
             linter.add_message("ParsoSetupError", None, "Parso grammar not loaded.")
        else:
            try:
                parso_tree = linter.grammar.parse(code, error_recovery=True)
                print(f"Parso AST parsed for realtime.", file=sys.stderr)
                for error in linter.grammar.iter_errors(parso_tree):
                     line, col = error.start_pos; to_line, end_col = error.end_pos
                     syntax_errors.append({'message': f"SyntaxError: {error.message}", 'line': line, 'column': col, 'to_line': to_line, 'end_column': max(col + 1, end_col), 'errorType': 'SyntaxError'})
                print(f"Found {len(syntax_errors)} syntax errors.", file=sys.stderr)
            except Exception as e:
                 linter.add_message('ParsoCrashError', None, f"Critical Parso parsing error: {e}")

        if parso_tree is not None:
            linter.analyze_parso(parso_tree) # Parso RT 체커 실행

        final_errors = syntax_errors + linter.errors

    # ====================================================================
    # 'static' 모드: Astroid 파싱 + Astroid Static 체커만 실행
    # ====================================================================
    elif mode == 'static':
        astroid_tree: Optional[astroid.Module] = None
        try:
            astroid_tree = astroid.parse(code, module_name='<string>')
            print(f"Astroid AST parsed for static analysis.", file=sys.stderr)
        except SyntaxError as e:
            # SyntaxError 발생 시, 이 오류 하나만 보고하고 종료
            error = {'message': f"SyntaxError: {e.msg}", 'line': e.lineno or 1, 'column': (e.offset or 1) - 1, 'to_line': e.lineno or 1, 'end_column': (e.offset or 1), 'errorType': 'SyntaxError'}
            final_errors.append(error)
            # 'static' 모드에서는 SyntaxError 발생 시 더 이상 진행하지 않음
        except Exception as e:
             linter.add_message('AstroidParsingError', None, f"Error parsing with Astroid: {e}")
             final_errors = linter.errors

        if astroid_tree is not None:
            # Astroid 상세 분석 실행 (그래프 생성 포함)
            linter.analyze_astroid(astroid_tree)
            try:
                if linter.call_graph.nodes: call_graph_data = json_graph.node_link_data(linter.call_graph)
            except Exception as e: linter.add_message('GraphError', None, f"Failed to convert call graph: {e}")
            final_errors = linter.errors # Astroid 체커 결과만 사용
    else:
        final_errors = [{'message': f"Unknown analysis mode: {mode}", 'line': 1, 'column': 0, 'to_line': 1, 'end_column': 1, 'errorType': 'ModeError'}]

    # 최종 결과 반환
    cleaned_errors = [{k: v for k, v in err.items() if k != '_key'} for err in final_errors]
    result = {'errors': cleaned_errors, 'call_graph': call_graph_data}
    print(f"analyze_code returning {len(result['errors'])} errors for mode '{mode}'.", file=sys.stderr)
    return result