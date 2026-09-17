"""Static config for the Momentum dashboard POC mock."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "momentum.db"

API_VERSION = "1"

# Hardcoded partner API key (POC only - a real UAT key is issued out of band).
API_KEY = "fl_uat_momentum_7f3c9a21d4e84b0c95e6"

# Bearer token accepted as an alternative to X-Api-Key (spec lists bearerAuth
# "for testing with mock API").
BEARER_TOKEN = API_KEY

# Sites / stores this key is scoped to. Anything outside these -> 403 FORBIDDEN.
SCOPED_ORG_UNIT_IDS = [4021, 4022, 4023, 4024, 4025]
SCOPED_STORE_IDS = [12, 13, 14, 15]

MAX_RANGE_DAYS = 92
DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 500
