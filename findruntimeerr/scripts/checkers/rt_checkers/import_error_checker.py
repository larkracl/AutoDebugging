# scripts/checkers/rt_checkers/import_error_checker.py
import parso
from parso.python import tree as pt

from checkers.base_checkers import BaseParsoChecker
from symbol_table import Scope
from utils import check_module_exists

class RTImportErrorChecker(BaseParsoChecker):
    """설치되지 않은 모듈을 import 하는 경우를 탐지하는 체커."""
    MSG_ID_PREFIX = 'E'
    NAME = 'rt-import-error-parso'
    node_types = ('import_name', 'import_from')
    MSGS = {'1001': ("ImportError: No module named '%s' (RT-Parso)", 'no-module-found-rt-parso', '')}

    def check(self, node: parso.tree.BaseNode, current_scope: Scope):
        """import 구문에서 모듈 존재 여부를 검사합니다."""
        
        module_name_node = None
        
        if node.type == 'import_name':
            # `import a.b.c` -> 'a.b.c' 부분을 가져옴 (dotted_name)
            # 복잡한 `import a, b` 케이스를 위해 모든 모듈을 순회
            dotted_as_names = next((c for c in node.children if c.type == 'dotted_as_names'), None)
            if dotted_as_names:
                for d_as_name in dotted_as_names.children:
                    if d_as_name.type == 'dotted_as_name':
                        module_node = d_as_name.children[0]
                        module_name_str = module_node.get_code().strip()
                        if not check_module_exists(module_name_str):
                            self.add_message(module_node, '1001', (module_name_str,))
                return # 개별적으로 처리했으므로 여기서 종료

        elif node.type == 'import_from':
            # `from a.b.c import ...` -> 'a.b.c' 부분을 가져옴
            module_name_node = next((c for c in node.children if c.type in ('dotted_name', 'name')), None)

        if module_name_node:
            module_name_str = module_name_node.get_code().strip()
            if not check_module_exists(module_name_str):
                self.add_message(module_name_node, '1001', (module_name_str,))