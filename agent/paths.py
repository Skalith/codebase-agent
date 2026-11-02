import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKPOINT_DB_PATH = os.path.join(PROJECT_ROOT, ".checkpoints.sqlite")
