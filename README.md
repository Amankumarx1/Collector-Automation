# Microsoft Learn Dataset Collector

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![Playwright](https://img.shields.io/badge/playwright-v1.40%2B-green.svg)](https://playwright.dev/python/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An automation system designed to collect, deduplicate, and compile all **Modules**, **Learning Paths**, and **Courses** from the official Microsoft Learn training catalog into a clean JSON dataset.

Built with Python and Playwright, this collector features a robust, stateful architecture capable of handling long-duration crawls (4,600+ items) over dynamic pagination securely and efficiently.

---

## ✨ Features

- 🔄 **Stateful Resumption:** Interrupted crawls resume instantly from the exact page they left off using the progressive `skip` URL offsets (e.g., `?skip=120`).
- 🎯 **Double-Scoped Smart Pagination:** Targets navigation elements precisely within `nav[aria-label="pagination"]` to avoid collisions with other hidden buttons.
- 🧹 **Dynamic Deduplication:** Automatically parses existing `data/modules.json` on startup to populate a memory-cached filter set, preventing duplicate scraping.
- 🛡️ **Anti-Detection Mechanics:** Utilizes realistic viewport scaling, human-like action delays (`1.5s` to `3.0s`), and custom user agents to crawl safely.
- 🩺 **Resilient Error Recovery & Screenshots:** Every page load, card extraction, and click incorporates a **3x retry cycle** with exponential backoff. Captures local high-resolution screenshots on persistent failures for rapid debugging.
- 📊 **Detailed Logs:** Prints elegant status outputs to the console and compiles extensive machine logs in `logs/scraper.log`.

---

## 🛠️ Project Structure

```text
Collector Automation/
├── data/
│   └── modules.json        # Compiled unique JSON dataset
├── logs/
│   └── scraper.log         # Complete execution log trail
├── screenshots/            # Failure snapshots for debugging
├── .gitignore              # Standard git exclusion rules
├── progress.json           # Tracks crawler state for resumption
├── requirements.txt        # Playwright dependencies
├── scraper.py              # Main crawler implementation
└── README.md               # Repository documentation
```

---

## 🚀 Getting Started

### 1. Prerequisites

Ensure you have Python 3.8+ installed on your system. 

### 2. Installation

Clone the repository and install the dependencies:
```bash
pip install -r requirements.txt
python -m playwright install chromium
```

### 3. Usage

#### Headless Mode (Standard Production Run)
Runs the browser invisibly in the background, consuming minimal system resources:
```bash
python scraper.py
```

#### Headed Mode (Visual Debugging)
Launches a visible Chromium window so you can watch the crawler scroll, paginate, and parse elements in real-time:
```bash
python scraper.py --headed
```

#### Aborting & Resuming
Press `Ctrl + C` in your terminal to pause execution at any time. The system will save its exact state to `progress.json`. Run the script again to resume instantly from where you left off.

---

## 📊 Dataset Format (`modules.json`)

The final output is saved inside `data/modules.json` as a clean, standardized array of unique entries:

```json
[
  {
    "name": "Describe cloud service types",
    "type": "module"
  },
  {
    "name": "Introduction to Cloud Infrastructure: Describe cloud concepts",
    "type": "learning path"
  },
  {
    "name": "Introduction to Cloud Infrastructure",
    "type": "course"
  }
]
```

---

## ⚖️ License

Distributed under the MIT License. See [LICENSE](LICENSE) or search online for more information.
