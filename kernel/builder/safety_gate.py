"""Safety gate — AST-based static analysis of generated Python code."""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Imports that are never permitted in generated code
_BLOCKED_IMPORTS: frozenset[str] = frozenset(
    {
        "subprocess",
        "importlib",
        "ctypes",
        "multiprocessing",
        "shutil",
        "signal",
        "socket",
        "threading",
        "requests",
        "urllib",
        "urllib3",
        "httpx",
        "aiohttp",
        "http",
    }
)

# Built-in callables that must not appear in generated code
_BLOCKED_BUILTINS: frozenset[str] = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "breakpoint",
        "open",
    }
)

# Dotted attribute chains that are blocked (e.g. "os.system")
_BLOCKED_ATTR_CHAINS: frozenset[str] = frozenset(
    {
        "os.system",
        "os.popen",
        "os.remove",
        "os.unlink",
        "os.rmdir",
        "os.rename",
        "os.makedirs",
    }
)


@dataclass
class SafetyResult:
    """Result of a safety analysis pass.

    Attributes:
        safe: True when no blocking issues were found.
        issues: List of hard-block violation messages.
        warnings: List of non-blocking concern messages.
    """

    safe: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class _SafetyVisitor(ast.NodeVisitor):
    """AST visitor that collects safety violations."""

    def __init__(self) -> None:
        self.issues: list[str] = []
        self.warnings: list[str] = []

    # ------------------------------------------------------------------
    # Import checks
    # ------------------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        """Check top-level import statements.

        Args:
            node: The Import AST node.
        """
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in _BLOCKED_IMPORTS:
                self.issues.append(
                    f"Blocked import '{alias.name}' at line {node.lineno}"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Check 'from X import ...' statements.

        Args:
            node: The ImportFrom AST node.
        """
        module = node.module or ""
        root = module.split(".")[0]
        if root in _BLOCKED_IMPORTS:
            self.issues.append(
                f"Blocked import from '{module}' at line {node.lineno}"
            )
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Call checks
    # ------------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        """Check function / method call nodes.

        Args:
            node: The Call AST node.
        """
        func = node.func

        # Direct name calls: eval(...), exec(...), etc.
        if isinstance(func, ast.Name):
            if func.id in _BLOCKED_BUILTINS:
                self.issues.append(
                    f"Blocked builtin call '{func.id}()' at line {node.lineno}"
                )

        # Attribute calls: os.system(...), etc.
        elif isinstance(func, ast.Attribute):
            chain = self._get_attr_chain(func)
            if chain in _BLOCKED_ATTR_CHAINS:
                self.issues.append(
                    f"Blocked attribute call '{chain}()' at line {node.lineno}"
                )

        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Attribute access checks
    # ------------------------------------------------------------------

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Check attribute access patterns (non-call context).

        Args:
            node: The Attribute AST node.
        """
        chain = self._get_attr_chain(node)
        if chain in _BLOCKED_ATTR_CHAINS:
            # Only warn if not already caught as a call (parent handles calls)
            # Here we add a warning for bare attribute access (e.g. fn = os.system)
            if isinstance(node.ctx, ast.Load):
                self.warnings.append(
                    f"Suspicious attribute access '{chain}' at line {node.lineno}"
                )
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_attr_chain(self, node: ast.Attribute | ast.Name) -> str:
        """Reconstruct a dotted name string from an Attribute/Name AST node.

        Args:
            node: An Attribute or Name AST node.

        Returns:
            Dotted string such as "os.path.join", or empty string when the
            chain cannot be fully resolved.
        """
        parts: list[str] = []
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        else:
            # Cannot resolve — give up
            return ""
        return ".".join(reversed(parts))


def check_code(source: str) -> SafetyResult:
    """Analyse Python source code for security violations.

    Uses true AST parsing — not string matching — so obfuscation via
    string concatenation or renamed imports is NOT detected. This is
    intentional: the gate targets naive/auto-generated code, not
    adversarial inputs.

    Args:
        source: Python source code to analyse.

    Returns:
        SafetyResult indicating whether the code is safe, with detailed
        issue and warning lists.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.warning("Syntax error while parsing code: %s", exc)
        return SafetyResult(
            safe=False,
            issues=[f"Syntax error: {exc}"],
            warnings=[],
        )

    visitor = _SafetyVisitor()
    visitor.visit(tree)

    safe = len(visitor.issues) == 0
    if not safe:
        logger.warning("Safety gate blocked code — issues: %s", visitor.issues)
    elif visitor.warnings:
        logger.info("Safety gate warnings: %s", visitor.warnings)

    return SafetyResult(safe=safe, issues=visitor.issues, warnings=visitor.warnings)
