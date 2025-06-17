import astroid
import parso
from typing import Dict, Tuple, Optional
import sys

class BaseAstroidChecker:
    """Astroid 기반 체커의 베이스 클래스."""
    MSG_ID_PREFIX = 'E'
    NAME = 'base-astroid-checker'
    MSGS: Dict[str, Tuple[str, str, str]] = {'F0001': ('Internal error (astroid): %s', 'fatal-error-astroid', '')}
    node_types: Tuple[type, ...] = ()
    def __init__(self, linter): self.linter = linter
    def add_message(self, node: astroid.NodeNG, msg_key: str, args: Optional[Tuple]=None):
        if self.NAME == 'base-astroid-checker': return
        if msg_key in self.MSGS:
            final_message = (self.MSGS[msg_key][0] % args) if args else self.MSGS[msg_key][0]
            self.linter.add_astroid_message(f"{self.MSG_ID_PREFIX}{msg_key}", node, final_message)
        else: print(f"Warning: Unknown msg key '{msg_key}' in {self.NAME}", file=sys.stderr)
    def check(self, node: astroid.NodeNG): raise NotImplementedError

class BaseParsoChecker:
    """Parso 기반 체커의 베이스 클래스."""
    MSG_ID_PREFIX = 'E'
    NAME = 'base-parso-checker'
    MSGS: Dict[str, Tuple[str, str, str]] = {'F0002': ('Internal error (parso): %s', 'fatal-error-parso', '')}
    node_types: Tuple[str, ...] = ()
    def __init__(self, linter): self.linter = linter
    def add_message(self, node: parso.tree.BaseNode, msg_key: str, args: Optional[Tuple]=None):
        if self.NAME == 'base-parso-checker': return
        if msg_key in self.MSGS:
            final_message = (self.MSGS[msg_key][0] % args) if args else self.MSGS[msg_key][0]
            self.linter.add_message(f"{self.MSG_ID_PREFIX}{msg_key}", node, final_message)
        else: print(f"Warning: Unknown msg key '{msg_key}' in {self.NAME}", file=sys.stderr)
    def check(self, node: parso.tree.BaseNode): raise NotImplementedError
