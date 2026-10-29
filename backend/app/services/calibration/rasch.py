"""Rasch (1PL) calibration by Marginal Maximum Likelihood with EM (Bock–Aitkin).

* Ability distribution fixed to N(0, 1) for identification; items are on a common logit scale only when
  the administration design is *linked* (forms share items). A disconnected design is refused.
* Handles incomplete designs (each person sees only their form's items).
* Returns item difficulty b with asymptotic SE (inverse expected information), EAP person abilities with
  posterior SD, and outfit mean-square fit for each item.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components


@dataclass
class RaschResult:
    items: np.ndarray          # item ids (as given)
    b: np.ndarray
    se: np.ndarray
    outfit: np.ndarray
    persons: np.ndarray
    theta: np.ndarray
    theta_sd: np.ndarray
    iterations: int
    converged: bool
    loglik: float


class RaschNotIdentified(ValueError):
    pass


def design_components(person_idx: np.ndarray, item_idx: np.ndarray, n_items: int, n_persons: int) -> int:
    m = sparse.coo_matrix((np.ones(len(person_idx)), (person_idx, item_idx)), shape=(n_persons, n_items)).tocsr()
    co = (m.T @ m)  # item × item co-administration
    n_comp, _ = connected_components(co, directed=False)
    return int(n_comp)


def fit_rasch(person_ids, item_ids, x, n_quad: int = 31, max_iter: int = 300, tol: float = 1e-4) -> RaschResult:
    person_ids, item_ids, x = np.asarray(person_ids), np.asarray(item_ids), np.asarray(x, dtype=float)
    persons, p_idx = np.unique(person_ids, return_inverse=True)
    items, i_idx = np.unique(item_ids, return_inverse=True)
    P, I = len(persons), len(items)
    if design_components(p_idx, i_idx, I, P) > 1:
        raise RaschNotIdentified("Administration design is disconnected (no common items linking forms)")

    q = np.linspace(-5, 5, n_quad)
    w = np.exp(-0.5 * q ** 2)
    w /= w.sum()
    # sparse indicator matrices for correct / incorrect observations
    X1 = sparse.csr_matrix((x, (p_idx, i_idx)), shape=(P, I))
    X0 = sparse.csr_matrix((1 - x, (p_idx, i_idx)), shape=(P, I))
    pc = np.asarray(X1.sum(0)).ravel() / np.maximum(np.asarray((X1 + X0).sum(0)).ravel(), 1)
    b = -np.log(np.clip(pc, 0.02, 0.98) / (1 - np.clip(pc, 0.02, 0.98)))  # logit start
    converged = False
    it = 0
    for it in range(1, max_iter + 1):
        logit = q[None, :] - b[:, None]                      # I × Q
        logp, logq_ = -np.logaddexp(0, -logit), -np.logaddexp(0, logit)
        L = X1 @ logp + X0 @ logq_ + np.log(w)[None, :]      # P × Q (log joint)
        m = L.max(1, keepdims=True)
        post = np.exp(L - m)
        norm = post.sum(1, keepdims=True)
        loglik = float((m.ravel() + np.log(norm.ravel())).sum())
        post /= norm
        r = np.asarray(X1.T @ post)                          # expected correct at each node, I × Q
        n = np.asarray((X1 + X0).T @ post)                   # expected attempts at each node
        prob = 1 / (1 + np.exp(-logit))
        grad = (n * prob - r).sum(1)                         # d logL / d b
        info = (n * prob * (1 - prob)).sum(1)
        step = np.clip(grad / np.maximum(info, 1e-9), -1.0, 1.0)
        b = b + step
        if float(np.abs(step).max()) < tol and it > 3:
            converged = True
            break
    se = 1 / np.sqrt(np.maximum(info, 1e-9))
    theta = post @ q
    theta_sd = np.sqrt(np.maximum(post @ q ** 2 - theta ** 2, 0))
    # outfit MSQ using EAP abilities
    th = theta[p_idx]
    pr = 1 / (1 + np.exp(-(th - b[i_idx])))
    z2 = (x - pr) ** 2 / np.maximum(pr * (1 - pr), 1e-9)
    outfit = np.bincount(i_idx, weights=z2, minlength=I) / np.maximum(np.bincount(i_idx, minlength=I), 1)
    return RaschResult(items, b, se, outfit, persons, theta, theta_sd, it, converged, loglik)
