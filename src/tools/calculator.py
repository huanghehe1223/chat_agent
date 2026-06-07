"""Safe calculator tool."""

from __future__ import annotations

import ast
import operator
import re
from typing import Any


class CalculatorError(ValueError):
    """Raised when the expression is unsafe or cannot be evaluated."""


_ALLOWED_PATTERN = re.compile(r"^[0-9+\-*/%().\s]+$")
_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}
_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def calculate(expression: str) -> dict[str, Any]:
    """Evaluate a simple arithmetic expression with a small AST allowlist."""

    if not isinstance(expression, str) or not expression.strip():
        raise CalculatorError("expression must be a non-empty string.")

    normalized = expression.strip()
    if len(normalized) > 200:
        raise CalculatorError("expression is too long.")
    if not _ALLOWED_PATTERN.fullmatch(normalized):
        raise CalculatorError("expression may only contain numbers, operators, spaces, and parentheses.")

    try:
        tree = ast.parse(normalized, mode="eval")
        result = _eval_node(tree.body)
    except CalculatorError:
        raise
    except ZeroDivisionError as exc:
        raise CalculatorError("division by zero.") from exc
    except (SyntaxError, ValueError, TypeError) as exc:
        raise CalculatorError("expression is not valid arithmetic.") from exc

    if isinstance(result, float) and result.is_integer():
        result = int(result)

    return {
        "expression": normalized,
        "result": result,
    }


def _eval_node(node: ast.AST) -> float | int:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value

    if isinstance(node, ast.BinOp):
        operator_fn = _BINARY_OPERATORS.get(type(node.op))
        if operator_fn is None:
            raise CalculatorError("operator is not allowed.")
        return operator_fn(_eval_node(node.left), _eval_node(node.right))

    if isinstance(node, ast.UnaryOp):
        operator_fn = _UNARY_OPERATORS.get(type(node.op))
        if operator_fn is None:
            raise CalculatorError("unary operator is not allowed.")
        return operator_fn(_eval_node(node.operand))

    raise CalculatorError("expression contains unsupported syntax.")
