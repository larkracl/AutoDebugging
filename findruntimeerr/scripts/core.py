# scripts/core.py (Linter에 스코프 트리 빌더 추가, 함수 호출 관계 수정)
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
    """Parso AST 순회 및 조건부 Astroid 분석 실행."""
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

    def _build_parso_scope_tree(self, tree: pt.Module):
        """Parso AST를 순회하며 스코프 트리와 심볼 테이블을 구축합니다."""
        if not tree: return
        print("[Linter._build_parso_scope_tree] Building scope tree...", file=sys.stderr)
        self.root_scope = Scope(tree, parent_scope=None)
        self.scope_map[id(tree)] = self.root_scope

        # 스택을 사용한 깊이 우선 탐색으로 스코프 트리 생성
        nodes_to_visit: List[Tuple[parso.tree.BaseNode, Scope]] = [(tree, self.root_scope)]

        while nodes_to_visit:
            current_node, parent_scope = nodes_to_visit.pop(0)

            # 현재 노드가 새로운 스코프를 생성하는지 확인
            current_scope = parent_scope
            if isinstance(current_node, (pt.Function, pt.Class, pt.Lambda)):
                 # 이미 이 노드에 대한 스코프가 생성되지 않았다면 새로 생성
                 if id(current_node) not in self.scope_map:
                      new_scope = Scope(current_node, parent_scope=parent_scope)
                      self.scope_map[id(current_node)] = new_scope
                      current_scope = new_scope
                 else: # 이미 생성되었다면 가져오기
                      current_scope = self.scope_map[id(current_node)]

            # 현재 결정된 스코프에 심볼 채우기
            populate_scope_from_parso(current_scope)

            # 자식 노드들을 방문 목록에 추가
            if hasattr(current_node, 'children'):
                for child in reversed(current_node.children): # 역순으로 추가하여 깊이 우선 유지
                    nodes_to_visit.insert(0, (child, current_scope)) # 자식은 현재 스코프를 부모로 가짐
        print("[Linter._build_parso_scope_tree] Scope tree build finished.", file=sys.stderr)


    def get_scope_for_node(self, node: parso.tree.BaseNode) -> Optional[Scope]:
        """주어진 Parso 노드가 속한 가장 가까운 스코프를 반환합니다."""
        current = node
        while current:
            if id(current) in self.scope_map:
                return self.scope_map[id(current)]
            current = current.parent
        return self.root_scope # 최후의 수단으로 root 스코프 반환

    def visit_parso_node(self, node: parso.tree.BaseNode):
        """Parso AST 노드를 재귀적으로 방문하며 체커를 실행합니다."""
        if not self.grammar: return
        for checker in self.parso_checkers:
            if not checker.node_types or node.type in checker.node_types:
                try:
                    if hasattr(checker, 'check') and callable(checker.check):
                        checker.check(node)
                except Exception as e:
                    error_msg = f"Error in parso checker {checker.NAME}: {e}"
                    print(error_msg, file=sys.stderr)
                    traceback.print_exc(file=sys.stderr)
                    self.add_message('InternalParsoCheckerError', node, error_msg)
        if hasattr(node, 'children'):
            for child in node.children:
                self.visit_parso_node(child)

    def analyze_parso(self, tree: pt.Module):
        if not self.grammar:
             self.add_message('ParsoSetupError', None, "Parso grammar not loaded, cannot perform Parso analysis.")
             return
        # 1. 스코프 트리 및 심볼 테이블 먼저 빌드
        self._build_parso_scope_tree(tree)
        # 2. AST 순회하며 체커 실행
        print("[Linter.analyze_parso] Starting analysis (parso)...", file=sys.stderr)
        try:
            self.visit_parso_node(tree)
        except Exception as e:
            print(f"!!! Exc during Parso AST traversal: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            self.add_message('ParsoTraversalError', None, f"Error: {e}")
        print("[Linter.analyze_parso] Analysis finished (parso).", file=sys.stderr)

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
        print("[Linter.analyze_astroid] Analysis finished (astroid).", file=sys.stderr)

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
    print(f"analyze_code (Parso+Astroid) called with mode: {mode}", file=sys.stderr)
    syntax_errors: List[Dict[str, Any]] = []; call_graph_data: Optional[Dict[str, Any]] = None
    linter = Linter()
    parso_tree: Optional[pt.Module] = None

    if not linter.grammar:
         linter.add_message("ParsoSetupError", None, "Failed to load Parso grammar. Analysis incomplete.")
    else:
        try:
            parso_tree = linter.grammar.parse(code, error_recovery=True)
            print(f"Parso AST parsed (error recovery enabled)", file=sys.stderr)
            for error in linter.grammar.iter_errors(parso_tree):
                 line, col = error.start_pos; to_line, end_col = error.end_pos
                 syntax_errors.append({'message': f"SyntaxError: {error.message}", 'line': line, 'column': col, 'to_line': to_line, 'end_column': max(col + 1, end_col), 'errorType': 'SyntaxError'})
            print(f"Found {len(syntax_errors)} syntax errors during parso parsing.", file=sys.stderr)
        except Exception as e: print(f"!!! CRITICAL Exc during parso parsing: {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr); linter.add_message('ParsoCrashError', None, f"Critical Parso parsing error: {e}"); parso_tree = None

    if parso_tree is not None:
        linter.analyze_parso(parso_tree)

    astroid_tree: Optional[astroid.Module] = None
    run_astroid_analysis = (not syntax_errors and mode == 'static')
    if run_astroid_analysis:
        print("[analyze_code] No syntax errors, mode 'static'. Proceeding with Astroid.", file=sys.stderr)
        try:
            astroid_tree = astroid.parse(code, module_name='<string>')
            print(f"Astroid AST parsed for static analysis.", file=sys.stderr)
        except SyntaxError as e:
            print(f"UNEXPECTED SyntaxError in astroid (static): {e}", file=sys.stderr)
            l, c = e.lineno or 1, (e.offset or 1) -1
            linter.add_message('AstroidSyntaxError', None, f"Astroid SyntaxError: {e.msg} L{l}:C{c+1}")
        except Exception as e:
            print(f"!!! Exc in astroid parsing (static): {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr)
            linter.add_message('AstroidParsingError', None, f"Error parsing with Astroid: {e}")
        if astroid_tree is not None:
            linter.analyze_astroid(astroid_tree)
            try:
                if linter.call_graph.nodes:
                    call_graph_data = json_graph.node_link_data(linter.call_graph)
                    print("[analyze_code] Call graph generated.", file=sys.stderr)
                else:
                    print("[analyze_code] Call graph empty.", file=sys.stderr)
                    call_graph_data = None
            except ImportError:
                print("Error: networkx not found for graph.", file=sys.stderr)
                linter.add_message('GraphError', None, "networkx library not found.")
                call_graph_data = None
            except Exception as e:
                print(f"Error converting graph: {e}", file=sys.stderr)
                linter.add_message('GraphError', None, f"Failed to convert graph: {e}")
                call_graph_data = None
    elif mode == 'static':
        print("[analyze_code] Syntax errors present. Skipping Astroid for static mode.", file=sys.stderr)

    all_errors = syntax_errors + linter.errors
    cleaned_errors = [{k: v for k, v in err.items() if k != '_key'} for err in all_errors]
    result = {'errors': cleaned_errors, 'call_graph': call_graph_data}
    if not isinstance(result.get('errors'), list):
        result['errors'] = []
    print(f"analyze_code returning {len(result['errors'])} total errors.", file=sys.stderr)
    return result