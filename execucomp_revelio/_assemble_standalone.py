import re
base = "execucomp_revelio/"
mods = ["config","jobcat","names","schema","loaders","universe","crosswalk",
        "matching","workhistory","mobility","panels","report","export","build_database"]
QUAL = re.compile(r"\b(config|schema|universe|crosswalk|matching|mobility|panels|report|jobcat)\.")
out = ['"""Self-contained build pipeline (auto-assembled from execucomp_revelio).',
       '',
       'Reads the six WRDS CSVs and writes the SQLite DB + panels/exports.',
       'Run with no args (defaults to ./wrds_csv -> ./out):  python standalone.py',
       '"""', '']
for m in mods:
    src = open(base + m + ".py").read().splitlines()
    keep, skip_paren = [], False
    for ln in src:
        if skip_paren:
            if ")" in ln:
                skip_paren = False
            continue
        if re.match(r"\s*from \.\w* import", ln):
            if "(" in ln and ")" not in ln:
                skip_paren = True
            continue
        if m == "build_database" and ln.startswith("if __name__"):
            break  # drop the package main guard; we add our own below
        keep.append(ln)
    body = QUAL.sub("", "\n".join(keep))
    out.append(f"\n# ===== {m}.py =====\n" + body)

out.append('''
if __name__ == "__main__":
    import sys
    if len(sys.argv) == 1:
        sys.argv += ["--funda", "wrds_csv/compustat_funda.csv",
                     "--index", "wrds_csv/compustat_idxcst_his.csv",
                     "--execucomp", "wrds_csv/execucomp_anncomp.csv",
                     "--individual", "wrds_csv/revelio_individual.csv",
                     "--positions", "wrds_csv/revelio_positions.csv",
                     "--company-mapping", "wrds_csv/revelio_company_mapping.csv",
                     "--output", "execucomp_revelio.db", "--export-dir", "out"]
    main()
''')
open(base + "standalone.py", "w").write("\n".join(out) + "\n")
print("wrote", base + "standalone.py")
