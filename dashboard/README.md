# Dashboard build

`python dashboard/build.py` turns `data/` into the JSON files behind the veg oil market dashboard (written to `dashboard/out/`, not committed).

- `events.json`: event calendar (official and expected dates), maintained by hand or by Claude.
- `intel.json`: dated news and physical-flow items with public source links, refreshed by Claude's weekday scheduled task.

All inputs are public, delayed data. Nothing here touches positions or company systems.
