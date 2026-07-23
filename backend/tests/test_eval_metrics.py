"""Unit tests for the pure eval calibration metrics."""
from evals.metrics import cohen_kappa, mode_fraction, pearson, pstdev, spearman


def test_pstdev_zero_for_constant():
    assert pstdev([5, 5, 5]) == 0.0
    assert pstdev([7]) == 0.0


def test_spearman_perfect_monotonic():
    assert abs(spearman([1, 2, 3, 4], [10, 20, 30, 40]) - 1.0) < 1e-9
    assert abs(spearman([1, 2, 3, 4], [40, 30, 20, 10]) + 1.0) < 1e-9


def test_spearman_handles_ties_and_constant():
    # Constant series has no variance → defined as 0 correlation.
    assert spearman([1, 2, 3], [5, 5, 5]) == 0.0


def test_pearson_monotonic_but_nonlinear_is_below_one():
    r = pearson([1, 2, 3, 4], [1, 4, 9, 16])
    assert 0.9 < r < 1.0  # strong but not perfectly linear


def test_cohen_kappa_perfect_and_chance():
    assert cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    # Total disagreement with balanced marginals → negative kappa.
    assert cohen_kappa(["a", "a", "b", "b"], ["b", "b", "a", "a"]) < 0.0


def test_cohen_kappa_constant_identical_is_one():
    assert cohen_kappa(["x", "x", "x"], ["x", "x", "x"]) == 1.0


def test_mode_fraction():
    assert mode_fraction(["a", "a", "a"]) == 1.0
    assert mode_fraction(["a", "a", "b"]) == 2 / 3
