"""e2e с браузером — по одному на сервер (замок ``browser``, tests/heavy_lock.py). Подключается строкой
``import _onebrowser  # noqa: F401`` в начале скрипта."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import heavy_lock

heavy_lock.hold("browser", os.path.basename(sys.argv[0]))
