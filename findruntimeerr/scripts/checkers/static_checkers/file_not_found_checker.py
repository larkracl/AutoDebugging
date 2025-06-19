import astroid
import sys
import os
from ..base_checkers import BaseAstroidChecker

class StaticFileNotFoundChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-file-not-found'; node_types = (astroid.Call,)
    MSGS = {'0801': ("FileNotFoundError: File '%s' may not exist (Static)", 'file-not-found', '')}
    def check(self, node: astroid.Call):
        # --- 디버깅 로그 추가 ---
        print(f"DEBUG: Running {self.NAME} on node: {node.as_string()}", file=sys.stderr)
        try:
            func = node.func
            is_open = False
            # open(...) 또는 io.open(...)
            if isinstance(func, astroid.Name) and func.name == 'open':
                is_open = True
            elif isinstance(func, astroid.Attribute) and func.attrname == 'open':
                is_open = True
            if is_open and node.args:
                file_arg = node.args[0]
                # 상수 문자열 경로: 실제 파일 존재 여부 체크
                if isinstance(file_arg, astroid.Const) and isinstance(file_arg.value, str):
                    file_path = file_arg.value
                    exists = False
                    try:
                        exists = os.path.exists(file_path)
                    except Exception:
                        exists = False
                    if not exists:
                        print(f"DEBUG: {self.NAME} FOUND an error for file '{file_path}' (not found)", file=sys.stderr)
                        self.add_message(node, '0801', (file_path,))
                else:
                    # 동적 경로(상수 아님)는 항상 경고
                    print(f"DEBUG: {self.NAME} FOUND a warning for dynamic file arg: {str(file_arg)}", file=sys.stderr)
                    self.add_message(node, '0801', (str(file_arg),))
        except Exception as e:
            print(f"Error in StaticFileNotFoundChecker: {e}", file=sys.stderr)
