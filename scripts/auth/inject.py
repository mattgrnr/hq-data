"""Put the shared sign-in code into each HQ Worker.
usage: python3 scripts/auth/inject.py [site ...]   (default: all six)
Each worker's `export default {` becomes `const HQ_APP = {`; the shared code and the wrapped
export go at the end of the file. Safe to run again: the old block is replaced."""
import pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
SITES = {"total": "total-hq", "slam": "slam-hq", "slapshot": "slapshot-hq", "touchdown": "touchdown-hq", "futbol": "futbol-hq", "moonshot": "moonshot-hq"}
START = "// ==== HQ ACCOUNTS"

for site in sys.argv[1:] or list(SITES):
    path = ROOT / "sites" / site / "worker.js"
    src = path.read_text()
    if START in src:
        src = src[:src.index(START)].rstrip() + "\n"
    if "\nexport default {" in src:
        src = src.replace("\nexport default {", "\nconst HQ_APP = {", 1)
    assert "\nconst HQ_APP = {" in src, site
    block = (HERE / "gate.js").read_text()
    if site == "total":
        block += "\n" + (HERE / "total.js").read_text()
    auth = "hqaAuth" if site == "total" else "null"
    src += "\n" + block + f'\nexport default hqaWrap(HQ_APP, "{SITES[site]}", {auth});\n'
    path.write_text(src)
    print(site, "ok")
