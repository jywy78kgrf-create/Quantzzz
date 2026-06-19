import sys
from pathlib import Path

# Make the subproject root importable (firewall/, eval/) when pytest is run
# from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent))
