"""AIHR: сопоставление резюме с вакансиями."""

import warnings

__version__ = "0.1.0"

# pymorphy2 внутри Natasha импортирует pkg_resources; setuptools закреплён на 80.x (pyproject.toml)
warnings.filterwarnings("ignore", message="pkg_resources is deprecated", category=UserWarning)
