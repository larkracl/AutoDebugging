import parso
from checkers.base_checkers import BaseParsoChecker
from symbol_table import Scope
from utils import check_module_exists

class RTImportErrorChecker(BaseParsoChecker):
    """설치되지 않은 모듈을 import 하는 경우를 탐지하는 체커."""
    MSG_ID_PREFIX = 'E'
    NAME = 'rt-import-error-parso'
    node_types = ('import_name', 'import_from')
    MSGS = {'1001': ("ImportError: No module named '%s'", 'no-module-found-rt-parso', '')}

    def check(self, node: parso.tree.BaseNode, current_scope: Scope):
        """import 구문에서 모듈 존재 여부를 검사합니다."""
        
        # `import a.b, c.d` 또는 `from x.y import ...` 구문에서 모든 모듈 이름을 추출
        try:
            # get_code()를 사용하여 노드의 전체 텍스트를 가져오고, 파싱하여 모듈 이름 추출
            code_segment = node.get_code()
            
            if node.type == 'import_name': # `import a, b.c as d`
                # 'import' 키워드 제거 후 쉼표로 분리
                parts = code_segment.replace('import', '').strip().split(',')
                for part in parts:
                    # 'as' 키워드가 있으면 그 앞부분만 모듈 이름으로 간주
                    module_name = part.split(' as ')[0].strip()
                    if not check_module_exists(module_name):
                        self.add_message(node, '1001', (module_name,))

            elif node.type == 'import_from': # `from a.b import c`
                # 'from'과 'import' 사이의 문자열이 모듈 이름
                parts = code_segment.split(' import ')
                if len(parts) > 1:
                    module_name = parts[0].replace('from', '').strip()
                    if not check_module_exists(module_name):
                        self.add_message(node, '1001', (module_name,))
        except Exception:
            # 파싱 오류 발생 시 조용히 실패
            pass