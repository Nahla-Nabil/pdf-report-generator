"""Print the report data as JSON — a quick look at the numbers.

    python show_report.py
"""

import json

from report_data import get_report_data

if __name__ == "__main__":
    print(json.dumps(get_report_data(), indent=2))
