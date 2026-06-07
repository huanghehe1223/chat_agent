"""Safe calculator tool."""

from __future__ import annotations

import ast
import math
import operator
from typing import Any


class CalculatorError(ValueError):
    """Raised when the expression is unsafe or cannot be evaluated."""


_MAX_ABS_RESULT = 1e100
_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
}
_FUNCTIONS = {
    "abs": abs,
    "ceil": math.ceil,
    "cos": math.cos,
    "degrees": math.degrees,
    "exp": math.exp,
    "floor": math.floor,
    "log": math.log,
    "log10": math.log10,
    "max": max,
    "min": min,
    "pow": pow,
    "radians": math.radians,
    "round": round,
    "sin": math.sin,
    "sqrt": math.sqrt,
    "tan": math.tan,
}


def calculate(expression: str) -> dict[str, Any]:
    """Evaluate a simple arithmetic expression with a small AST allowlist."""

    if not isinstance(expression, str) or not expression.strip():
        raise CalculatorError("expression must be a non-empty string.")

    normalized = expression.strip()
    if len(normalized) > 300:
        raise CalculatorError("expression is too long.")

    try:
        tree = ast.parse(normalized, mode="eval")
        result = _eval_node(tree.body)
    except CalculatorError:
        raise
    except ZeroDivisionError as exc:
        raise CalculatorError("division by zero.") from exc
    except OverflowError as exc:
        raise CalculatorError("calculation result is too large.") from exc
    except (SyntaxError, ValueError, TypeError) as exc:
        raise CalculatorError("expression is not valid arithmetic.") from exc

    _ensure_finite_number(result)
    if isinstance(result, float) and result.is_integer():
        result = int(result)

    return {
        "expression": normalized,
        "result": result,
    }


def _eval_node(node: ast.AST) -> float | int:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value

    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise CalculatorError(f"unknown name: {node.id}.")

    if isinstance(node, ast.BinOp):
        operator_fn = _BINARY_OPERATORS.get(type(node.op))
        if operator_fn is None:
            raise CalculatorError("operator is not allowed.")
        if isinstance(node.op, ast.Pow):
            exponent = _eval_node(node.right)
            if abs(exponent) > 100:
                raise CalculatorError("exponent is too large.")
        return _checked_number(operator_fn(_eval_node(node.left), _eval_node(node.right)))

    if isinstance(node, ast.UnaryOp):
        operator_fn = _UNARY_OPERATORS.get(type(node.op))
        if operator_fn is None:
            raise CalculatorError("unary operator is not allowed.")
        return _checked_number(operator_fn(_eval_node(node.operand)))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise CalculatorError("only direct function calls are allowed.")
        function = _FUNCTIONS.get(node.func.id)
        if function is None:
            raise CalculatorError(f"function is not allowed: {node.func.id}.")
        if node.keywords:
            raise CalculatorError("keyword arguments are not allowed.")
        if len(node.args) > 10:
            raise CalculatorError("too many function arguments.")
        args = [_eval_node(arg) for arg in node.args]
        return _checked_number(function(*args))

    raise CalculatorError("expression contains unsupported syntax.")


def _checked_number(value: Any) -> float | int:
    if not isinstance(value, (int, float)):
        raise CalculatorError("calculation result must be numeric.")
    _ensure_finite_number(value)
    if abs(value) > _MAX_ABS_RESULT:
        raise CalculatorError("calculation result is too large.")
    return value


def _ensure_finite_number(value: float | int) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise CalculatorError("calculation result is not finite.")
