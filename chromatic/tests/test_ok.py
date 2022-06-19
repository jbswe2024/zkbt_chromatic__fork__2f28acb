from ..rainbows import *
from .setup_tests import *


def test_ok_rows_and_columns():
    s = SimulatedRainbow().inject_noise()
    s.wavelike["ok"] = np.arange(s.nwave) > 10
    s.timelike["ok"] = np.arange(s.ntime) > 5
    s.fluxlike["ok"] = np.ones(s.shape)
    assert s.ok[0, 0] == 0
    assert s.ok[-1, -1] == 1
    assert np.all(s.ok[:10, :] == 0)
    assert np.all(s.ok[:, :5] == 0)


def test_bin_with_not_ok_data():
    for ok_fraction in [0, 0.01, 0.5, 0.99, 1]:
        a = (
            SimulatedRainbow(dt=2 * u.minute, dw=0.2 * u.micron)
            .inject_transit()
            .inject_noise()
        )
        a.ok = np.random.uniform(size=a.shape) < ok_fraction

        if ok_fraction == 0:
            with pytest.raises(RuntimeError):
                should_fail = a.bin(
                    dw=0.7 * u.micron, dt=20 * u.minute, minimum_acceptable_ok=1
                )
            continue

        cautious = a.bin(dw=0.7 * u.micron, dt=20 * u.minute, minimum_acceptable_ok=1)
        carefree = a.bin(
            dw=0.7 * u.micron, dt=20 * u.minute, minimum_acceptable_ok=0, trim=False
        )
        assert np.all((cautious.ok == 1) | (cautious.ok == 0))
        if np.any(a.ok == 0):
            assert np.any((carefree.ok != 1) & (carefree.ok != 0))


def test_get_ok_data_helpers(quantity="flux"):
    s = SimulatedRainbow(dw=0.5 * u.micron, dt=20 * u.minute).inject_noise()
    s.ok = np.random.uniform(0, 1, s.shape) > 0.5
    s.imshow()

    fi, ax = plt.subplots(2, 2, sharex="col", sharey=True, constrained_layout=True)
    for r, e in enumerate([False, True]):
        ax[r, 0].set_title(f"express_badness_with_uncertainty={e}")

        for c, f in enumerate([s.get_ok_data_for_wavelength, s.get_ok_data_for_time]):
            for i in range(3):
                x, y, sigma = f(
                    i, quantity=quantity, express_badness_with_uncertainty=e
                )
                ax[r, c].scatter(x, y - i * 0.2, c=np.isfinite(sigma))
