import os
import sys

if not sys.platform.startswith('win32'):
    print("Error: portable-msvc only works on Windows", file=sys.stderr)
    sys.exit(1)
