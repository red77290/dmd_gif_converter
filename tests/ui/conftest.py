import pytest
from unittest.mock import MagicMock
import tkinter as tk

# Mock tk variables to avoid Tkinter initialization in UI tests completely
tk.BooleanVar = MagicMock
tk.StringVar = MagicMock
tk.IntVar = MagicMock
tk.DoubleVar = MagicMock
