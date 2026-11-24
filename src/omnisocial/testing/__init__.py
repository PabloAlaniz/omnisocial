"""Para probar una red sin red de verdad: un transporte falso y el contrato que toda red cumple.

```python
from omnisocial.testing import FakeTransport, NetworkHarness, ProviderContract


class TestMiRed(ProviderContract):
    def harness(self) -> NetworkHarness:
        return MiRedHarness()
```

No depende de pytest: las pruebas del contrato son métodos comunes que lanzan `AssertionError`.
"""

from omnisocial.testing.contract import NetworkHarness, ProviderContract
from omnisocial.testing.transport import FakeTransport, RecordedCall

__all__ = ["FakeTransport", "NetworkHarness", "ProviderContract", "RecordedCall"]
