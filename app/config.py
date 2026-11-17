"""Static config for the Momentum dashboard POC mock."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "momentum.db"

# Real data exported from Forcelink by tools/export_from_db.py. When present, app.seed loads it instead of
# generating data. Git-ignored: it holds real names and comments.
PROD_DATA_PATH = BASE_DIR / "prod_data.sql"

API_VERSION = "1"

# Hardcoded partner API key (POC only - a real UAT key is issued out of band).
API_KEY = "fl_uat_momentum_7f3c9a21d4e84b0c95e6"

# Bearer token accepted as an alternative to X-Api-Key (spec lists bearerAuth
# "for testing with mock API").
BEARER_TOKEN = API_KEY

# Sites / stores this key is scoped to. Anything outside these -> 403 FORBIDDEN.
# 4021-4025 are the generated sites; 542-544 are the real Momentum sites that
# tools/export_from_forcelink.py loads (Cape Town, Centurion, Sandton).
SCOPED_ORG_UNIT_IDS = [4021, 4022, 4023, 4024, 4025, 542, 543, 544]
SCOPED_STORE_IDS = [12, 13, 14, 15]

MAX_RANGE_DAYS = 92
DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 500
