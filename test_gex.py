import numpy as np
from scipy.stats import norm

def bs_gamma(S, K, T, r, sigma):
    if sigma <= 0 or T <= 0:
        return 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return norm.pdf(d1) / (S * sigma * np.sqrt(T))

gamma = bs_gamma(6700, 6700, 1/365, 0.05, 0.20)
print(f"Test Gamma: {gamma}")
