# -*- coding: utf-8 -*-
"""
agents/math_agent.py — Полный математический / финансовый движок.

Архитектура:
  Пользователь (текст) → LLM разбирает → MathEngine считает точно → LLM объясняет

Движки:
  CASEngine       — символьная математика (SymPy): уравнения, производные, интегралы
  StatsEngine     — статистика и теория вероятностей (SciPy/NumPy)
  FinanceEngine   — финансовые формулы: NPV, IRR, ROI, VaR, Sharpe, Kelly, Black-Scholes
  MonteCarloEngine — симуляции Монте-Карло для стратегий и портфелей
  PortfolioEngine — оптимизация портфеля по Марковицу

LLM не считает сам — он только:
  1. Понимает вопрос на русском/английском
  2. Выделяет переменные и параметры
  3. Переводит в формат движка
  4. Объясняет результат человеческим языком
"""

from __future__ import annotations

import json
import logging
import math
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

log = logging.getLogger("agents.math")

# ── Опциональные зависимости (graceful degradation) ──────────────────────────

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None  # type: ignore

try:
    import scipy.stats as scipy_stats
    import scipy.optimize as scipy_opt
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    scipy_stats = None  # type: ignore
    scipy_opt = None    # type: ignore

try:
    import sympy as sp
    from sympy import symbols, solve, diff, integrate, simplify, latex, N as sp_N
    from sympy.parsing.sympy_parser import parse_expr
    HAS_SYMPY = True
except ImportError:
    HAS_SYMPY = False
    sp = None  # type: ignore


# ══════════════════════════════════════════════════════════════════════════════
# 1. CAS ENGINE — Символьная математика (SymPy)
# ══════════════════════════════════════════════════════════════════════════════

class CASEngine:
    """Символьный математический движок на базе SymPy."""

    def available(self) -> bool:
        return HAS_SYMPY

    def solve_equation(self, equation_str: str,
                       variable: str = "x") -> Dict[str, Any]:
        """Решить уравнение или систему уравнений."""
        if not HAS_SYMPY:
            return {"error": "SymPy не установлен. pip install sympy"}
        try:
            var = sp.Symbol(variable)
            # Убираем пробелы, нормализуем
            eq = equation_str.replace("^", "**").strip()
            if "=" in eq:
                left, right = eq.split("=", 1)
                expr = parse_expr(left, local_dict={variable: var}) - \
                       parse_expr(right, local_dict={variable: var})
            else:
                expr = parse_expr(eq, local_dict={variable: var})
            solutions = solve(expr, var)
            return {
                "equation": equation_str,
                "variable": variable,
                "solutions": [str(s) for s in solutions],
                "numeric": [float(sp_N(s)) for s in solutions
                            if s.is_real and s.is_finite],
                "latex": f"${latex(expr)} = 0$",
            }
        except Exception as e:
            return {"error": str(e)}

    def differentiate(self, expr_str: str, variable: str = "x",
                      order: int = 1) -> Dict[str, Any]:
        """Вычислить производную."""
        if not HAS_SYMPY:
            return {"error": "SymPy не установлен"}
        try:
            var = sp.Symbol(variable)
            expr = parse_expr(expr_str.replace("^", "**"),
                              local_dict={variable: var})
            result = diff(expr, var, order)
            simplified = simplify(result)
            return {
                "expression": expr_str,
                "derivative_order": order,
                "result": str(simplified),
                "latex": f"$\\frac{{d^{order}}}{{d{variable}^{order}}}({latex(expr)}) = {latex(simplified)}$",
            }
        except Exception as e:
            return {"error": str(e)}

    def integrate_expr(self, expr_str: str, variable: str = "x",
                       lower: Optional[float] = None,
                       upper: Optional[float] = None) -> Dict[str, Any]:
        """Вычислить интеграл."""
        if not HAS_SYMPY:
            return {"error": "SymPy не установлен"}
        try:
            var = sp.Symbol(variable)
            expr = parse_expr(expr_str.replace("^", "**"),
                              local_dict={variable: var})
            if lower is not None and upper is not None:
                result = integrate(expr, (var, lower, upper))
                numeric = float(sp_N(result))
                return {
                    "expression": expr_str,
                    "type": "definite",
                    "bounds": [lower, upper],
                    "result": str(result),
                    "numeric": numeric,
                    "latex": f"$\\int_{{{lower}}}^{{{upper}}} {latex(expr)} d{variable} = {latex(result)}$",
                }
            else:
                result = integrate(expr, var)
                return {
                    "expression": expr_str,
                    "type": "indefinite",
                    "result": str(result) + " + C",
                    "latex": f"$\\int {latex(expr)} d{variable} = {latex(result)} + C$",
                }
        except Exception as e:
            return {"error": str(e)}

    def simplify_expr(self, expr_str: str) -> Dict[str, Any]:
        """Упростить математическое выражение."""
        if not HAS_SYMPY:
            return {"error": "SymPy не установлен"}
        try:
            expr = parse_expr(expr_str.replace("^", "**"))
            simplified = simplify(expr)
            numeric = None
            try:
                numeric = float(sp_N(simplified))
            except Exception:
                pass
            return {
                "original": expr_str,
                "simplified": str(simplified),
                "numeric": numeric,
                "latex": f"${latex(simplified)}$",
            }
        except Exception as e:
            return {"error": str(e)}

    def evaluate(self, expr_str: str,
                 variables: Dict[str, float] = None) -> Dict[str, Any]:
        """Вычислить числовое значение выражения."""
        try:
            # Безопасное вычисление через math
            safe_vars = {
                "pi": math.pi, "e": math.e,
                "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
                "sin": math.sin, "cos": math.cos, "tan": math.tan,
                "exp": math.exp, "abs": abs, "pow": math.pow,
                "ceil": math.ceil, "floor": math.floor,
            }
            if variables:
                safe_vars.update(variables)
            expr = expr_str.replace("^", "**")
            result = eval(expr, {"__builtins__": {}}, safe_vars)
            return {"expression": expr_str, "result": result}
        except Exception as e:
            return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# 2. STATS ENGINE — Статистика и теория вероятностей
# ══════════════════════════════════════════════════════════════════════════════

class StatsEngine:
    """Статистика, вероятности, распределения."""

    def probability_distribution(self, dist_name: str, params: dict,
                                 query: dict) -> Dict[str, Any]:
        """
        Вычислить вероятности для распределения.
        dist_name: normal | binomial | poisson | exponential | uniform | t
        query: {type: pdf|cdf|ppf|mean|std, x: value, p: probability}
        """
        result = {}
        try:
            dist_lower = dist_name.lower()

            if HAS_SCIPY:
                # SciPy распределения
                dists = {
                    "normal":      lambda p: scipy_stats.norm(loc=p.get("mean", 0), scale=p.get("std", 1)),
                    "binomial":    lambda p: scipy_stats.binom(n=p["n"], p=p["p"]),
                    "poisson":     lambda p: scipy_stats.poisson(mu=p["lambda"]),
                    "exponential": lambda p: scipy_stats.expon(scale=1/p.get("lambda", 1)),
                    "uniform":     lambda p: scipy_stats.uniform(loc=p.get("a", 0), scale=p.get("b", 1)-p.get("a", 0)),
                    "t":           lambda p: scipy_stats.t(df=p.get("df", 10)),
                    "chi2":        lambda p: scipy_stats.chi2(df=p.get("df", 1)),
                    "lognormal":   lambda p: scipy_stats.lognorm(s=p.get("sigma", 1), scale=math.exp(p.get("mu", 0))),
                }
                dist_fn = dists.get(dist_lower)
                if not dist_fn:
                    return {"error": f"Неизвестное распределение: {dist_name}"}
                dist = dist_fn(params)
                query_type = query.get("type", "cdf")
                x = query.get("x", 0)
                p = query.get("p", 0.95)

                if query_type == "pdf":
                    result = {"pdf": float(dist.pdf(x)), "x": x}
                elif query_type == "cdf":
                    result = {"cdf": float(dist.cdf(x)), "P(X <= x)": float(dist.cdf(x)), "x": x}
                elif query_type == "ppf":
                    result = {"quantile": float(dist.ppf(p)), "p": p}
                elif query_type in ("stats", "all"):
                    mean, var = dist.stats(moments="mv")
                    result = {
                        "mean": float(mean),
                        "variance": float(var),
                        "std": float(math.sqrt(var)),
                        "median": float(dist.ppf(0.5)),
                        "p5":  float(dist.ppf(0.05)),
                        "p95": float(dist.ppf(0.95)),
                        "p99": float(dist.ppf(0.99)),
                    }
            else:
                # Чистый Python — только normal
                if dist_lower == "normal":
                    mean = params.get("mean", 0)
                    std = params.get("std", 1)
                    query_type = query.get("type", "cdf")
                    x = query.get("x", 0)
                    z = (x - mean) / std
                    cdf = 0.5 * (1 + math.erf(z / math.sqrt(2)))
                    result = {
                        "cdf": cdf, "P(X <= x)": cdf, "x": x,
                        "mean": mean, "std": std,
                    }

        except Exception as e:
            result = {"error": str(e)}

        return {"distribution": dist_name, "params": params, **result}

    def expected_value(self, outcomes: List[float],
                       probabilities: List[float]) -> Dict[str, Any]:
        """Математическое ожидание дискретной случайной величины."""
        if len(outcomes) != len(probabilities):
            return {"error": "Количество исходов и вероятностей не совпадает"}
        prob_sum = sum(probabilities)
        if abs(prob_sum - 1.0) > 0.01:
            return {"error": f"Сумма вероятностей = {prob_sum:.4f} (должна быть 1.0)"}
        ev = sum(o * p for o, p in zip(outcomes, probabilities))
        e_x2 = sum(o**2 * p for o, p in zip(outcomes, probabilities))
        variance = e_x2 - ev**2
        return {
            "expected_value": ev,
            "variance": variance,
            "std": math.sqrt(abs(variance)),
            "outcomes": outcomes,
            "probabilities": probabilities,
            "interpretation": f"В среднем ожидаемый исход: {ev:.4f}",
        }

    def bayes_update(self, prior: float, likelihood: float,
                     likelihood_neg: float) -> Dict[str, Any]:
        """
        Байесовское обновление вероятности.
        P(H|E) = P(E|H)*P(H) / [P(E|H)*P(H) + P(E|¬H)*P(¬H)]
        """
        prior_neg = 1 - prior
        posterior = (likelihood * prior) / (likelihood * prior + likelihood_neg * prior_neg)
        likelihood_ratio = likelihood / likelihood_neg
        return {
            "prior": prior,
            "likelihood_ratio": likelihood_ratio,
            "posterior": posterior,
            "update_factor": f"{likelihood_ratio:.2f}x",
            "interpretation": (
                f"До события: {prior:.1%} | После события: {posterior:.1%} "
                f"(вероятность {'выросла' if posterior > prior else 'упала'} "
                f"в {likelihood_ratio:.1f} раза)"
            ),
        }

    def confidence_interval(self, data: List[float],
                            confidence: float = 0.95) -> Dict[str, Any]:
        """Доверительный интервал для выборки."""
        n = len(data)
        if n < 2:
            return {"error": "Нужно минимум 2 наблюдения"}
        mean = sum(data) / n
        variance = sum((x - mean)**2 for x in data) / (n - 1)
        std = math.sqrt(variance)
        se = std / math.sqrt(n)

        if HAS_SCIPY:
            t_crit = float(scipy_stats.t.ppf((1 + confidence) / 2, df=n-1))
        else:
            # Приближение для n > 30
            z_table = {0.90: 1.645, 0.95: 1.960, 0.99: 2.576}
            t_crit = z_table.get(confidence, 1.960)

        margin = t_crit * se
        return {
            "mean": mean,
            "std": std,
            "n": n,
            "confidence": confidence,
            "margin_of_error": margin,
            "lower": mean - margin,
            "upper": mean + margin,
            "interval": f"[{mean-margin:.4f}, {mean+margin:.4f}]",
            "interpretation": f"С {confidence:.0%} вероятностью истинное среднее находится в [{mean-margin:.4f}, {mean+margin:.4f}]",
        }

    def descriptive_stats(self, data: List[float]) -> Dict[str, Any]:
        """Описательная статистика для набора данных."""
        n = len(data)
        if not data:
            return {"error": "Пустой набор данных"}
        sorted_data = sorted(data)
        mean = sum(data) / n
        variance = sum((x - mean)**2 for x in data) / (n - 1) if n > 1 else 0
        std = math.sqrt(variance)
        median = sorted_data[n // 2] if n % 2 else (sorted_data[n//2-1] + sorted_data[n//2]) / 2
        skewness = sum(((x - mean) / std)**3 for x in data) / n if std > 0 else 0
        result = {
            "n": n, "mean": mean, "median": median,
            "std": std, "variance": variance,
            "min": min(data), "max": max(data),
            "range": max(data) - min(data),
            "skewness": skewness,
            "p25": sorted_data[int(0.25 * n)],
            "p75": sorted_data[int(0.75 * n)],
            "iqr": sorted_data[int(0.75 * n)] - sorted_data[int(0.25 * n)],
        }
        if HAS_SCIPY:
            result["kurtosis"] = float(scipy_stats.kurtosis(data))
            result["shapiro_pvalue"] = float(scipy_stats.shapiro(data).pvalue) if n >= 3 else None
        return result


# ══════════════════════════════════════════════════════════════════════════════
# 3. FINANCE ENGINE — Финансовые формулы
# ══════════════════════════════════════════════════════════════════════════════

class FinanceEngine:
    """Точные финансовые расчёты. LLM не считает — использует эти формулы."""

    # ── Базовые ────────────────────────────────────────────────────────────────

    def compound_interest(self, principal: float, annual_rate: float,
                          years: float, n: int = 1) -> Dict[str, Any]:
        """Сложный процент. A = P*(1 + r/n)^(n*t)"""
        rate = annual_rate / 100 if annual_rate > 1 else annual_rate
        A = principal * (1 + rate / n) ** (n * years)
        total_interest = A - principal
        return {
            "principal": principal,
            "annual_rate_pct": rate * 100,
            "years": years,
            "compounding_per_year": n,
            "final_amount": A,
            "total_interest": total_interest,
            "return_pct": (A / principal - 1) * 100,
            "formula": f"A = {principal} × (1 + {rate:.4f}/{n})^({n}×{years}) = {A:.2f}",
        }

    def cagr(self, initial: float, final: float,
             years: float) -> Dict[str, Any]:
        """Среднегодовой темп роста. CAGR = (final/initial)^(1/years) - 1"""
        if initial <= 0 or years <= 0:
            return {"error": "Начальная стоимость и период должны быть > 0"}
        rate = (final / initial) ** (1 / years) - 1
        return {
            "initial": initial, "final": final, "years": years,
            "cagr_pct": rate * 100,
            "total_return_pct": (final / initial - 1) * 100,
            "formula": f"CAGR = ({final}/{initial})^(1/{years}) - 1 = {rate:.4f}",
        }

    def roi(self, cost: float, revenue: float) -> Dict[str, Any]:
        """Return on Investment. ROI = (revenue - cost) / cost"""
        if cost == 0:
            return {"error": "Затраты не могут быть 0"}
        roi_val = (revenue - cost) / cost
        return {
            "cost": cost, "revenue": revenue,
            "profit": revenue - cost,
            "roi_pct": roi_val * 100,
            "multiplier": revenue / cost,
            "formula": f"ROI = ({revenue} - {cost}) / {cost} = {roi_val:.4f}",
        }

    # ── NPV / IRR ──────────────────────────────────────────────────────────────

    def npv(self, rate: float, cash_flows: List[float]) -> Dict[str, Any]:
        """
        Чистая приведённая стоимость.
        NPV = sum(CF_t / (1+r)^t) для t=0,1,...,n
        cash_flows[0] — обычно отрицательный (начальные инвестиции)
        """
        r = rate / 100 if rate > 1 else rate
        npv_val = sum(cf / (1 + r) ** t for t, cf in enumerate(cash_flows))
        pv_flows = [cf / (1 + r) ** t for t, cf in enumerate(cash_flows)]
        return {
            "rate_pct": r * 100,
            "cash_flows": cash_flows,
            "pv_of_flows": [round(pv, 2) for pv in pv_flows],
            "npv": npv_val,
            "decision": "✅ Выгодно (NPV > 0)" if npv_val > 0 else "❌ Невыгодно (NPV < 0)",
            "interpretation": f"Проект {'создаёт' if npv_val > 0 else 'уничтожает'} стоимость: {npv_val:,.2f}",
        }

    def irr(self, cash_flows: List[float]) -> Dict[str, Any]:
        """
        Внутренняя норма доходности — ставка при которой NPV = 0.
        Используется метод Ньютона-Рафсона.
        """
        def _npv(r, cfs):
            return sum(cf / (1 + r) ** t for t, cf in enumerate(cfs))

        def _npv_prime(r, cfs):
            return sum(-t * cf / (1 + r) ** (t + 1) for t, cf in enumerate(cfs))

        if HAS_SCIPY:
            try:
                irr_val = scipy_opt.brentq(_npv, -0.999, 100, args=(cash_flows,))
                return {
                    "cash_flows": cash_flows,
                    "irr_pct": irr_val * 100,
                    "interpretation": f"IRR = {irr_val*100:.2f}% — минимальная требуемая доходность",
                }
            except Exception:
                pass

        # Ньютон-Рафсон
        r = 0.1
        for _ in range(1000):
            npv_val = _npv(r, cash_flows)
            npv_d = _npv_prime(r, cash_flows)
            if abs(npv_d) < 1e-10:
                break
            r_new = r - npv_val / npv_d
            if abs(r_new - r) < 1e-8:
                r = r_new
                break
            r = r_new

        if abs(_npv(r, cash_flows)) < 0.01:
            return {
                "cash_flows": cash_flows,
                "irr_pct": r * 100,
                "interpretation": f"IRR = {r*100:.2f}%",
            }
        return {"error": "IRR не сходится для данных потоков"}

    # ── РИСК ───────────────────────────────────────────────────────────────────

    def value_at_risk(self, returns: List[float],
                      confidence: float = 0.95,
                      portfolio_value: float = 10000) -> Dict[str, Any]:
        """
        Value at Risk — максимальный ожидаемый убыток при данном уровне доверия.
        Методы: исторический и параметрический.
        """
        n = len(returns)
        if n < 10:
            return {"error": "Нужно минимум 10 наблюдений"}

        # Исторический VaR
        sorted_r = sorted(returns)
        idx = int((1 - confidence) * n)
        hist_var_pct = sorted_r[idx] if idx < n else sorted_r[0]
        hist_var_usd = abs(hist_var_pct * portfolio_value)

        # Параметрический VaR
        mean = sum(returns) / n
        std = math.sqrt(sum((r - mean)**2 for r in returns) / (n-1))

        if HAS_SCIPY:
            z = float(scipy_stats.norm.ppf(1 - confidence))
        else:
            z_table = {0.90: -1.282, 0.95: -1.645, 0.99: -2.326}
            z = z_table.get(confidence, -1.645)

        param_var_pct = mean + z * std
        param_var_usd = abs(param_var_pct * portfolio_value)

        # CVaR (Expected Shortfall)
        tail = sorted_r[:max(1, idx)]
        cvar_pct = sum(tail) / len(tail) if tail else hist_var_pct
        cvar_usd = abs(cvar_pct * portfolio_value)

        return {
            "confidence": confidence,
            "portfolio_value": portfolio_value,
            "n_observations": n,
            "historical_var_pct": hist_var_pct * 100,
            "historical_var_usd": hist_var_usd,
            "parametric_var_pct": param_var_pct * 100,
            "parametric_var_usd": param_var_usd,
            "cvar_pct": cvar_pct * 100,
            "cvar_usd": cvar_usd,
            "mean_return": mean * 100,
            "std_return": std * 100,
            "interpretation": (
                f"С вероятностью {confidence:.0%} убыток за период "
                f"не превысит {hist_var_usd:,.0f} ({abs(hist_var_pct)*100:.1f}%). "
                f"В худших {(1-confidence)*100:.0f}% случаев — в среднем {cvar_usd:,.0f}."
            ),
        }

    def sharpe_ratio(self, returns: List[float],
                     risk_free_rate: float = 0.02) -> Dict[str, Any]:
        """Коэффициент Шарпа = (доход - безрисковая ставка) / волатильность."""
        n = len(returns)
        if n < 2:
            return {"error": "Нужно минимум 2 доходности"}
        mean = sum(returns) / n
        std = math.sqrt(sum((r - mean)**2 for r in returns) / (n-1))
        ann_factor = 252 if n > 100 else 12 if n > 20 else 1
        ann_return = mean * ann_factor
        ann_std = std * math.sqrt(ann_factor)
        rfr_period = risk_free_rate / ann_factor

        sharpe = (mean - rfr_period) / std if std > 0 else 0
        sharpe_ann = (ann_return - risk_free_rate) / ann_std if ann_std > 0 else 0

        # Сортино (только отрицательная волатильность)
        neg = [r for r in returns if r < rfr_period]
        downside_std = math.sqrt(sum(r**2 for r in neg) / n) if neg else std
        sortino = (mean - rfr_period) / downside_std if downside_std > 0 else 0

        return {
            "n": n,
            "mean_return_pct": mean * 100,
            "std_pct": std * 100,
            "risk_free_rate_pct": risk_free_rate * 100,
            "sharpe_ratio": sharpe,
            "sharpe_annualized": sharpe_ann,
            "sortino_ratio": sortino,
            "interpretation": (
                f"Sharpe = {sharpe_ann:.2f} — "
                f"{'отличный' if sharpe_ann > 2 else 'хороший' if sharpe_ann > 1 else 'приемлемый' if sharpe_ann > 0.5 else 'плохой'} "
                f"риск/доходность"
            ),
        }

    def max_drawdown(self, prices: List[float]) -> Dict[str, Any]:
        """Максимальная просадка = максимальное падение от пика."""
        if len(prices) < 2:
            return {"error": "Нужно минимум 2 цены"}
        peak = prices[0]
        max_dd = 0
        peak_idx = 0
        trough_idx = 0
        for i, price in enumerate(prices):
            if price > peak:
                peak = price
                peak_idx = i
            dd = (price - peak) / peak
            if dd < max_dd:
                max_dd = dd
                trough_idx = i
        recovery = None
        for i in range(trough_idx, len(prices)):
            if prices[i] >= prices[peak_idx]:
                recovery = i - trough_idx
                break
        return {
            "max_drawdown_pct": max_dd * 100,
            "peak_value": prices[peak_idx],
            "trough_value": prices[trough_idx],
            "peak_index": peak_idx,
            "trough_index": trough_idx,
            "recovery_periods": recovery,
            "interpretation": f"Максимальная просадка: {max_dd*100:.1f}%",
        }

    # ── KELLY CRITERION ────────────────────────────────────────────────────────

    def kelly_criterion(self, win_probability: float,
                        win_amount: float,
                        loss_amount: float = 1.0,
                        fractional: float = 0.5) -> Dict[str, Any]:
        """
        Критерий Келли — оптимальный размер ставки.
        f* = (bp - q) / b
        b = win_amount/loss_amount, p = win_probability, q = 1-p
        fractional < 1 — более консервативный вариант (рекомендуется 0.25-0.5)
        """
        p = win_probability
        q = 1 - p
        b = win_amount / loss_amount

        kelly_full = (b * p - q) / b
        kelly_frac = kelly_full * fractional

        if kelly_full <= 0:
            return {
                "kelly_full_pct": kelly_full * 100,
                "kelly_fraction_pct": kelly_frac * 100,
                "recommendation": "❌ НЕ СТАВИТЬ — математическое ожидание отрицательное",
                "expected_value_per_bet": p * win_amount - q * loss_amount,
            }

        ev = p * win_amount - q * loss_amount
        return {
            "win_probability": p,
            "loss_probability": q,
            "win_amount": win_amount,
            "loss_amount": loss_amount,
            "b_ratio": b,
            "kelly_full_pct": kelly_full * 100,
            "kelly_fraction_pct": kelly_frac * 100,
            "expected_value_per_unit": ev,
            "formula": f"Kelly = ({b:.2f}×{p:.2f} - {q:.2f}) / {b:.2f} = {kelly_full:.4f}",
            "interpretation": (
                f"Полный Келли: {kelly_full*100:.1f}% от капитала. "
                f"Дробный ({fractional:.0%}): {kelly_frac*100:.1f}%. "
                f"Ожидаемая прибыль на единицу риска: {ev:.4f}"
            ),
            "recommendation": (
                f"{'✅' if ev > 0 else '❌'} Ставить {kelly_frac*100:.1f}% от капитала "
                f"(дробный Келли {fractional:.0%})"
            ),
        }

    # ── BLACK-SCHOLES ──────────────────────────────────────────────────────────

    def black_scholes(self, S: float, K: float, T: float,
                      r: float, sigma: float,
                      option_type: str = "call") -> Dict[str, Any]:
        """
        Модель Блэка-Шоулза для оценки опционов.
        S = текущая цена актива
        K = страйк (цена исполнения)
        T = время до экспирации (в годах)
        r = безрисковая ставка
        sigma = волатильность (годовая)
        """
        if T <= 0:
            # Стоимость при экспирации
            if option_type.lower() == "call":
                return {"price": max(0, S - K), "intrinsic": max(0, S - K)}
            else:
                return {"price": max(0, K - S), "intrinsic": max(0, K - S)}

        def _norm_cdf(x: float) -> float:
            return 0.5 * (1 + math.erf(x / math.sqrt(2)))

        d1 = (math.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)

        if option_type.lower() == "call":
            price = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
            delta = _norm_cdf(d1)
        else:
            price = K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)
            delta = _norm_cdf(d1) - 1

        # Greeks
        gamma = math.exp(-d1**2 / 2) / (S * sigma * math.sqrt(T) * math.sqrt(2 * math.pi))
        vega  = S * math.sqrt(T) * math.exp(-d1**2 / 2) / math.sqrt(2 * math.pi) / 100
        theta = (-S * sigma * math.exp(-d1**2/2) / (2*math.sqrt(T)*math.sqrt(2*math.pi))
                 - r * K * math.exp(-r*T) * _norm_cdf(d2)) / 365
        intrinsic = max(0, S - K) if option_type == "call" else max(0, K - S)
        time_value = price - intrinsic

        return {
            "option_type": option_type,
            "spot": S, "strike": K, "expiry_years": T,
            "risk_free_rate_pct": r * 100,
            "volatility_pct": sigma * 100,
            "price": price,
            "intrinsic_value": intrinsic,
            "time_value": time_value,
            "d1": d1, "d2": d2,
            "greeks": {
                "delta": delta,
                "gamma": gamma,
                "vega": vega,
                "theta": theta,
            },
            "interpretation": (
                f"Опцион {'колл' if option_type == 'call' else 'пут'}: "
                f"справедливая цена = {price:.4f} "
                f"(внутренняя {intrinsic:.4f} + временная {time_value:.4f}). "
                f"Delta = {delta:.3f}"
            ),
        }

    def break_even(self, fixed_costs: float,
                   variable_cost_per_unit: float,
                   price_per_unit: float) -> Dict[str, Any]:
        """Точка безубыточности."""
        if price_per_unit <= variable_cost_per_unit:
            return {"error": "Цена должна быть выше переменных затрат"}
        margin = price_per_unit - variable_cost_per_unit
        be_units = fixed_costs / margin
        be_revenue = be_units * price_per_unit
        return {
            "fixed_costs": fixed_costs,
            "variable_cost_per_unit": variable_cost_per_unit,
            "price_per_unit": price_per_unit,
            "contribution_margin": margin,
            "break_even_units": be_units,
            "break_even_revenue": be_revenue,
            "margin_pct": margin / price_per_unit * 100,
            "interpretation": f"Нужно продать {be_units:.0f} единиц ({be_revenue:,.0f}) для покрытия затрат",
        }


# ══════════════════════════════════════════════════════════════════════════════
# 4. MONTE CARLO ENGINE — Симуляции
# ══════════════════════════════════════════════════════════════════════════════

class MonteCarloEngine:
    """Монте-Карло симуляции для оценки риска и оптимизации стратегий."""

    def __init__(self, seed: int = 42):
        self._seed = seed

    def _rng(self):
        if HAS_NUMPY:
            return np.random.RandomState(self._seed)
        random.seed(self._seed)
        return None

    def simulate_strategy(self, win_prob: float,
                           payoff_ratio: float,
                           bankroll: float = 1000,
                           bet_fraction: float = 0.1,
                           n_bets: int = 100,
                           n_simulations: int = 10000) -> Dict[str, Any]:
        """
        Симуляция торговой стратегии / ставок.
        Возвращает распределение финальных капиталов.
        """
        rng = self._rng()
        final_values = []

        for _ in range(n_simulations):
            capital = bankroll
            for _ in range(n_bets):
                if capital <= 0:
                    break
                bet = capital * bet_fraction
                if HAS_NUMPY:
                    win = rng.random() < win_prob
                else:
                    win = random.random() < win_prob
                if win:
                    capital += bet * payoff_ratio
                else:
                    capital -= bet
            final_values.append(capital)

        if HAS_NUMPY:
            fv = np.array(final_values)
            mean_final = float(np.mean(fv))
            median_final = float(np.median(fv))
            std_final = float(np.std(fv))
            p5 = float(np.percentile(fv, 5))
            p25 = float(np.percentile(fv, 25))
            p75 = float(np.percentile(fv, 75))
            p95 = float(np.percentile(fv, 95))
            prob_profit = float(np.mean(fv > bankroll))
            prob_ruin = float(np.mean(fv < bankroll * 0.1))
        else:
            fv_sorted = sorted(final_values)
            n = len(fv_sorted)
            mean_final = sum(fv_sorted) / n
            median_final = fv_sorted[n // 2]
            std_final = math.sqrt(sum((x - mean_final)**2 for x in fv_sorted) / n)
            p5 = fv_sorted[int(0.05 * n)]
            p25 = fv_sorted[int(0.25 * n)]
            p75 = fv_sorted[int(0.75 * n)]
            p95 = fv_sorted[int(0.95 * n)]
            prob_profit = sum(1 for x in fv_sorted if x > bankroll) / n
            prob_ruin = sum(1 for x in fv_sorted if x < bankroll * 0.1) / n

        kelly_bet = ((win_prob * payoff_ratio - (1 - win_prob)) / payoff_ratio
                     if payoff_ratio > 0 else 0)

        return {
            "parameters": {
                "win_probability": win_prob,
                "payoff_ratio": payoff_ratio,
                "bankroll": bankroll,
                "bet_fraction": bet_fraction,
                "n_bets": n_bets,
                "n_simulations": n_simulations,
            },
            "results": {
                "mean_final": mean_final,
                "median_final": median_final,
                "std_final": std_final,
                "p5_final": p5,
                "p25_final": p25,
                "p75_final": p75,
                "p95_final": p95,
                "prob_profitable": prob_profit,
                "prob_ruin": prob_ruin,
            },
            "kelly_optimal_fraction": kelly_bet,
            "interpretation": (
                f"{n_simulations} симуляций по {n_bets} ставок:\n"
                f"  Средний итог: {mean_final:,.0f} (медиана: {median_final:,.0f})\n"
                f"  Прибыльных сценариев: {prob_profit:.1%}\n"
                f"  Риск потери >90%: {prob_ruin:.1%}\n"
                f"  5%-95% диапазон: [{p5:,.0f} — {p95:,.0f}]\n"
                f"  Оптимальный Келли: {kelly_bet*100:.1f}% от капитала"
            ),
        }

    def portfolio_simulation(self, expected_returns: List[float],
                              volatilities: List[float],
                              weights: List[float],
                              n_periods: int = 252,
                              n_simulations: int = 5000,
                              initial_value: float = 10000) -> Dict[str, Any]:
        """
        Симуляция портфеля методом Монте-Карло.
        expected_returns: годовые доходности активов
        volatilities: годовые волатильности
        """
        if not HAS_NUMPY:
            return {"error": "NumPy необходим для портфельной симуляции. pip install numpy"}

        n_assets = len(expected_returns)
        rng = np.random.RandomState(self._seed)

        # Дневные параметры
        daily_ret = np.array(expected_returns) / 252
        daily_vol = np.array(volatilities) / np.sqrt(252)
        w = np.array(weights)
        w /= w.sum()

        portfolio_values = []
        for _ in range(n_simulations):
            asset_returns = rng.normal(daily_ret, daily_vol, (n_periods, n_assets))
            # Портфельная доходность
            port_returns = asset_returns @ w
            cum_return = np.prod(1 + port_returns)
            portfolio_values.append(float(initial_value * cum_return))

        pv = np.array(portfolio_values)
        ann_return = (np.mean(pv) / initial_value) ** (252 / n_periods) - 1
        var_95 = float(np.percentile(pv, 5))
        cvar_95 = float(np.mean(pv[pv <= var_95]))

        return {
            "initial_value": initial_value,
            "n_periods": n_periods,
            "n_simulations": n_simulations,
            "mean_final": float(np.mean(pv)),
            "median_final": float(np.median(pv)),
            "std_final": float(np.std(pv)),
            "var_95_usd": initial_value - var_95,
            "cvar_95_usd": initial_value - cvar_95,
            "prob_profit": float(np.mean(pv > initial_value)),
            "annualized_return_pct": ann_return * 100,
            "p5": float(np.percentile(pv, 5)),
            "p50": float(np.percentile(pv, 50)),
            "p95": float(np.percentile(pv, 95)),
            "interpretation": (
                f"Портфель через {n_periods} торговых дней:\n"
                f"  Средний итог: {np.mean(pv):,.0f}\n"
                f"  Вероятность прибыли: {np.mean(pv > initial_value):.1%}\n"
                f"  VaR(95%): -{initial_value - var_95:,.0f}\n"
                f"  Годовая доходность: {ann_return*100:.1f}%"
            ),
        }

    def optimal_bet_simulation(self, win_prob: float,
                                payoff_ratio: float,
                                bankroll: float = 1000,
                                n_bets: int = 100) -> Dict[str, Any]:
        """
        Найти оптимальный размер ставки через симуляцию.
        Тестирует от 1% до 100% Келли.
        """
        kelly_full = (win_prob * payoff_ratio - (1 - win_prob)) / payoff_ratio
        if kelly_full <= 0:
            return {"error": "Стратегия убыточна — Келли отрицателен"}

        fractions = [f/100 for f in range(1, 101, 2)]
        best_fraction = 0
        best_median = 0
        results = []

        for frac in fractions:
            bet_f = kelly_full * frac
            sim = self.simulate_strategy(
                win_prob, payoff_ratio, bankroll, bet_f,
                n_bets, n_simulations=2000
            )
            median_val = sim["results"]["median_final"]
            results.append({"fraction": frac, "kelly_frac": bet_f,
                             "median_final": median_val})
            if median_val > best_median:
                best_median = median_val
                best_fraction = frac

        return {
            "kelly_full_pct": kelly_full * 100,
            "optimal_fraction_of_kelly": best_fraction,
            "optimal_bet_pct": kelly_full * best_fraction * 100,
            "expected_median_final": best_median,
            "top_fractions": sorted(results, key=lambda x: x["median_final"], reverse=True)[:5],
            "interpretation": (
                f"Оптимальный размер: {kelly_full*best_fraction*100:.1f}% от капитала "
                f"({best_fraction:.0%} от полного Келли). "
                f"Медианный результат после {n_bets} ставок: {best_median:,.0f}"
            ),
        }


# ══════════════════════════════════════════════════════════════════════════════
# 5. PORTFOLIO ENGINE — Оптимизация портфеля
# ══════════════════════════════════════════════════════════════════════════════

class PortfolioEngine:
    """Оптимизация портфеля по Марковицу и эффективная граница."""

    def optimize_sharpe(self, expected_returns: List[float],
                        cov_matrix: List[List[float]],
                        risk_free_rate: float = 0.02,
                        n_portfolios: int = 5000) -> Dict[str, Any]:
        """
        Максимизация коэффициента Шарпа.
        Перебирает случайные веса и находит оптимальный портфель.
        """
        if not HAS_NUMPY:
            return {"error": "NumPy необходим. pip install numpy"}

        n = len(expected_returns)
        mu = np.array(expected_returns)
        cov = np.array(cov_matrix)

        best_sharpe = -np.inf
        best_weights = None
        results = []

        rng = np.random.RandomState(42)
        for _ in range(n_portfolios):
            w = rng.dirichlet(np.ones(n))
            port_return = float(w @ mu)
            port_var = float(w @ cov @ w)
            port_std = math.sqrt(port_var)
            sharpe = (port_return - risk_free_rate) / port_std if port_std > 0 else 0
            results.append((sharpe, port_return, port_std, w.tolist()))
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_weights = w.tolist()
                best_return = port_return
                best_std = port_std

        # Минимальная дисперсия
        min_var_result = min(results, key=lambda x: x[2])

        return {
            "max_sharpe": {
                "weights": best_weights,
                "expected_return_pct": best_return * 100,
                "volatility_pct": best_std * 100,
                "sharpe_ratio": best_sharpe,
            },
            "min_variance": {
                "weights": min_var_result[3],
                "expected_return_pct": min_var_result[1] * 100,
                "volatility_pct": min_var_result[2] * 100,
                "sharpe_ratio": min_var_result[0],
            },
            "n_portfolios_tested": n_portfolios,
            "interpretation": (
                f"Портфель максимального Шарпа: доходность {best_return*100:.1f}%, "
                f"волатильность {best_std*100:.1f}%, Шарп {best_sharpe:.2f}"
            ),
        }


# ══════════════════════════════════════════════════════════════════════════════
# 6. ГЛАВНЫЙ АГЕНТ
# ══════════════════════════════════════════════════════════════════════════════

class MathAgent:
    """
    Главный математический агент.
    LLM разбирает запрос → точный движок считает → LLM объясняет.
    """

    def __init__(self):
        self.cas = CASEngine()
        self.stats = StatsEngine()
        self.finance = FinanceEngine()
        self.mc = MonteCarloEngine()
        self.portfolio = PortfolioEngine()
        log.info("MathAgent ready | sympy=%s numpy=%s scipy=%s",
                 HAS_SYMPY, HAS_NUMPY, HAS_SCIPY)

    def process(self, text: str, source: str = "gui") -> str:
        """Главный обработчик — маршрутизирует по типу задачи."""
        from brain.llm_router import LLMRouter, LLMRequest

        llm = LLMRouter.get()
        text_lower = text.lower()

        # ── 1. Определить тип задачи через быстрый LLM ───────────────────────
        classify_prompt = (
            f"Определи тип математической/финансовой задачи (одно слово):\n\n"
            f"Запрос: {text}\n\n"
            f"Типы: equation (уравнение), derivative (производная), "
            f"integral (интеграл), expression (вычислить выражение), "
            f"stats (статистика/вероятность), distribution (распределение), "
            f"ev (мат.ожидание), bayes (байес), confidence (доверительный интервал), "
            f"npv (NPV/IRR), roi (ROI/прибыль), compound (сложный процент), "
            f"var (VaR/риск), sharpe (Шарп/Сортино), kelly (Келли/ставка), "
            f"blackscholes (опцион), monte_carlo (симуляция/Монте-Карло), "
            f"portfolio (портфель), breakeven (безубыточность), cagr (CAGR), "
            f"drawdown (просадка), general (общий расчёт)\n\n"
            f"Ответь ТОЛЬКО одним словом из списка."
        )
        task_type = llm.ask_fast(classify_prompt).strip().lower().split()[0]
        log.debug("MathAgent task_type: %s", task_type)

        # ── 2. Извлечь параметры через LLM ───────────────────────────────────
        params = self._extract_params(text, task_type, llm)

        # ── 3. Выполнить точный расчёт ────────────────────────────────────────
        calc_result = self._calculate(task_type, params, text)

        # ── 4. LLM объясняет результат ────────────────────────────────────────
        return self._explain(text, task_type, calc_result, params, llm)

    def _extract_params(self, text: str, task_type: str,
                        llm) -> Dict[str, Any]:
        """LLM извлекает параметры из текста в JSON."""
        from brain.llm_router import LLMRequest

        schema_map = {
            "equation":    '{"equation": "выражение=0 или само выражение", "variable": "x"}',
            "derivative":  '{"expression": "f(x)", "variable": "x", "order": 1}',
            "integral":    '{"expression": "f(x)", "variable": "x", "lower": null, "upper": null}',
            "expression":  '{"expression": "математическое выражение", "variables": {}}',
            "stats":       '{"data": [список чисел]}',
            "distribution":'{"dist": "normal", "params": {"mean": 0, "std": 1}, "query": {"type": "cdf", "x": 0}}',
            "ev":          '{"outcomes": [список исходов], "probabilities": [вероятности]}',
            "bayes":       '{"prior": 0.5, "likelihood": 0.9, "likelihood_neg": 0.1}',
            "confidence":  '{"data": [список чисел], "confidence": 0.95}',
            "npv":         '{"rate": 0.1, "cash_flows": [-1000, 300, 400, 500]}',
            "roi":         '{"cost": 1000, "revenue": 1500}',
            "compound":    '{"principal": 1000, "annual_rate": 10, "years": 5, "n": 1}',
            "var":         '{"returns": [список доходностей], "confidence": 0.95, "portfolio_value": 10000}',
            "sharpe":      '{"returns": [список доходностей], "risk_free_rate": 0.02}',
            "kelly":       '{"win_probability": 0.6, "win_amount": 1.5, "loss_amount": 1.0, "fractional": 0.5}',
            "blackscholes":'{"S": 100, "K": 100, "T": 0.25, "r": 0.05, "sigma": 0.2, "option_type": "call"}',
            "monte_carlo": '{"win_prob": 0.55, "payoff_ratio": 1.5, "bankroll": 1000, "bet_fraction": 0.1, "n_bets": 100, "n_simulations": 5000}',
            "portfolio":   '{"expected_returns": [0.10, 0.08], "cov_matrix": [[0.04,0.01],[0.01,0.02]], "risk_free_rate": 0.02}',
            "breakeven":   '{"fixed_costs": 10000, "variable_cost_per_unit": 5, "price_per_unit": 15}',
            "cagr":        '{"initial": 1000, "final": 2000, "years": 5}',
            "drawdown":    '{"prices": [список цен]}',
        }
        schema = schema_map.get(task_type, '{"values": []}')

        prompt = (
            f"Извлеки числовые параметры из запроса и верни JSON.\n\n"
            f"ЗАПРОС: {text}\n\n"
            f"ОЖИДАЕМЫЙ ФОРМАТ JSON:\n{schema}\n\n"
            f"ВАЖНО:\n"
            f"- Верни ТОЛЬКО валидный JSON, без комментариев\n"
            f"- Все числа — float или int (не строки)\n"
            f"- Если параметр не указан — используй дефолтное значение из схемы\n"
            f"- Проценты оставляй как есть (10% = 10, не 0.10), кроме вероятностей (0.6, не 60%)"
        )
        req = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            task_type="fast", max_tokens=600, temperature=0.1,
        )
        resp = llm.ask(req)
        try:
            # Извлекаем JSON из ответа
            match = re.search(r'\{.*\}', resp.content, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as e:
            log.debug("Param extraction failed: %s", e)
        return {}

    def _calculate(self, task_type: str, params: Dict,
                   original_text: str) -> Dict[str, Any]:
        """Выполнить точный расчёт через нужный движок."""
        try:
            # CAS
            if task_type == "equation":
                return self.cas.solve_equation(
                    params.get("equation", original_text),
                    params.get("variable", "x")
                )
            if task_type == "derivative":
                return self.cas.differentiate(
                    params.get("expression", original_text),
                    params.get("variable", "x"),
                    int(params.get("order", 1))
                )
            if task_type == "integral":
                return self.cas.integrate_expr(
                    params.get("expression", original_text),
                    params.get("variable", "x"),
                    params.get("lower"), params.get("upper")
                )
            if task_type == "expression":
                expr = params.get("expression", original_text)
                variables = params.get("variables") or {}
                result = self.cas.evaluate(expr, variables)
                if HAS_SYMPY and "error" in result:
                    result = self.cas.simplify_expr(expr)
                return result

            # Статистика
            if task_type == "stats":
                data = params.get("data", [])
                return self.stats.descriptive_stats(data)
            if task_type == "distribution":
                return self.stats.probability_distribution(
                    params.get("dist", "normal"),
                    params.get("params", {}),
                    params.get("query", {"type": "stats"})
                )
            if task_type == "ev":
                return self.stats.expected_value(
                    params.get("outcomes", []),
                    params.get("probabilities", [])
                )
            if task_type == "bayes":
                return self.stats.bayes_update(
                    float(params.get("prior", 0.5)),
                    float(params.get("likelihood", 0.8)),
                    float(params.get("likelihood_neg", 0.2))
                )
            if task_type == "confidence":
                return self.stats.confidence_interval(
                    params.get("data", []),
                    float(params.get("confidence", 0.95))
                )

            # Финансы
            if task_type == "npv":
                return self.finance.npv(
                    float(params.get("rate", 0.1)),
                    params.get("cash_flows", [0])
                )
            if task_type == "roi":
                return self.finance.roi(
                    float(params.get("cost", 0)),
                    float(params.get("revenue", 0))
                )
            if task_type == "compound":
                return self.finance.compound_interest(
                    float(params.get("principal", 1000)),
                    float(params.get("annual_rate", 10)),
                    float(params.get("years", 5)),
                    int(params.get("n", 1))
                )
            if task_type == "var":
                returns = params.get("returns", [])
                return self.finance.value_at_risk(
                    returns,
                    float(params.get("confidence", 0.95)),
                    float(params.get("portfolio_value", 10000))
                )
            if task_type == "sharpe":
                return self.finance.sharpe_ratio(
                    params.get("returns", []),
                    float(params.get("risk_free_rate", 0.02))
                )
            if task_type == "kelly":
                return self.finance.kelly_criterion(
                    float(params.get("win_probability", 0.5)),
                    float(params.get("win_amount", 1.0)),
                    float(params.get("loss_amount", 1.0)),
                    float(params.get("fractional", 0.5))
                )
            if task_type == "blackscholes":
                return self.finance.black_scholes(
                    float(params.get("S", 100)),
                    float(params.get("K", 100)),
                    float(params.get("T", 0.25)),
                    float(params.get("r", 0.05)),
                    float(params.get("sigma", 0.2)),
                    params.get("option_type", "call")
                )
            if task_type == "breakeven":
                return self.finance.break_even(
                    float(params.get("fixed_costs", 0)),
                    float(params.get("variable_cost_per_unit", 0)),
                    float(params.get("price_per_unit", 1))
                )
            if task_type == "cagr":
                return self.finance.cagr(
                    float(params.get("initial", 1000)),
                    float(params.get("final", 2000)),
                    float(params.get("years", 5))
                )
            if task_type == "drawdown":
                return self.finance.max_drawdown(params.get("prices", []))

            # Монте-Карло
            if task_type == "monte_carlo":
                return self.mc.simulate_strategy(
                    float(params.get("win_prob", 0.55)),
                    float(params.get("payoff_ratio", 1.5)),
                    float(params.get("bankroll", 1000)),
                    float(params.get("bet_fraction", 0.1)),
                    int(params.get("n_bets", 100)),
                    int(params.get("n_simulations", 5000))
                )
            if task_type == "portfolio":
                er = params.get("expected_returns", [0.10, 0.08])
                cov = params.get("cov_matrix", [[0.04, 0.01], [0.01, 0.02]])
                rfr = float(params.get("risk_free_rate", 0.02))
                return self.portfolio.optimize_sharpe(er, cov, rfr)

            # Общий — пробуем вычислить как выражение
            return self.cas.evaluate(original_text)

        except Exception as e:
            log.error("MathAgent calculate error: %s", e, exc_info=True)
            return {"error": str(e), "task_type": task_type}

    def _explain(self, question: str, task_type: str,
                 calc_result: Dict, params: Dict, llm) -> str:
        """LLM объясняет результат расчёта человеческим языком."""
        from brain.llm_router import LLMRequest

        if "error" in calc_result:
            error = calc_result["error"]
            # Попробуем ответить без точного расчёта
            req = LLMRequest(
                messages=[{"role": "user", "content": question}],
                system=(
                    "Ты математик. Дай точный, структурированный ответ. "
                    f"Точный движок вернул ошибку: {error}. "
                    "Ответь на основе своих знаний, явно пометив что это теоретический ответ."
                ),
                task_type="math",
                max_tokens=2000,
            )
            resp = llm.ask(req)
            return resp.content if resp.success else f"❌ Ошибка расчёта: {error}"

        # Форматируем результат
        result_json = json.dumps(calc_result, ensure_ascii=False, indent=2)

        explain_prompt = (
            f"ВОПРОС ПОЛЬЗОВАТЕЛЯ:\n{question}\n\n"
            f"ТОЧНЫЙ МАТЕМАТИЧЕСКИЙ РАСЧЁТ (достоверный результат движка):\n"
            f"```json\n{result_json[:3000]}\n```\n\n"
            f"Объясни результат:\n"
            f"1. Ответь прямо на вопрос пользователя\n"
            f"2. Выдели ключевые числа жирным (**число**)\n"
            f"3. Объясни что значат числа простым языком\n"
            f"4. Если есть поле 'interpretation' — используй его как основу\n"
            f"5. Добавь практическую рекомендацию\n"
            f"6. Если финансовый расчёт — добавь дисклеймер о рисках\n"
            f"Язык: тот же что у пользователя (русский/английский)"
        )
        req = LLMRequest(
            messages=[{"role": "user", "content": explain_prompt}],
            system="Ты финансовый аналитик и математик. Объясняй точно и практично.",
            task_type="analysis",
            max_tokens=2000,
        )
        resp = llm.ask(req)
        if not resp.success:
            # Fallback — форматируем JSON красиво
            return self._format_result_fallback(task_type, calc_result)

        return resp.content

    def _format_result_fallback(self, task_type: str,
                                result: Dict) -> str:
        """Форматирование без LLM — если LLM недоступен."""
        lines = [f"📐 **Результат расчёта [{task_type.upper()}]**\n"]
        for k, v in result.items():
            if k == "interpretation":
                lines.append(f"\n💡 {v}")
            elif k == "formula":
                lines.append(f"\n🔢 Формула: `{v}`")
            elif k == "error":
                lines.append(f"\n❌ Ошибка: {v}")
            elif isinstance(v, float):
                lines.append(f"  {k}: **{v:.4f}**")
            elif isinstance(v, (int, str)):
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)

    def get_status(self) -> str:
        engines = []
        if HAS_SYMPY:
            engines.append("SymPy(CAS)")
        if HAS_NUMPY:
            engines.append("NumPy")
        if HAS_SCIPY:
            engines.append("SciPy(Stats)")
        engines.append("Finance(built-in)")
        engines.append("MonteCarlo")
        return f"MathAgent: {', '.join(engines)}"

    def capabilities_text(self) -> str:
        """Описание возможностей для системного промта."""
        return (
            "MathAgent — точный математический / финансовый движок:\n"
            "  Символьная математика: решение уравнений, производные, интегралы, упрощение\n"
            "  Статистика: распределения, мат.ожидание, байесовский вывод, доверительные интервалы\n"
            "  Финансы: NPV, IRR, ROI, CAGR, сложный процент, точка безубыточности\n"
            "  Риск: VaR, CVaR, просадка, коэффициент Шарпа/Сортино\n"
            "  Ставки: критерий Келли (оптимальный размер позиции)\n"
            "  Опционы: модель Блэка-Шоулза (цена + Greeks)\n"
            "  Монте-Карло: симуляция стратегий, портфелей, оптимальная доля\n"
            "  Портфель: оптимизация Марковица (максимальный Шарп, минимальная дисперсия)\n"
            "ИИ НЕ считает сам — вызывает этот движок для точных результатов."
        )
