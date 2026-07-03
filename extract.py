#!/usr/bin/env python3
import argparse, csv, re, sys, warnings
from pathlib import Path
from difflib import SequenceMatcher

import pandas as pd

warnings.filterwarnings("ignore")


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def load_file(path: str) -> pd.DataFrame:
    p = Path(path)
    if p.suffix == ".pdf":
        import pdfplumber

        rows = []
        with pdfplumber.open(p) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        rows.append([c.strip() if c else "" for c in row])
        if not rows:
            sys.exit(f"No tables found in {path}")
        return pd.DataFrame(rows[1:], columns=rows[0])
    elif p.suffix in (".xls", ".xlsx"):
        return pd.read_excel(p, dtype=str)
    elif p.suffix in (".csv", ".tsv"):
        sep = "\t" if p.suffix == ".tsv" else ","
        return pd.read_csv(p, sep=sep, dtype=str)
    else:
        sys.exit(f"Unsupported format: {p.suffix}")


def normalize_column(name: str) -> str:
    name = name.lower().strip().rstrip(".:;$#")
    name = re.sub(r"[ _\-]+", "_", name)
    mapping = {
        r"precio|price|\$|cost": "price",
        r"stock|inventario|qty|cantidad": "stock",
        r"sku|code|codigo|id_producto": "sku",
        r"nombre|name|producto|product|title|descripcion": "name",
        r"marca|brand": "brand",
        r"categoria|category": "category",
    }
    for pattern, replacement in mapping.items():
        if re.fullmatch(pattern, name):
            return replacement
    return name


def clean(df: pd.DataFrame) -> pd.DataFrame:
    # Drop fully empty rows/cols
    df = df.dropna(how="all").dropna(axis=1, how="all")
    # Normalize column names
    df.columns = [normalize_column(c) for c in df.columns]
    # Drop duplicate columns
    df = df.loc[:, ~df.columns.duplicated()]
    # Normalize price column
    if "price" in df.columns:
        df["price"] = (
            df["price"]
            .astype(str)
            .str.replace(r"[^\d.,]", "", regex=True)
            .str.replace(".", "", regex=False)
            .str.replace(",", ".", regex=False)
        )
        df["price"] = pd.to_numeric(df["price"], errors="coerce").fillna(0).astype(int)
    # Fuzzy dedup on name
    if "name" in df.columns:
        seen, keep = [], []
        names = df["name"].astype(str).tolist()
        for n in names:
            dup = any(_similar(n, s) > 0.85 for s in seen)
            if not dup:
                seen.append(n)
                keep.append(True)
            else:
                keep.append(False)
        df = df[keep].reset_index(drop=True)
    return df


def main():
    parser = argparse.ArgumentParser(description="Extract & clean data from PDF/Excel")
    parser.add_argument("input", help="Path to PDF or Excel file")
    parser.add_argument("--output", "-o", default=None, help="Output CSV path")
    parser.add_argument("--sheets", action="store_true", help="Push to Google Sheets")
    args = parser.parse_args()

    df = load_file(args.input)
    df = clean(df)

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    if args.output:
        out_path = Path(args.output)
    else:
        stem = Path(args.input).stem
        out_path = output_dir / f"{stem}_clean.csv"

    df.to_csv(out_path, index=False)
    print(f"✓ Cleaned {len(df)} rows → {out_path}")

    if args.sheets:
        try:
            import gspread
            from google.auth.exceptions import DefaultCredentialsError

            gc = gspread.service_account()
            sh = gc.open(input("Paste Google Sheets name: "))
            sh.sheet1.clear()
            sh.sheet1.update([df.columns.tolist()] + df.values.tolist())
            print(f"✓ Pushed to Google Sheets: {sh.title}")
        except ImportError:
            sys.exit("Install gspread: pip install gspread")
        except DefaultCredentialsError:
            sys.exit("Set up Google service account: https://docs.gspread.org/")


if __name__ == "__main__":
    main()
