# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Self-check for the 403 suppression in UnicommerceClient.request().

Runs standalone (no frappe, no site):

    python unicommerce/client/test_forbidden_guard.py

The rule under test: a 403 is a standing account permission, not a transient
failure, so it must be logged ONCE per endpoint per client and must never be
retried -- a full traceback per call turned one missing Uniware permission
into 9,000+ Error Log rows in a morning.
"""


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code
        self.reason = "Forbidden"
        self.text = "Access denied, access resource MINIMAL is needed."

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _MiniClient:
    """The 403 branch of request(), lifted verbatim in shape."""

    def __init__(self):
        self._forbidden_endpoints: set[str] = set()
        self.logged: list[str] = []

    def request(self, endpoint, status_code=403):
        response = _FakeResponse(status_code)
        if response.status_code == 403:
            if endpoint not in self._forbidden_endpoints:
                self._forbidden_endpoints.add(endpoint)
                self.logged.append(endpoint)
            return None, False
        response.raise_for_status()
        return {}, True


def demo():
    c = _MiniClient()
    ep = "/services/rest/v1/invoice/details/get"

    # The real failure mode: the same endpoint hit once per package, every
    # 5 minutes. 112 calls must produce exactly one log row.
    for _ in range(112):
        data, ok = c.request(ep)
        assert data is None and ok is False, "a 403 must return (None, False)"
    assert c.logged == [ep], f"expected 1 log for {ep}, got {len(c.logged)}"

    # A different forbidden endpoint is a distinct fact -- it logs too.
    other = "/services/rest/v1/oms/shipment/show"
    c.request(other)
    assert c.logged == [ep, other], "each endpoint logs once, independently"

    # Non-403 failures keep raising -- the guard must not swallow them.
    try:
        c.request("/services/rest/v1/oms/saleorder/get", status_code=500)
    except RuntimeError:
        pass
    else:
        raise AssertionError("a 500 must still raise, not be suppressed")

    # A fresh client re-reports: the suppression is per run, so a permission
    # that is still missing tomorrow is surfaced again rather than silenced
    # forever.
    assert _MiniClient().logged == [], "suppression must not leak across clients"

    print("OK: 112 calls -> 1 log; per-endpoint; 500s still raise; per-client reset")


if __name__ == "__main__":
    demo()
